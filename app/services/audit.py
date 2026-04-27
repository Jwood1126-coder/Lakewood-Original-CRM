"""Automatic audit logging via SQLAlchemy session events.

How it works:
1. We hook `before_flush` on the SQLAlchemy session.
2. For each "tracked" model in the session's new/dirty/deleted sets,
   we capture before/after column values and append an AuditLog row to
   the same session.
3. Because we add the AuditLog inside before_flush, it commits atomically
   with the original change — either both succeed or both roll back.

Models we track: Client, Property, Job, Visit, Quote, Invoice, LineItem,
Payment. Internal/operational models (Setting, Conversation, Message,
Notification, AuditLog itself, User) are NOT tracked — they'd just be
noise and Setting changes are already audited by the value being timestamped.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time as dt_time
from decimal import Decimal

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, attributes


# Set in init_audit() once create_app has loaded the models
_TRACKED_MODELS: set[type] = set()


def init_audit(app) -> None:
    """Wire the audit listeners. Call once from create_app()."""
    # Lazy import to avoid pulling models at module import time
    from app.models.client import Client
    from app.models.invoice import Invoice
    from app.models.job import Job
    from app.models.line_item import LineItem
    from app.models.payment import Payment
    from app.models.property import Property
    from app.models.quote import Quote
    from app.models.visit import Visit

    _TRACKED_MODELS.update({Client, Property, Job, Visit, Quote, Invoice,
                             LineItem, Payment})
    app.logger.info("Audit listener tracking %d model types", len(_TRACKED_MODELS))


def _is_tracked(obj) -> bool:
    return type(obj) in _TRACKED_MODELS


def _value_for_json(v):
    """Cast SQL types to JSON-friendly forms."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (datetime, date, dt_time)):
        return v.isoformat()
    if isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


def _snapshot_columns(obj) -> dict:
    """Snapshot every mapped column on `obj` to a JSON-safe dict."""
    insp = inspect(obj)
    out = {}
    for col in insp.mapper.columns:
        try:
            out[col.key] = _value_for_json(getattr(obj, col.key))
        except Exception:
            pass
    return out


def _changed_columns(obj) -> dict:
    """For UPDATE: return {col: (before, after)} of actually-changed columns.

    Uses PASSIVE_OFF so the original DB value is loaded if the session
    expired the attribute (which it does after commit by default).
    """
    insp = inspect(obj)
    out = {}
    column_keys = {c.key for c in insp.mapper.columns}
    for key in column_keys:
        try:
            h = attributes.get_history(obj, key, passive=attributes.PASSIVE_OFF)
        except Exception:
            continue
        if not h.has_changes():
            continue
        before = _value_for_json(h.deleted[0]) if h.deleted else None
        after = _value_for_json(h.added[0])  if h.added else None
        out[key] = (before, after)
    return out


def _actor() -> tuple[str | None, str]:
    try:
        from flask import has_request_context
        from flask_login import current_user
        if has_request_context() and current_user.is_authenticated:
            return current_user.email, "user"
    except Exception:
        pass
    return None, "system"


def _summary_for_change(obj, op: str, changes: dict | None) -> str:
    name = type(obj).__name__
    pk = getattr(obj, "id", None)
    label = f"{name} #{pk}" if pk else name

    if op == "insert":
        return f"Created {label}"
    if op == "delete":
        return f"Deleted {label}"
    if changes:
        # Prefer status changes for a punchy summary
        if "status" in changes:
            b, a = changes["status"]
            return f"{label} status: {b} → {a}"
        first_key = next(iter(changes))
        b, a = changes[first_key]
        s = f"{label} {first_key}: {b!r} → {a!r}"
        if len(changes) > 1:
            s += f" (+{len(changes)-1} more)"
        return s
    return f"Updated {label}"


_REGISTERED_SESSIONS: set[int] = set()


def register_session_events(session_factory) -> None:
    """Attach session listeners. Idempotent — calling twice is a no-op.

    - before_flush: snapshot the changes (before/after column values) and
      stash them on the session.
    - after_flush: now that auto-increment IDs are assigned, materialize
      AuditLog rows with the correct entity_ids.

    Both phases run inside the same transaction, so audit rows commit
    atomically with the original change.
    """
    sid = id(session_factory)
    if sid in _REGISTERED_SESSIONS:
        return
    _REGISTERED_SESSIONS.add(sid)

    @event.listens_for(session_factory, "before_flush")
    def _capture_changes(session: Session, flush_context, instances):
        actor_email, actor_kind = _actor()
        now = datetime.utcnow()

        pending = []  # list of (obj, op, before, after, summary)

        for obj in list(session.new):
            if not _is_tracked(obj):
                continue
            pending.append((obj, "insert", None, _snapshot_columns(obj),
                            _summary_for_change(obj, "insert", None)))

        for obj in list(session.dirty):
            if not _is_tracked(obj):
                continue
            if not session.is_modified(obj, include_collections=False):
                continue
            changes = _changed_columns(obj)
            if not changes:
                continue
            before = {k: v[0] for k, v in changes.items()}
            after = {k: v[1] for k, v in changes.items()}
            pending.append((obj, "update", before, after,
                            _summary_for_change(obj, "update", changes)))

        for obj in list(session.deleted):
            if not _is_tracked(obj):
                continue
            pending.append((obj, "delete", _snapshot_columns(obj), None,
                            _summary_for_change(obj, "delete", None)))

        # Stash for after_flush, plus the actor info captured at change-time
        if pending:
            session.info.setdefault("_audit_pending", []).append({
                "rows": pending, "actor_email": actor_email,
                "actor_kind": actor_kind, "now": now,
            })

    @event.listens_for(session_factory, "after_flush")
    def _materialize_audit_rows(session: Session, flush_context):
        from app.models.audit_log import AuditLog
        batches = session.info.pop("_audit_pending", None)
        if not batches:
            return

        for batch in batches:
            for obj, op, before, after, _stale_summary in batch["rows"]:
                # IDs are now assigned for inserts (post-autoincrement)
                entity_id = getattr(obj, "id", None)
                # Re-snapshot inserts so we capture server defaults + the new id
                if op == "insert":
                    after = _snapshot_columns(obj)
                # Regenerate summary now that the id is known
                if op == "update":
                    # Reconstruct {key: (before, after)} for the helper
                    changes_for_summary = {
                        k: (before.get(k) if before else None,
                            after.get(k)  if after else None)
                        for k in (after or before or {}).keys()
                    }
                else:
                    changes_for_summary = None
                summary = _summary_for_change(obj, op, changes_for_summary)
                row = AuditLog(
                    created_at=batch["now"],
                    operation=op,
                    entity_type=type(obj).__name__,
                    entity_id=entity_id,
                    actor_email=batch["actor_email"],
                    actor_kind=batch["actor_kind"],
                    before_json=(json.dumps(before, default=str) if before is not None else None),
                    after_json=(json.dumps(after,  default=str) if after  is not None else None),
                    summary=summary,
                )
                session.add(row)
