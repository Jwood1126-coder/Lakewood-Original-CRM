# PR #16 — M0 Stabilize Review Notes

- **Date:** 2026-05-20
- **PR:** https://github.com/Jwood1126-coder/Lakewood-Original-CRM/pull/16
- **Branch:** `m0-stabilize-issues-2-3-4-5`
- **Base:** `main`
- **Scope:** Fix the four M0 stabilization issues
  ([#2](https://github.com/Jwood1126-coder/Lakewood-Original-CRM/issues/2),
  [#3](https://github.com/Jwood1126-coder/Lakewood-Original-CRM/issues/3),
  [#4](https://github.com/Jwood1126-coder/Lakewood-Original-CRM/issues/4),
  [#5](https://github.com/Jwood1126-coder/Lakewood-Original-CRM/issues/5))
  plus follow-up fixes for blocking findings from independent code review.

---

## What was reviewed

The original PR shipped four fixes (one per M0 issue):

| Issue | Fix |
| ----- | ---- |
| #2 — Settings → Notifications crash | Moved `notify_email_to` (and duplicate `submit`) back onto `NotificationForm` from `JobberClientsImportForm`. (`app/settings/forms.py`) |
| #3 — Quote status guard | Added `_QUOTE_ALLOWED_TRANSITIONS` + `can_transition_to`/`transition_to` on `Quote`, route-level guard, and `/convert-to-job` enforcement so `status='converted'` always has a matching `converted_to_job_id`. (`app/models/quote.py`, `app/quotes/routes.py`) |
| #4 — Intake CORS allow-list | Env-driven `INTAKE_CORS_ORIGINS`; disallowed origins get no ACAO header, disallowed preflights get 403. (`app/config.py`, `app/intake/routes.py`, `.env.example`) |
| #5 — `/jobber/sync/all` blocking | Moved the clients → jobs → quotes → invoices+payments sequence onto a daemon thread; UI polls `/jobber/sync/all/status`. Procfile + railway.json timeouts harmonized at 120s. (`app/services/jobber_sync_runner.py`, `app/jobber/routes.py`, `app/templates/jobber/index.html`, `Procfile`) |

---

## Independent reviewer findings (blocking)

### 1. CORS write-blocking — disallowed POSTs still wrote to the DB

**Symptom.** `/intake/api/request` only suppressed `Access-Control-Allow-Origin`
for disallowed origins. The browser couldn't read the response, but
`_ingest_request` had already executed and committed a `Client` (+ optional
`Property`) + `Quote` to the database. Any random origin on the web could
drive-by write rows.

**Fix.** When the request has an `Origin` header that's not in
`INTAKE_CORS_ORIGINS`, return `403 {ok: false, error: "Origin not allowed"}`
before calling `_ingest_request`. Same-origin / server-side callers (no
`Origin` header) are still allowed through — the rate limiter + honeypot
remain in front of them so the public HTML form keeps working.

**Files.** `app/intake/routes.py` (`api_request`, new `_allowed_origins` helper).

### 2. `start_sync_all` TOCTOU race — could spawn two background threads

**Symptom.** `start_sync_all` acquired `_state_lock`, checked
`_state.running`, **released the lock**, then called `_reset_for_new_run`
which re-acquired the lock to set `running=True`. Two concurrent POSTs to
`/jobber/sync/all` could both observe `running=False`, both call the
reset, and both spawn a daemon thread.

**Fix.** Reset-for-new-run is now an inlined helper (`_reset_for_new_run_locked`)
that the caller invokes while still holding `_state_lock`. The "is anyone
running?" check and the "claim the running slot" write happen as one
atomic step. `run_sync_all_inline` was updated to the same pattern.

**Files.** `app/services/jobber_sync_runner.py`.

---

## Non-blocking caveats (addressed or documented)

### Procfile timeout drop (600 → 120)

The Procfile + railway.json now agree at 120s. The per-stage sync routes
(`/jobber/sync/clients|jobs|quotes|invoices`) are still synchronous — they
do GraphQL fetches without inter-stage sleeps, so they comfortably fit
under 120s for any tenant we expect at M0. If a tenant ever hits the
limit, the documented workaround is the "Pull EVERYTHING" button, which
already runs on the background thread.

**Follow-up.** If we add per-stage backgrounding (M1?), reuse the
`jobber_sync_runner` state machine rather than rolling a parallel one.

### Sync state is in-memory and lost on process restart

Acceptable for M0 (single Gunicorn worker on Railway, no Celery/Redis).
Restart while a sync is running drops the progress log; the next page
load shows "no run in progress" and re-clicking the button starts a
fresh run. Anything already imported is idempotent / skipped, so this
is safe.

**Follow-up.** When/if we move to multi-worker, push state into the DB
(`jobber_sync_runs` table) and key on a run UUID.

### CORS allow-list previously read once at class definition

`Config.INTAKE_CORS_ORIGINS` is still a class-level constant computed
at import time, but the intake routes now read the live value off
`current_app.config` per request via the new `_allowed_origins()`
helper. That means tests (and any future admin-UI override) can
mutate the allow-list at runtime and have it take effect immediately.

### Stage labels in the UI poller

Previously the progress card showed the raw stage key
(`"clients"`, `"invoices"`). Now mapped to friendly labels
("Clients + properties", "Invoices + payments") via a small lookup
in the inline JS. Pure cosmetic.

---

## Tests run

- Full suite: `pytest`
- Result: **76 passed, 0 failed** (was 74; +2 for the new CORS write-block
  test and the concurrent-start regression test).
- Critical new coverage:
  - `tests/test_m0_stabilize.py::TestIssue4IntakeCORS::test_post_from_denied_origin_is_403_and_writes_nothing`
    asserts disallowed-origin POST returns 403 and creates zero
    Client/Property/Quote rows.
  - `tests/test_m0_stabilize.py::TestIssue4IntakeCORS::test_post_with_no_origin_header_still_ingests`
    pins the "server-side / HTML form / no Origin header" path.
  - `tests/test_m0_stabilize.py::TestIssue5SyncAllBackgrounded::test_concurrent_starts_only_one_thread_wins`
    spawns 16 threads racing into `start_sync_all` at a barrier and asserts
    exactly one wins and exactly one background worker thread launches.
    Genuine concurrency probe — not a pre-seeded `running=True`.

---

## Deployment notes / env vars

- `INTAKE_CORS_ORIGINS` (optional). Comma-separated list of full origins
  (`scheme://host[:port]`, no wildcards, no path). Default covers
  `https://lakewoodoriginal.com`, `https://www.lakewoodoriginal.com`,
  and `http://localhost:8000` / `http://127.0.0.1:8000` for dev.
  Override in Railway → Variables when adding a staging origin.
- No new migrations.
- No new packages.
- Gunicorn timeout pinned at 120s in both `Procfile` and `railway.json`.

---

## Files changed in the follow-up commit(s)

- `app/intake/routes.py` — 403 + no writes for disallowed-origin POSTs;
  per-request allow-list read.
- `app/services/jobber_sync_runner.py` — atomic running-slot claim;
  `_reset_for_new_run_locked` helper.
- `app/templates/jobber/index.html` — friendly stage labels in the
  progress card.
- `tests/test_m0_stabilize.py` — denied-origin 403/no-write test,
  no-Origin happy-path test, concurrent-start regression test.
- `docs/pr-16-m0-stabilize-review-notes.md` — this file.
