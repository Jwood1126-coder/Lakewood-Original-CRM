"""Gmail → InboxMessage sync.

Phase 1: pull recent messages, store raw From/Subject/snippet/Date.
Idempotent via the (source, source_message_id) unique constraint.
Parser/matching live in a later phase — kind defaults to 'email' and
client_id stays NULL until then.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from sqlalchemy import select

from app.extensions import db
from app.models.inbox_message import InboxMessage
from app.services import gmail
from app.services import inbox_parser


def _existing_ids(source: str, ids: Iterable[str]) -> set[str]:
    rows = db.session.scalars(
        select(InboxMessage.source_message_id).where(
            InboxMessage.source == source,
            InboxMessage.source_message_id.in_(list(ids)),
        )
    ).all()
    return set(rows)


def _header(headers: list[dict], name: str) -> str | None:
    for h in headers or []:
        if (h.get("name") or "").lower() == name.lower():
            return h.get("value")
    return None


def _split_from(raw: str | None) -> tuple[str | None, str | None]:
    """Split a From: header into (display name, address).

    "Acme Plumbing <billing@acme.com>"  → ("Acme Plumbing", "billing@acme.com")
    "billing@acme.com"                  → (None, "billing@acme.com")
    """
    if not raw:
        return None, None
    raw = raw.strip()
    if "<" in raw and raw.endswith(">"):
        name, _, addr = raw.rpartition("<")
        return (name.strip().strip('"') or None,
                addr[:-1].strip() or None)
    return None, raw or None


def sync_recent(days_back: int = 14, max_messages: int = 200) -> dict:
    """Pull message IDs newer than `days_back` (capped at `max_messages`),
    store any we haven't seen before. Returns a stats dict for the UI flash."""
    stats = {"seen": 0, "created": 0, "skipped_existing": 0,
             "matched": 0, "unmatched": 0, "errors": []}

    # Phase 1 is single-page; for larger backfills use sync_recent's
    # pageToken loop in a later phase.
    page = gmail.list_message_ids(days_back=days_back, max_results=max_messages)
    msg_refs = page.get("messages") or []
    stats["seen"] = len(msg_refs)
    if not msg_refs:
        return stats

    ids = [m["id"] for m in msg_refs if m.get("id")]
    already = _existing_ids("gmail", ids)

    new_msgs: list[InboxMessage] = []
    for ref in msg_refs:
        mid = ref.get("id")
        if not mid:
            continue
        if mid in already:
            stats["skipped_existing"] += 1
            continue
        try:
            full = gmail.get_message(mid, format="metadata")
        except Exception as e:
            stats["errors"].append(f"{mid}: {e!r}")
            continue

        headers = (full.get("payload") or {}).get("headers") or []
        from_raw = _header(headers, "From")
        subject = _header(headers, "Subject")
        from_name, from_addr = _split_from(from_raw)
        received = gmail.parse_internal_date(full.get("internalDate")) or datetime.utcnow()

        msg = InboxMessage(
            source="gmail",
            source_message_id=mid,
            source_thread_id=full.get("threadId"),
            kind="email",  # parser sets the real kind below
            direction="in",
            from_addr=(from_addr or "")[:320] or None,
            from_name=(from_name or "")[:200] or None,
            subject=(subject or "")[:500] or None,
            snippet=(full.get("snippet") or "") or None,
            received_at=received,
        )
        db.session.add(msg)
        new_msgs.append(msg)
        stats["created"] += 1

    if new_msgs:
        applied = inbox_parser.apply_to(new_msgs)
        stats["matched"] = applied["matched"]
        stats["unmatched"] = applied["unmatched"]

    db.session.commit()
    return stats


def poll_gmail() -> dict:
    """Scheduled entry point: pull recent Gmail every 4h.

    Safe to schedule before the operator has connected — returns early if
    no token is stored. days_back=2 covers any 4h gap with margin (the
    next run will dedupe whatever it sees twice).
    """
    from flask import current_app
    from app.services.gmail import is_connected
    if not is_connected():
        return {"skipped": "gmail not connected"}
    try:
        return sync_recent(days_back=2, max_messages=200)
    except Exception as e:
        current_app.logger.exception("Gmail poll failed: %s", e)
        return {"error": repr(e)}
