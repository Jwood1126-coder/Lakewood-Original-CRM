"""Background runner for `/jobber/sync/all` (issue #5).

The all-syncs sequence (clients → jobs → quotes → invoices) inserts 30s
cool-downs between Jobber API stages to stay under their rate-limit
bucket. End-to-end that's ~90s of sleeping plus the real GraphQL work,
which exceeds the 120s Gunicorn timeout configured in railway.json.

To keep the request handler off the critical path we run the sequence
on a daemon thread and let the UI poll a status endpoint. This is
intentionally lightweight (single-worker app, no Celery/Redis): the
runner state lives in process memory, only one all-sync may run at a
time, and progress survives only as long as the worker process. That
matches the rest of the app's deployment model (single Gunicorn worker
on Railway) and keeps the dependency surface unchanged.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from flask import Flask, current_app

# Cool-down between Jobber sync stages (seconds). Pulled out of the
# inline route handler so tests can monkeypatch it down to 0.
STAGE_COOLDOWN_SECONDS = 30


@dataclass
class SyncAllState:
    """In-memory snapshot of the all-sync background run."""

    running: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None
    current_stage: str | None = None  # "clients" | "jobs" | "quotes" | "invoices" | None
    results: list[str] = field(default_factory=list)
    error: str | None = None
    started_by: str | None = None

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "current_stage": self.current_stage,
            "results": list(self.results),
            "error": self.error,
            "started_by": self.started_by,
        }


_state = SyncAllState()
_state_lock = threading.Lock()


def get_state() -> SyncAllState:
    """Return a snapshot (copy) of the current state. Safe to call from
    any thread."""
    with _state_lock:
        return SyncAllState(
            running=_state.running,
            started_at=_state.started_at,
            finished_at=_state.finished_at,
            current_stage=_state.current_stage,
            results=list(_state.results),
            error=_state.error,
            started_by=_state.started_by,
        )


def _reset_for_new_run_locked(started_by: str | None) -> None:
    """Mutate state in place. Caller MUST already hold `_state_lock`.

    Inlining the reset under the existing lock (instead of acquiring it
    a second time) lets `start_sync_all`/`run_sync_all_inline` do the
    "is anyone running?" check and the "claim the slot" write as one
    atomic step. Two concurrent POSTs to `/jobber/sync/all` previously
    raced between releasing the lock for the check and re-acquiring it
    here to set `running = True`, which let both callers start a thread.
    """
    _state.running = True
    _state.started_at = datetime.utcnow()
    _state.finished_at = None
    _state.current_stage = None
    _state.results = []
    _state.error = None
    _state.started_by = started_by


def _set_stage(stage: str | None) -> None:
    with _state_lock:
        _state.current_stage = stage


def _append_result(line: str) -> None:
    with _state_lock:
        _state.results.append(line)


def _finish(error: str | None = None) -> None:
    with _state_lock:
        _state.running = False
        _state.current_stage = None
        _state.finished_at = datetime.utcnow()
        _state.error = error


def _run_clients_stage() -> str:
    """Pull all clients (and their properties) via GraphQL and persist."""
    from app.services.jobber import fetch_all_clients
    from scripts.import_jobber_clients import (
        ClientImport,
        PropertyImport,
        write_clients,
    )

    api_rows = fetch_all_clients(page_size=50)
    parsed = []
    for row in api_rows:
        ci = ClientImport(
            jobber_client_id=row["jobber_client_id"], name=row["name"],
            phone=row["phone"], email=row["email"],
            is_company=row["is_company"], company_name=row["company_name"],
            contact_first=row["contact_first"], contact_last=row["contact_last"],
            lead_source=row["lead_source"], referred_by=row["referred_by"],
            created_at=row["created_at"],
            custom_fields=row.get("custom_fields") or {},
        )
        for p in row["properties"]:
            ci.properties.append(PropertyImport(
                label=p["label"], address_line1=p["address_line1"],
                address_line2=p["address_line2"], city=p["city"],
                state=p["state"], zip_code=p["zip_code"],
                county=p["county"], tax_rate=p["tax_rate"],
                jobber_property_id=p.get("jobber_property_id"),
                custom_fields=p.get("custom_fields") or {},
            ))
        parsed.append(ci)
    r = write_clients(parsed, commit=True)
    s = r["stats"]
    return (
        f"Clients +{s['clients_created']} (skipped {s['clients_skipped_existing']}, "
        f"backfilled {s.get('clients_updated', 0)} client + "
        f"{s.get('properties_updated', 0)} property custom fields); "
        f"properties +{s['properties_created']}"
    )


_REMAINING_STAGES: list[tuple[str, str, str]] = [
    # (state-key, display-label, function name on services.jobber_sync)
    ("jobs", "Jobs", "sync_jobs"),
    ("quotes", "Quotes", "sync_quotes"),
    ("invoices", "Invoices+Payments", "sync_invoices"),
]


def _run_remaining_stage(fn_name: str, label: str) -> str:
    from app.services import jobber_sync as js
    s = getattr(js, fn_name)()
    extra = (f", payments +{s['payments_created']}"
             if "payments_created" in s else "")
    return f"{label} +{s['created']} (skipped {s['skipped_existing']}){extra}"


def _do_run(app: Flask, sleep_fn: Callable[[float], None]) -> None:
    """Body of the background thread. Pushes an app context so SQLAlchemy
    and current_app work. Errors per-stage are caught and recorded so the
    other stages still run."""
    with app.app_context():
        # Clients
        _set_stage("clients")
        try:
            _append_result(_run_clients_stage())
        except Exception as e:
            current_app.logger.exception("All-sync clients step failed")
            _append_result(f"Clients FAILED: {e}")

        # Jobs / Quotes / Invoices+Payments, with cool-downs between stages.
        for key, label, fn_name in _REMAINING_STAGES:
            sleep_fn(STAGE_COOLDOWN_SECONDS)
            _set_stage(key)
            try:
                _append_result(_run_remaining_stage(fn_name, label))
            except Exception as e:
                current_app.logger.exception("All-sync %s step failed", label)
                _append_result(f"{label} FAILED: {e}")

        _finish(error=None)


def start_sync_all(app: Flask, started_by: str | None = None,
                    sleep_fn: Callable[[float], None] = time.sleep) -> bool:
    """Kick off a background all-sync if one isn't already running.

    Returns True if a new run was started, False if one was already in
    progress (the caller can then surface progress via get_state()).

    The "is a run already going?" check and the "claim the running slot"
    write are performed under a single critical section so two concurrent
    POSTs to `/jobber/sync/all` can never both see `running=False` and
    spawn two daemon threads.
    """
    with _state_lock:
        if _state.running:
            return False
        _reset_for_new_run_locked(started_by)

    t = threading.Thread(
        target=_do_run,
        args=(app, sleep_fn),
        name="jobber-sync-all",
        daemon=True,
    )
    t.start()
    return True


def run_sync_all_inline(app: Flask,
                         sleep_fn: Callable[[float], None] = time.sleep) -> SyncAllState:
    """Synchronous variant used by tests (and the CLI, if we ever add one).

    Mutates the same module-level state as the background runner but
    blocks until done. Returns the final state snapshot.
    """
    with _state_lock:
        if _state.running:
            return get_state()
        _reset_for_new_run_locked("inline")
    _do_run(app, sleep_fn)
    return get_state()


def reset_state_for_tests() -> None:
    """Clear in-memory state. Pytest fixture cleanup hook."""
    with _state_lock:
        _state.running = False
        _state.started_at = None
        _state.finished_at = None
        _state.current_stage = None
        _state.results = []
        _state.error = None
        _state.started_by = None
