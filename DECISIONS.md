# Decisions Made

Every non-trivial default chosen during the build, with the reasoning.
If you disagree with any of these, here's where to push back.

---

## Project layout

- **App-factory pattern** (`create_app()` in `app/__init__.py`).
  Why: required for clean tests + Alembic + multiple worker processes.
- **Per-feature blueprints**: `auth/`, `clients/`, `properties/`,
  `jobs/`, `visits/`, `quotes/`, `invoices/`, `reports/`, `assistant/`,
  `settings/`, `intake/`, `jobber/`, `main/`. Each folder has
  `routes.py` and `forms.py`. Templates live under
  `app/templates/<blueprint>/`.
- **`services/` directory for domain logic** (audit, backup, briefing,
  email, events, jobber, jobber_sync, photos, reminders, scheduler,
  assistant, money). Keeps views thin; views call services, services
  don't know about HTTP.
- **`utils/` directory for stateless helpers** (`crypto`, `ohio_tax`,
  `phone`, `service_area`, `timezone`).

## Stack choices

- **Flask 3.0** over Django. Operator's existing stack; right size for
  this app; per-feature blueprints scale fine.
- **SQLAlchemy 2.x typed `Mapped[]` columns** + **Alembic migrations**.
  Modern API, great tooling, well-documented.
- **SQLite (WAL + foreign_keys=ON)** over Postgres. Single-writer
  workload; backup = file copy. WAL mode = better concurrent read
  perf; FK enforcement = catches accidental orphans early.
- **Jinja2 + HTMX 2.0 + Pico.css 2.0**. No build step, no JS framework.
  Server returns HTML fragments for interactivity.
- **Argon2id for password hashing** (`argon2-cffi`). Modern recommended;
  bcrypt is older. Auto-rehash on verify if argon2 params have been upgraded.
- **Sessions, not JWT.** Single user, single browser, no SPA.
- **Flask-Login `session_protection = "strong"`**. Invalidates session on
  IP/user-agent change.
- **Flask-Limiter (in-memory backend)** for login rate limiting. Single
  Gunicorn worker keeps it consistent. 8/min, 30/hr per IP on POST /login.
- **Werkzeug ProxyFix middleware** to honor Railway's `X-Forwarded-Proto`.
  Without it, `url_for(_external=True)` builds `http://` URLs; Jobber's
  OAuth flow rejected the redirect URI. ProxyFix tells Flask the request
  is really HTTPS even though the container received HTTP from the proxy.

## Database

- **`render_as_batch=True` in Alembic env.py.** SQLite can't ALTER TABLE
  directly; batch mode does the copy-table-recreate dance automatically.
- **Initial migrations written by hand** rather than `flask db migrate
  --autogenerate` (since the autogen environment wasn't available at the
  time). Future schema changes use autogenerate.
- **No SQLAlchemy 1.x patterns.** All models use 2.x typed `Mapped[...]`
  columns and `select(...)` queries.
- **Path resolution helper** in `config.py` converts relative
  `sqlite:///./data/app.db` to absolute. Flask-SQLAlchemy treats
  relative paths as relative to instance/, which surprises everyone;
  we anchor to project root.

## Models

- **`User` v1 = single operator.** No role column. When/if a crew
  member is added, add a `role` field via Alembic migration.
- **`Client` has display_phone helper** for `(xxx) xxx-xxxx` rendering.
  Storage is digits-only — separation of storage vs. presentation.
- **`Client.balance_owed_cents` computed property.** Sums open-invoice
  balances. Shown as a red pill on the client view if > $0.
- **`Property` carries `tax_rate` as `Numeric(6,4)`.** Decimal storage
  avoids float math errors in invoicing. Stored as the rate (0.08), not
  percent (8.00) — matches how SQL math will treat it.
- **`Photo` uses nullable-FK polymorphism** (property_id / job_id /
  visit_id; CHECK constraint enforces ≥1 parent). Simpler than
  SQLAlchemy polymorphic_identity; indexes are obvious.
- **`Job.prop` not `Job.property`.** Renamed to avoid shadowing
  Python's `@property` decorator inside the class body.
- **`Invoice.paid_cents` is query-backed**, not a relationship-sum. So a
  freshly-added Payment in the same transaction is included even if
  the relationship cache hasn't refreshed.
- **`Invoice.paid_cents_bulk(ids)` for list views.** One GROUP-BY SUM
  query for many invoices at once. Avoids N+1 on dashboard + A/R aging.
- **Explicit state-machine guards** on Job, Quote, Invoice. Invalid
  transitions raise (or show flash error in the route).
- **`Invoice.has_payments` blocks deletion**. Wrong default to cascade-
  delete payment history with an invoice. Mark Void instead.
- **`LineItem` is shared between Quote and Invoice via two nullable FKs**
  (CHECK constraint requires exactly one). Cleaner than two separate
  tables; same fields and rendering logic.

## Auth

- **Open-redirect guard on `?next=` parameter** (auth/routes.py
  `_is_safe_url`). Blocks `/auth/login?next=https://evil.com` attacks.
- **No password reset flow.** By design — see ARCHITECTURE.md. If you
  forget, run `python -m scripts.create_admin --password new`.
- **Login rate limit** at `8/min, 30/hr` per IP. Friendly 429 page if
  exceeded. Disabled in TESTING config.

## Photos

- **Resize to 1600px long-edge, JPEG quality 85.** Phone photos are
  3-5MB; resized they're ~250-500KB. The original is NOT kept.
- **EXIF auto-rotation** (`ImageOps.exif_transpose`). Phone landscape/
  portrait orientation is encoded in EXIF; without this, half your
  photos are sideways.
- **Auth-gated photo serving** (`/properties/photos/file/<path>`).
  Files aren't world-readable.
- **Token-based filenames** (`secrets.token_urlsafe(8) + ".jpg"`).
  Avoids guessable URLs, avoids filename collisions, ignores user
  filename weirdness.
- **Atomic upload pattern**: write file as `.tmp` → add DB row → commit
  → atomic rename. On any failure, rollback DB and unlink temp + final.
  Prevents orphan JPEGs on disk if commit fails.

## Backups

- **APScheduler in-process at 03:00 local** (`services/scheduler.py`).
  Not a separate Redis + worker. One process, one thing to monitor.
- **Backup = `sqlite3.backup()` + tar.gz of (snapshot, photos, CLAUDE.md)
  → optional B2 upload.** `.backup()` is the consistent-snapshot API;
  works while writes are happening. Tarball lets you restore the entire
  app state from one file.
- **Local prune at 7 days; cloud retention via B2 lifecycle policy.**
- **B2 unconfigured ⇒ local-only.** App still works; just no off-site copies.
- **Single Gunicorn worker** in Procfile so the scheduler doesn't run
  jobs 2x.

## Audit log

- **Captured atomically with the change**: `before_flush` snapshots,
  `after_flush` materializes the AuditLog row (now that auto-IDs exist).
- **Both phases run inside the same DB transaction** → audit row commits
  with the change, never out of sync.
- **Listener registration is idempotent.** Called more than once on the
  same session (e.g. test fixtures) is a no-op.
- **`AuditLog` itself isn't tracked** (would recurse infinitely).
- **Tracked models**: Client, Property, Job, Visit, Quote, Invoice,
  LineItem, Payment.
- **Not tracked**: User, Setting (already has updated_at), Conversation,
  Message, Notification, Photo. Photo could be tracked but currently
  isn't — file unlink semantics make audit semantics fuzzy.
- **`PASSIVE_OFF` for history retrieval** so attribute changes on
  expired (post-commit) objects still capture the original value.

## Money

- **Integer cents in DB, `Decimal` for math, `ROUND_HALF_UP` for tax.**
  No floats anywhere. Helpers in `app/services/money.py`.
- **Per-line `taxable` flag** (instead of per-quote) so labor and
  materials can be mixed correctly.
- **Tax math**: sum taxable line totals, multiply by effective rate,
  round to cent. Per-Ohio: each line individually.

## Ohio tax

- **Curated ZIP→county table** (`utils/ohio_tax.py`) covering Cleveland
  metro + major OH cities. NOT exhaustive.
- **Tax rate per Property, not per Client.** Ohio is destination-based.
- **Per-invoice override** in Phase 3 (already wired).
- **Fallback rate = 5.75% (state-only) for unknown ZIPs.** Sane default
  — under-collecting for an unknown county is better than over-collecting.

## Time zones

- **Storage UTC, display local.** `app/utils/timezone.py` exposes
  `today_local()` and `now_local()` reading `APP_TIMEZONE` (default
  America/New_York).
- **Used in:** dashboard "today's jobs", briefing assembly, invoice
  `is_overdue` / `days_overdue`, reminder dedup, A/R aging.
- **Bug class avoided:** `date.today()` returns server-local (UTC on
  Railway) and disagreed with the scheduler's local-TZ "today" by 4–5
  hours around midnight Eastern. The helpers eliminated this.

## Notifications

- **Two delivery channels: in-app inbox (always on) + email (optional)**.
- **Multi-recipient email** via comma-separated `NOTIFY_EMAIL`. Single
  SMTP send delivers to all.
- **SMTP provider-agnostic.** Defaults to Outlook.com personal
  (smtp-mail.outlook.com:587 + STARTTLS). Gmail / M365 / Yahoo all work
  via env-var overrides. Backwards-compat aliases preserve `GMAIL_USER`
  and `GMAIL_APP_PASSWORD` from earlier setups.
- **Per-event toggles** for the Jobber-style triggers
  (quote_request_received, quote_sent, quote_accepted, quote_converted,
  job_complete, invoice_sent, invoice_paid, payment_received).
  Defaults all on.
- **Event helpers called from routes after commit**, NOT subscribed to
  audit log events. Keeps business meaning ("paid") decoupled from
  schema changes ("status went X→Y") — easier to test, easier to read.
- **Reminders bool fix**: was `not get_setting() == "1"` which parses
  as `(not "1") == "1"` → always False; the job-day reminder never
  fired. Fixed with explicit `!=`.

## Public website intake

- **`POST /intake/api/request` is CSRF-exempt** (cross-origin from
  WordPress) but rate-limited (8/hr per IP) and honeypot-protected.
- **CORS locked to `https://lakewoodoriginal.com`.** Other origins get
  blocked at preflight.
- **Honeypot field** named `website` (likely-tempting bait for bots).
- **Service area + categories sourced from `app/utils/service_area.py`**
  — single source of truth, syncs the form dropdown with the WP page.
- **Source tag in Quote.internal_notes**: `Source: website` so the
  Today dashboard's "📩 New website requests" tile can filter for them.

## Jobber integration

- **CSV import path AND API sync path**, both idempotent. CSV is
  easier when Jobber's email exports work. API is fallback when they don't.
- **OAuth tokens encrypted at rest** with Fernet. Key derived via
  HKDF-SHA256 from `SECRET_KEY` with stable salt + "jobber-token-v1"
  info string. Rotating SECRET_KEY invalidates stored tokens.
- **Tokens stored in the existing Setting key-value table** as a single
  encrypted blob (`jobber_oauth_token_encrypted`). Avoids a new schema.
- **Jobber's mandatory `X-JOBBER-GRAPHQL-VERSION` header**: pinned to
  `2025-04-16` (their latest stable as of writing). Bump as Jobber
  publishes new versions in their changelog.
- **Throttle handling**: pre-call sleep (0.35s) caps sustained rate;
  on `THROTTLED` error, exponential backoff (5s/10s/20s/40s/60s, max 8
  retries); honors HTTP 429 `Retry-After` header. 8s cool-down between
  stages in `/sync/all`.
- **Default page_size = 25** for Relay-style queries. Smaller pages =
  fewer points per query on Jobber's rate-limited API.
- **Refresh-token handling**: refreshes 60s before expiry; preserves the
  refresh_token if Jobber doesn't issue a new one.
- **Errors in GraphQL response body raise** (not silently ignored) — a
  weakness in the older lakewood-assistant prototype, fixed here.
- **Per-record errors don't fail the batch.** Each row is wrapped in
  try/except; errors counted in stats and shown in the flash, batch
  continues.
- **Same dedup pattern across all entities**: stamp Jobber ID into
  notes, `WHERE notes LIKE '%[Jobber X #<id>]%'`. See DATA_SCHEMA.md
  for the patterns.
- **Status mapping defined in service code header** (`jobber_sync.py`):
  Jobber's enums → ours. Unknown statuses fall back to a safe default
  with a warning logged.
- **Money from Jobber arrives as floats (dollars).** Converted to
  integer cents via Decimal + ROUND_HALF_UP. Float-free per money.py.

## Deploy

- **Railway with `release: flask db upgrade && python -m scripts.create_admin --only-if-missing`**
  in Procfile. Migrations run before the new container takes traffic.
- **Gunicorn `--workers 1 --threads 4 --timeout 120`.** Threads handle
  concurrent requests cheaply; one worker keeps the scheduler
  singleton-safe; 120s timeout for occasional photo upload bursts.
- **Health check at `/health`** (no auth, returns JSON). Used by
  Railway's health checker + any uptime ping you set up.

## UI / themes / mobile

- **Pico.css via CDN** in `templates/base.html`. Zero build step.
- **HTMX 2.x via CDN** (same file). Used in clients list for live search.
- **Three themes** (`dark` default, `amoled`, `light`) per-user. AMOLED
  layered on top of Pico's "dark" via custom `data-app-theme` attribute
  (Pico itself only knows light/dark — earlier bug fix).
- **Mobile bottom-nav** with a Floating Action Button. 16px form inputs
  prevent iOS zoom-on-focus. 44px tap targets per WCAG. PWA manifest
  for "Add to Home Screen".
- **Single CSS file (`static/css/app.css`)** with theme overrides.
  Compiled? No — it's hand-written CSS. Pico does the heavy lifting.

## Things deliberately NOT done (scope discipline)

- **No customer-facing accept/decline pages yet.** Token URLs work but
  the customer-facing pages come in Phase 3.5.
- **No Stripe integration yet.** Manual mark-paid covers v1; Stripe
  Payment Links in Phase 6 if pain justifies.
- **No recurring jobs (RRULE).** Repeat-job button covers most cases.
- **No SMS reminders.** Use your phone.
- **No customer login portal.** Magic-link tokens cover the use case.
- **No PDF generation library.** HTML invoices + browser print-to-PDF
  for ad-hoc; archive HTML snapshots for durable record. Avoids
  pycairo / WeasyPrint native deps.
- **No CSRF on `/intake/api/request` and `/jobber/callback`.** Both are
  cross-origin; rate-limit + honeypot (intake) and OAuth state
  (jobber callback) provide the protection instead.
- **No soft-delete `deleted_at` columns.** Audit log captures full
  delete snapshots; recovery is possible from there.

## Things I'd want a second pair of eyes on

- The `ohio_tax.py` ZIP→county table is curated, not exhaustive. Update
  it annually as Ohio Dept of Taxation publishes new rates.
- The `--workers 1` Gunicorn config means slow requests block each
  other modulo threading. For one-user traffic this is fine, but if you
  ever scale, scheduler needs a leader-election pattern.
- The Jobber GraphQL schema changes occasionally; if Jobber bumps
  their API version and renames fields again, the sync queries need
  matching updates.
- The intake CORS list is hardcoded to `lakewoodoriginal.com`. If you
  ever add a staging or alt domain, make it a config value.
