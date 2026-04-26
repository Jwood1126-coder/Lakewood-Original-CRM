# Decisions Made (Phase 0 + Phase 1)

Every non-trivial default chosen during the autonomous build session, with
the reasoning. If you disagree with any of these, here's where to push back.

---

## Project layout

- **App-factory pattern** (`create_app()` in `app/__init__.py`).
  Why: required for clean tests + Alembic + multiple worker processes.
- **Per-feature blueprints** (`auth/`, `clients/`, `properties/`, `main/`).
  Why: each feature folder has its own routes + forms + (later) services,
  keeps view files small, and means Phase 2's `jobs/` blueprint slots in
  alongside without touching the others.
- **`services/` directory for domain logic** (photos, backups, scheduler).
  Why: keeps views thin; views call services, services don't know about HTTP.

## Stack choices

- **Pico.css via CDN** (`templates/base.html`).
  Why: zero build step, looks decent out of the box. The `static/css/README.md`
  documents how to vendor it for production durability.
- **HTMX 2.x via CDN** (same file).
  Why: matches Pico's "no build step" ethos. Used in clients list for
  live search.
- **No tailwind, no React, no JS build pipeline.**
  Why: the design philosophy was "simple is elegant" — every dependency earns its slot.

## Database

- **SQLite with WAL + foreign-keys-on pragmas** (`extensions.py`).
  WAL = better concurrent read perf, FK enforcement = catches accidental
  orphans early.
- **`render_as_batch=True` in Alembic env.py.**
  SQLite can't `ALTER TABLE` directly; batch mode does the
  copy-table-recreate dance automatically.
- **Initial migration written by hand** (`migrations/versions/0001_initial_schema.py`)
  rather than `flask db migrate --autogenerate`.
  Why: I can't run Python in this sandbox; the manual file is what
  autogenerate would have produced. Future schema changes should use
  autogenerate.
- **No SQLAlchemy 1.x patterns.**
  All models use 2.x typed `Mapped[...]` columns and `select(...)` queries.

## Models

- **`User` v1 = single operator.**
  No role column. When/if a crew member is added, add a `role` field via
  Alembic migration. Don't over-engineer now.
- **`Client` has display_phone helper** for `(xxx) xxx-xxxx` rendering.
  Storage is digits-only (see `utils/phone.py`) — separation of storage
  vs. presentation.
- **`Property` carries `tax_rate` as Numeric(6,4).**
  Decimal storage avoids float math errors in Phase 3 invoicing. Stored as
  the rate (0.08), not percent (8.00) — matches how SQL math will treat it.
- **`Photo` uses nullable-FK polymorphism** (currently only property_id;
  visit/quote/invoice FKs added in their phases).
  Why: simpler than SQLAlchemy polymorphic_identity, indexes are obvious,
  fine at <100k photos. CHECK constraint guarantees ≥1 parent.

## Auth

- **Argon2id for password hashing** (`argon2-cffi`).
  Modern recommended choice; bcrypt is older. Auto-rehash on verify if
  argon2 params have been upgraded.
- **Sessions, not JWT.**
  Single user, single browser, no SPA — sessions are the right call.
- **`session_protection = "strong"`** (Flask-Login).
  Invalidates session on IP/user-agent change. Slight inconvenience worth
  the safety.
- **Open-redirect guard on `?next=` parameter** (auth/routes.py `_is_safe_url`).
  Blocks `/auth/login?next=https://evil.com` attacks.
- **No password reset flow.**
  By design — see Chunk 4. If you forget, run `python -m scripts.create_admin --password new`.

## Photos

- **Resize to 1600px long-edge, JPEG quality 85.**
  Phone photos are 3-5MB; resized they're ~250-500KB. 5-10× storage
  savings, still fine for documentation. The original is NOT kept.
- **EXIF auto-rotation** (`ImageOps.exif_transpose`).
  Phone landscape/portrait orientation is encoded in EXIF; without this,
  half your photos are sideways.
- **Auth-gated photo serving** (`/properties/photos/file/<path>`).
  Files aren't world-readable. Means slower static serving, but correct
  default for a CRM.
- **Token-based filenames** (`secrets.token_urlsafe(8) + ".jpg"`).
  Avoids guessable URLs, avoids filename collisions, ignores user filename
  weirdness (Unicode, slashes, etc.).

## Backups

- **APScheduler in-process at 03:00 local** (`services/scheduler.py`).
  Not a separate Redis + worker. One process, one thing to monitor.
- **Backup = `sqlite3 .backup` + tar.gz of (snapshot, photos, CLAUDE.md) → optional B2 upload.**
  `.backup()` is the consistent-snapshot API; works while writes are
  happening. Tarball lets you restore the entire app state from one file.
- **Local prune at 7 days; cloud retention via B2 lifecycle policy.**
  Don't accumulate 6 months of tarballs on the small Railway volume.
- **B2 unconfigured ⇒ local-only.**
  App still works without B2 creds. Backups happen; they're just not
  off-site. You'll see a log line "B2 not configured; backup stays local only".
- **Single Gunicorn worker** in Procfile so the scheduler doesn't run jobs 2x.
  Trade-off: one user, no parallelism needed; if you ever scale, switch to
  a leader-election scheme or a separate scheduler process.

## Ohio tax

- **Curated ZIP→county table** (`utils/ohio_tax.py`) covering Cleveland
  metro + major OH cities. NOT exhaustive.
  When a customer comes from a new county, add the ZIP. Update annually.
- **Tax rate per Property, not per Client.**
  Ohio is destination-based; the rate depends on where the work happens,
  not who's paying.
- **Per-invoice override coming in Phase 3.**
  The Property's rate is the default; invoices can override.
- **Fallback rate = 5.75% (state-only) for unknown ZIPs.**
  Sane default — under-collecting for an unknown county is better than
  over-collecting and getting a complaint.

## Scheduler

- **`APP_TIMEZONE = America/New_York`** (env-overridable).
  All cron times are local; storage stays UTC.
- **`coalesce=True, max_instances=1`** on every job.
  If the app was down at 3am and comes back at 4am, run the missed
  backup once (not five times). And never run two backups concurrently.

## Deploy

- **Railway with `release: flask db upgrade`** (Procfile).
  Migrations run before the new container takes traffic. Critical: if a
  migration fails, deploy fails, app keeps running on old version.
- **Gunicorn `--workers 1 --threads 4 --timeout 120`.**
  Threads handle concurrent requests cheaply; one worker keeps the
  scheduler singleton-safe; 120s timeout is for occasional photo upload bursts.
- **Health check at `/health`** (no auth, returns JSON).
  Used by Railway's health checker + any uptime ping you set up later.

## Things I deliberately did NOT do

- **No Postgres adapter, no S3-FUSE photo storage, no Redis.**
  Out of scope at this scale.
- **No frontend build step.** No `package.json`, no `npm`, no Tailwind.
- **No customer-facing pages yet.** Those come in Phase 3 (token URLs).
- **No PDF generation yet.** Phase 3.
- **No CSRF on the photo file-serve route.** It's GET-only; CSRF doesn't apply.
- **No rate limiting yet.** With one user, no public actions yet, no
  webhooks — there's nothing to rate-limit.
- **Logo file is not in the repo.** You'll add it later; the Phase 3
  invoice template will check for it and degrade to text-only.
- **No analytics, no Sentry.** Skipped for v1 per the design philosophy.

## Things I'd want a second pair of eyes on

- The `ohio_tax.py` ZIP→county table is incomplete. Want a quick eye on
  whether the rates I have are current (used Ohio DoT rates as of late 2024).
- The `--workers 1` Gunicorn config means slow requests block each other
  modulo threading. For Phase 1's traffic profile (you, two requests/min)
  this is genuinely fine, but I want to flag it.
- I left `ADMIN_PASSWORD` blank in `.env.example`. If you set it before
  first run, the create-admin script uses it. If you don't, the script
  generates one and prints it. Either is fine; the script being run is
  the part that matters.
