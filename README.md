# Lakewood Original CRM

A self-hosted, mobile-first field-service CRM for [Lakewood Original](https://lakewoodoriginal.com)
— a solo handyman business in Cleveland, OH. Replaces Jobber for the
day-to-day workflow at a fraction of the cost, with a built-in Claude
assistant, automated daily-briefing pipeline, full audit log, public
"request a quote" intake from the website, and a one-shot Jobber
migration tool (CSV importer + GraphQL API sync).

[![tests](https://img.shields.io/badge/tests-50%20passing-brightgreen)]()
[![python](https://img.shields.io/badge/python-3.12-blue)]()
[![flask](https://img.shields.io/badge/flask-3.0-blue)]()
[![sqlalchemy](https://img.shields.io/badge/sqlalchemy-2.0-blue)]()
[![htmx](https://img.shields.io/badge/htmx-2.0-purple)]()
[![claude](https://img.shields.io/badge/claude-opus--4.7-orange)]()

> **Design philosophy:** simple is elegant. Every dependency earns its slot.
> The whole production system is one Python process, one SQLite file, and a
> photos folder. If everything else is on fire you can restore from a
> 200KB tarball.

---

## Documentation

| File | Audience | What's in it |
|---|---|---|
| **README.md** (this file) | Anyone | Overview, quick start, deploy, project layout |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Operator / non-developer | How the pieces fit, why each tool was chosen |
| [DATA_SCHEMA.md](DATA_SCHEMA.md) | Operator / non-developer | Every table in plain English |
| [DECISIONS.md](DECISIONS.md) | Developer | Every non-trivial default with the reasoning |
| [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md) | Operator | Env vars + decisions still pending |
| [RESTORE.md](RESTORE.md) | Operator | Disaster-recovery playbook |
| [JOBBER_INTEGRATION.md](JOBBER_INTEGRATION.md) | Developer | Jobber OAuth + GraphQL sync deep-dive |
| [WEBSITE_INTAKE_SNIPPET.md](WEBSITE_INTAKE_SNIPPET.md) | Operator | HTML to paste into the WordPress site |

---

## Capabilities

### Core CRM
- Client + property database with photo upload (Pillow resize, EXIF auto-rotate)
- Job scheduling with status state machine, multi-visit on-site time tracking
- Calendar — month / week / day views with switcher
- Quotes with line items + Ohio destination-based tax (per-property rate)
- Invoices with multi-payment ledger, auto status recompute, can't-delete-with-payments guard
- Quote → Job conversion, Job → Invoice creation
- Customer profile: jobs + quotes + invoices + balance owed in one view

### Dashboard "needs attention" pipeline
- 📩 New website requests
- ⚠ Overdue invoices
- 🟡 Jobs ready to invoice
- ✓ Quotes accepted but not scheduled
- ⚠ Overdue jobs
- A/R outstanding total in the stat strip

### Reports (CSV-exportable)
- **Sales tax** — by month, per-invoice detail, accrual basis, drives Ohio filing
- **Revenue** — cash basis (payments received) + accrual basis (invoices billed) side by side
- **A/R aging** — current / 1-30 / 31-60 / 61-90 / 90+ buckets, per-client breakdown
- **Year-end packet** — quick-links bundle for handing to a CPA + IRS retention reminder

### Claude assistant
- Chat at `/assistant` with read-only tool use against your data
- Editable system prompt (`/data/CLAUDE.md`) persisted on the volume
- Daily briefing automatically generated at configurable time, narrative paragraph from Claude

### Notifications (Jobber-style event triggers)
- 📩 Website request received
- Quote sent / accepted / converted
- Job marked complete
- Invoice sent / paid
- Payment received
- Each toggleable per-event in Settings → Notifications
- Two channels: in-app inbox (always) + email (if SMTP configured)
- Multi-recipient (`NOTIFY_EMAIL=jake@gmail.com, jake@outlook.com`)
- SMTP provider-agnostic — defaults to Outlook.com personal; Gmail / M365 / Yahoo all work via env vars

### Public website intake
- `POST /intake/api/request` JSON endpoint takes a customer's request and creates a draft Quote
- Honeypot + per-IP rate limit + CORS locked to production domain
- Self-hosted form at `/intake/request` for fallback / direct sharing
- See [WEBSITE_INTAKE_SNIPPET.md](WEBSITE_INTAKE_SNIPPET.md) for the WordPress copy-paste

### Jobber migration (one-time)
- **CSV importer** at Settings → Import Jobber clients
  - Groups CSV rows by Jobber client_id (multi-property rows collapse to one client)
  - Auto-fills Ohio county + tax rate from each property's ZIP
  - Skip-list field for known dupes / test entries
  - Idempotent re-runs (Jobber ID stamped in client notes)
- **API sync** at Settings → Jobber sync (when CSV exports aren't arriving)
  - OAuth 2.0 flow, encrypted token storage
  - Pages through clients, jobs, quotes, invoices, payments
  - Throttle handling with exponential backoff
  - Same dedup as the CSV importer
  - Single "🚀 Pull EVERYTHING" button runs all syncs in dependency order

### Backups + audit
- Nightly tarball at 03:00 local: SQLite snapshot + photos + CLAUDE.md → optional Backblaze B2
- Manual on-demand backup with download links
- Automatic audit log of every change to client/property/job/visit/quote/invoice/line-item/payment — captured atomically in the same DB transaction as the change
- Audit viewer at Settings → Audit log, filterable by entity type, ID, operation

### Security + ops
- Argon2id password hashing
- Login rate limiting (8/min, 30/hr per IP) via Flask-Limiter
- Global CSRF protection (Flask-WTF)
- ProxyFix middleware (trusts Railway's `X-Forwarded-Proto` for correct `https://` URLs)
- All money: integer cents in DB, Decimal arithmetic with ROUND_HALF_UP for tax
- Time zones: UTC stored, operator-local rendered (`app/utils/timezone.py`)

### UI
- Dark mode by default; AMOLED true-black + Light alternates (per-user)
- Mobile bottom-nav (Today / Calendar / [Assistant FAB] / Clients / More)
- iPhone PWA "Add to Home Screen"
- Tables collapse to cards on narrow screens
- 16px form inputs (no iOS zoom-on-focus); 44px tap targets

### Currently deferred
- Customer-facing accept/decline pages via token URLs (Phase 3.5)
- Stripe Payment Links (Phase 6 — manual mark-paid covers v1)
- Recurring jobs engine (the "Repeat last job" button covers most cases)
- Photo upload on intake form
- Cloudflare Turnstile on intake form

---

## Tech stack at a glance

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Operator's existing stack |
| Web framework | Flask 3.0 | Minimal, app-factory pattern, blueprints |
| ORM | SQLAlchemy 2.0 (Mapped types) | Industry standard; modern typed API |
| Migrations | Alembic via Flask-Migrate | Versioned schema; `render_as_batch=True` for SQLite ALTER |
| Database | SQLite (WAL, foreign_keys=ON) | One file; backup = `cp`; sufficient for one writer |
| Templating | Jinja2 (Flask default) | — |
| Interactivity | HTMX 2.0 | Server returns HTML fragments; no JSON API, no React |
| CSS | Pico.css 2.0 + ~800 lines of overrides | Classless baseline; zero build step |
| Auth (operator) | Flask-Login + Argon2id (`argon2-cffi`) | Modern recommended hash; cookie sessions |
| Auth (customer) | Unguessable URL tokens (`secrets.token_urlsafe(24)`) | Magic-link UX; no customer accounts |
| Forms / CSRF | Flask-WTF (global CSRFProtect) | Auto-applied to all POST/PUT/DELETE |
| Rate limiting | Flask-Limiter (memory backend) | Login throttle: 8/min, 30/hr per IP |
| Reverse-proxy fix | werkzeug ProxyFix | Trusts Railway edge `X-Forwarded-*` headers |
| Scheduling | APScheduler 3.10 (BackgroundScheduler) | In-process cron; no Redis |
| Email | `smtplib` over Outlook/Gmail/M365/Yahoo | Free, perfect deliverability for self-notifications |
| Encryption | `cryptography` (Fernet, HKDF-SHA256) | Encrypts Jobber OAuth tokens at rest |
| HTTP client | `requests` | For Jobber API calls |
| AI | `anthropic` SDK 0.45+ (Opus 4.7 default) | Tool use + prompt caching |
| Money | Integer cents in DB, `Decimal` with `ROUND_HALF_UP` | Float-free (`app/services/money.py`) |
| Audit | SQLAlchemy session events (`before_flush` + `after_flush`) | Atomic with the change |
| PDF | HTML-first, browser print | No native deps |
| Backups | `sqlite3.backup()` + `tar.gz` → Backblaze B2 (S3 API) | Consistent snapshot; off-site optional |
| Hosting | Railway (Hobby plan, 1GB volume) | One container + persistent volume; `git push` deploy |

[Full reasoning per layer in ARCHITECTURE.md.](ARCHITECTURE.md)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (HTMX)        WordPress site → /intake/api/request │
└─────────────────────────────────────┬───────────────────────┘
                                      │ HTTPS
┌─────────────────────────────────────▼───────────────────────┐
│  Railway edge (TLS termination, *.up.railway.app)           │
│  → ProxyFix middleware honors X-Forwarded-Proto/Host        │
└─────────────────────────────────────┬───────────────────────┘
                                      │
┌─────────────────────────────────────▼───────────────────────┐
│  Gunicorn 23 (1 worker, 4 threads, 120s timeout)            │
│   ├─ Flask 3.0 application factory                          │
│   ├─ Flask-Login (Argon2id sessions, 30d remember)          │
│   ├─ Flask-WTF (global CSRF)                                │
│   ├─ Flask-Limiter (login rate limit; opt-in per route)     │
│   ├─ SQLAlchemy 2.0 + audit listeners                       │
│   ├─ Alembic migrations (auto-applied on deploy release)    │
│   ├─ APScheduler (03:00 backup; 06:30 daily briefing;       │
│   │   hourly reminder tick)                                 │
│   ├─ Anthropic SDK (chat + briefing narrative)              │
│   └─ Jobber API client (OAuth + GraphQL, throttle retry)    │
└──────┬──────────────────┬──────────────────┬───────────────┘
       │                  │                  │
       ▼                  ▼                  ▼
┌──────────────┐   ┌────────────────┐   ┌─────────────────┐
│ SQLite (WAL) │   │ Anthropic API  │   │ SMTP            │
│ /data/app.db │   │ Claude Opus 4.7│   │ (Outlook/Gmail/ │
│ + /photos    │   └────────────────┘   │  M365/etc.)     │
│ + /backups   │                        └─────────────────┘
│ + /CLAUDE.md │   ┌────────────────┐   ┌─────────────────┐
│              │──▶│ Backblaze B2   │   │ Jobber GraphQL  │
│  on Railway  │   │ (off-site bkp) │   │ api.getjobber   │
│   volume     │   └────────────────┘   │ .com/api/graphql│
└──────────────┘                        └─────────────────┘
```

---

## Quick start (local development)

```bash
# 1. Create venv and install
python -m venv .venv
.venv\Scripts\activate                  # Windows
# source .venv/bin/activate              # macOS/Linux
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env: at minimum set SECRET_KEY (any 48+ char random string)

# 3. Apply migrations to a fresh SQLite DB
flask db upgrade

# 4. Create the admin user (idempotent)
python -m scripts.create_admin --only-if-missing

# 5. Run the dev server
flask run

# Open http://127.0.0.1:5000
```

Common dev commands:

```bash
pytest                                   # 50-test suite
flask db migrate -m "describe change"    # generate migration after model change
flask db upgrade                         # apply pending migrations
flask db downgrade -1                    # roll back one migration
python -m scripts.run_backup             # trigger a backup manually
python -m scripts.import_jobber_clients <csv> [--commit] [--skip-jobber-ids "id1,id2"]
```

---

## Deploy to Railway

The repo ships with `railway.json`, `Procfile`, and `runtime.txt`.

1. Push to GitHub.
2. Railway → **New Project → Deploy from GitHub repo**.
3. Service → **Volumes** → mount 1GB at `/data`.
4. Service → **Variables** → Raw Editor → paste:

```
# REQUIRED
SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_urlsafe(48))">
DATABASE_URL=sqlite:////data/app.db
PHOTO_DIR=/data/photos
ARCHIVE_DIR=/data/archive
BACKUP_DIR=/data/backups
ADMIN_EMAIL=you@example.com
ADMIN_PASSWORD=<strong password>

# BUSINESS
BUSINESS_NAME=Lakewood Original
BUSINESS_ADDRESS=<your address>
BUSINESS_PHONE=(216) 770-7034
BUSINESS_EMAIL=Jakewood@lakewoodoriginal.com
DEFAULT_COUNTY=Cuyahoga
APP_TIMEZONE=America/New_York

# CLAUDE ASSISTANT
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-4-7        # default; sonnet-4-6 cheaper

# EMAIL (notifications-to-self only — never customers)
# Defaults: Outlook.com personal (smtp-mail.outlook.com:587 + STARTTLS)
SMTP_USER=jake@outlook.com
SMTP_PASSWORD=<App Password>
NOTIFY_EMAIL=jake@gmail.com, jake@outlook.com   # comma-sep multi-recipient
# For Gmail SMTP: SMTP_HOST=smtp.gmail.com SMTP_PORT=465 SMTP_USE_TLS=0
# For M365 work: SMTP_HOST=smtp.office365.com (admin must enable SMTP AUTH)

# OFF-SITE BACKUPS (optional)
B2_ENDPOINT_URL=https://s3.us-east-005.backblazeb2.com
B2_KEY_ID=
B2_APPLICATION_KEY=
B2_BUCKET=lakewood-crm-backups

# JOBBER MIGRATION (one-time use)
JOBBER_CLIENT_ID=<from developer.getjobber.com>
JOBBER_CLIENT_SECRET=<from developer.getjobber.com>
# JOBBER_REDIRECT_URI=  # optional; auto-derived from request URL
# JOBBER_GRAPHQL_VERSION=2025-04-16  # default; bump as Jobber publishes
```

5. Push to `main` → Railway auto-deploys. The `release` step in `Procfile` runs:
   `flask db upgrade && python -m scripts.create_admin --only-if-missing`
6. **Settings → Networking → Generate Domain** for a `*.up.railway.app` URL.

The four-slash `////` in `DATABASE_URL` is intentional — it's an absolute SQLite path.

---

## Project structure

```
app/
  __init__.py             # Flask application factory + ProxyFix wiring
  config.py               # All env-driven config + path resolution
  extensions.py           # SQLAlchemy, Login, Migrate, CSRF, Limiter

  models/                 # SQLAlchemy ORM (Mapped[] typed columns)
    audit_log.py          #   Append-only change history
    client.py             #   Customer + computed balance_owed
    conversation.py       #   Assistant chat history
    invoice.py            #   State machine + paid_cents query + recompute_status
    job.py                #   State machine; relationships to invoices, source_quotes
    line_item.py          #   Polymorphic via two nullable FKs (CHECK constraint)
    notification.py       #   Inbox content
    payment.py            #   Per-invoice ledger
    photo.py              #   Polymorphic over Property/Job/Visit
    property.py           #   Address + Ohio tax_rate (auto-resolved from ZIP)
    quote.py              #   State machine + Quote→Job conversion link
    setting.py            #   Singleton key-value store
    user.py               #   Operator login (Argon2id)
    visit.py              #   arrived_at/departed_at, computed duration

  auth/      clients/      jobs/        quotes/      invoices/
  reports/   properties/   assistant/   settings/    main/
  intake/    jobber/
                          # Each is a Blueprint folder with routes.py + forms.py.
                          # Templates live under app/templates/<blueprint>/.

  services/               # Domain logic — keep views thin
    assistant.py          #   Anthropic tool-use loop; CLAUDE.md persistence
    audit.py              #   before_flush + after_flush listeners
    backup.py             #   sqlite3.backup() → tar.gz → optional B2
    briefing.py           #   Daily briefing assembly + Claude narrative + email
    email.py              #   Generic SMTP (Outlook/Gmail/M365/Yahoo)
    events.py             #   Jobber-style event notifications (quote sent, etc.)
    jobber.py             #   Jobber OAuth + GraphQL client + throttle retry
    jobber_sync.py        #   Pull jobs/quotes/invoices/payments via API
    money.py              #   Cents/Decimal — float-free
    photos.py             #   Pillow resize + EXIF rotate + auth-gated serve
    reminders.py          #   Hourly tick — emits Notifications
    scheduler.py          #   APScheduler bootstrap + reschedule_recurring_jobs

  templates/              # Jinja templates organized by blueprint
  static/                 # CSS, manifest.json
  utils/                  # Pure stateless helpers
    crypto.py             #   Fernet + HKDF for OAuth token at-rest encryption
    ohio_tax.py           #   ZIP → county → tax-rate lookup table
    phone.py              #   US-only digit normalization
    service_area.py       #   Lakewood Original services + service area cities
    timezone.py           #   today_local() / now_local() — operator-local TZ

migrations/               # Alembic versions (0001 → 0006)
scripts/                  # CLI entry points
  create_admin.py         #   Idempotent admin bootstrap (run on every deploy)
  run_backup.py           #   Manual backup trigger
  import_jobber_clients.py#   Jobber CSV → DB importer (also reused by API sync)
tests/                    # pytest (50 tests)
data/                     # Runtime — NOT in git (contents gitignored;
                          #   directory structure preserved via .gitkeep)
wsgi.py                   # Gunicorn entry point
Procfile, railway.json    # Deploy config
runtime.txt               # Python version pin for Railway nixpacks
```

---

## Key implementation details

### Atomic writes
Every Flask route call commits its changes once at the end of request
handling. SQLAlchemy auto-rolls-back on any exception. Multi-step operations
(e.g. creating a Quote with line items) `flush()` mid-request to obtain
auto-incremented IDs but `commit()` only at the end.

### Audit log (event-sourced)
SQLAlchemy session events capture every change to tracked models
(`Client`, `Property`, `Job`, `Visit`, `Quote`, `Invoice`, `LineItem`,
`Payment`):

- `before_flush`: snapshot the changes (using `attributes.get_history(...,
  passive=PASSIVE_OFF)` to force-load original values for expired attributes).
- `after_flush`: materialize `AuditLog` rows now that auto-incremented
  IDs are known.

Both phases run inside the same DB transaction → audit row commits
atomically with the change. `AuditLog` itself isn't tracked.
Listener registration is idempotent. Code:
[`app/services/audit.py`](app/services/audit.py).

### Money math
Stored as `Integer` cents in the DB. Computed in Python with `Decimal`
+ `ROUND_HALF_UP` for tax. Conversion utilities in
[`app/services/money.py`](app/services/money.py). Per-invoice total
includes a per-line `taxable` flag so labor and materials can be mixed:

```python
taxable_subtotal_cents = sum(li.line_total_cents for li in lines if li.taxable)
tax_cents = round_half_up(taxable_subtotal_cents * effective_tax_rate)
total_cents = subtotal_cents + tax_cents
```

`Invoice.paid_cents` is a query-backed property (not a relationship-sum)
so a freshly-added Payment in the same transaction is included even if
the relationship cache hasn't refreshed. `Invoice.paid_cents_bulk(ids)`
provides a single GROUP-BY SUM lookup for many invoices at once
(used in dashboard + A/R aging to avoid N+1).

### Ohio destination-based sales tax
`tax_rate` lives on `Property`, auto-resolved from ZIP via a curated
`ZIP_TO_COUNTY` table in [`app/utils/ohio_tax.py`](app/utils/ohio_tax.py).
Per-invoice `tax_rate_override` falls back to property's rate when null.
Cleveland metro + major OH cities seeded; expand annually as Ohio
Department of Taxation publishes new rates.

### State machines
`Job`, `Quote`, `Invoice` each have explicit transition tables. All have
guarded `can_transition_to()` / `transition_to()` methods (invalid
transitions raise / show flash error in the route). Invoice can't be
deleted if it has any payments — must be marked Void instead.

### Customer connectivity
Strong reverse relationships: `Client.jobs`, `Client.quotes`,
`Client.invoices`, `Client.balance_owed_cents` (computed property,
sums open-invoice balances). `Job` has back-populates to `client` and
`prop`, plus relationships to `invoices` and `source_quotes`.

### Event notifications (Jobber-style)
`app/services/events.py` exposes per-event helpers (`notify_quote_sent`,
`notify_invoice_paid`, etc.) called from routes after each meaningful
action commits. Each helper:
1. Checks the per-event toggle in Settings
2. Inserts a `Notification` row (in-app inbox)
3. If the email channel is on AND SMTP is configured, sends an email
   to all recipients in `NOTIFY_EMAIL` (comma-separated)

Pattern is intentionally explicit (route handlers call helpers directly)
rather than subscribing to audit_log events — keeps business meaning
("paid") decoupled from incidental schema changes ("status column went X→Y").

### Public website intake
`POST /intake/api/request` accepts a customer's request from the
WordPress site. Creates Client (matched if existing) + Property
(auto OH tax) + Quote in `draft` status. Spam mitigation: per-IP rate
limit, honeypot field, CSRF exempted (cross-origin), CORS locked to
`https://lakewoodoriginal.com`. New requests appear in a "📩 New website
requests" tile on the Today dashboard. See
[WEBSITE_INTAKE_SNIPPET.md](WEBSITE_INTAKE_SNIPPET.md) for the
WordPress copy-paste.

### Jobber migration
Two paths, both idempotent:

1. **CSV importer** (`Settings → Import Jobber clients`) — for the data
   Jobber's UI export emails reliably (Clients).
2. **API sync** (`Settings → Jobber sync`) — for everything else.
   OAuth flow → encrypted token storage (Fernet, key derived via HKDF
   from SECRET_KEY) → paged GraphQL queries through clients, jobs,
   quotes, invoices, payments. Throttle retries with exponential backoff.

Both use the same dedup pattern: each Jobber entity ID is stamped into
the imported row's notes (`[Jobber job #abc123]`), so re-runs skip
already-imported records. Detailed flow in
[JOBBER_INTEGRATION.md](JOBBER_INTEGRATION.md).

### Security
- Global `CSRFProtect` from Flask-WTF, auto-applied to all state-changing
  HTTP methods. `/intake/api/request` and `/jobber/callback` are explicitly
  exempted (cross-origin / external redirect).
- Jinja autoescape on. The single `|safe` use is on `Notification.body_html`,
  which is server-generated using `html.escape()` on every user-derived string.
- `?next=` parameter on login validated via `_is_safe_url()` to block
  open redirects.
- Argon2id password hashing (`argon2-cffi`) with auto-rehash on parameter
  upgrade.
- Login rate limit: 8/min, 30/hr per IP via Flask-Limiter (in-memory).
- Photos served behind `@login_required`; filenames are
  `secrets.token_urlsafe(8)` to prevent enumeration.
- Jobber OAuth tokens encrypted at rest (Fernet, HKDF-SHA256 from `SECRET_KEY`).

### Backup strategy
1. **Railway volume** — replicated within Railway infra (fast restore).
2. **Nightly tarball at 03:00 local time** (APScheduler):
   `sqlite3.backup()` → `tar.gz(snapshot, photos, CLAUDE.md)` → optional B2
   upload. Local prune at 7 days.
3. **Manual on-demand** via Settings → Backups (downloadable).
4. **Quarterly local pull** (operator discipline) — download to USB.

Restore documented in [RESTORE.md](RESTORE.md).

### Mobile-first UI
- Bottom navigation on phones (`@media max-width: 720px`); top nav on
  tablet/desktop. Floating action button center-bottom.
- Tables collapse to cards via `.table-cards` modifier on narrow screens.
- 16px form inputs (prevents iOS zoom-on-focus).
- 44px minimum tap targets (WCAG-recommended).
- `safe-area-inset` for iPhone notch/home-indicator.
- PWA manifest for "Add to Home Screen".

### Themes
Three themes (`dark` default, `amoled`, `light`) per-user (`User.theme`).
Pico.css recognizes `data-theme="dark"|"light"`; AMOLED layers on top
of the dark baseline via a custom `data-app-theme="amoled"` attribute
selector for true-black `#000000`.

### Time zones
All timestamps stored as UTC. `app/utils/timezone.py` provides
`today_local()` and `now_local()` that read `APP_TIMEZONE` config
(default `America/New_York`). Used everywhere "today" matters:
dashboard tiles, invoice overdue check, A/R aging, daily-briefing
assembly, reminder dedup. Avoids the bug class where the operator's
"today" disagrees with the server's `date.today()` around midnight.

---

## Migration history

| Revision | What |
|---|---|
| 0001_initial_schema | users, clients, properties, photos |
| 0002_jobs_visits_photo_fks | jobs, visits; photos can attach to jobs/visits |
| 0003_user_theme_and_settings | user.theme; settings key-value table |
| 0004_assistant_and_notifications | conversations, messages, notifications |
| 0005_quotes_invoices_payments | quotes, invoices, line_items, payments |
| 0006_audit_log_and_soft_delete | audit_log table |

All migrations use `render_as_batch=True` so SQLite `ALTER TABLE`
copy-table-recreate works. Apply with `flask db upgrade`.

---

## Live URL map (post-deploy)

| Route | Purpose |
|---|---|
| `GET /` | Today dashboard with pipeline tiles |
| `GET /jobs/calendar?view=month\|week\|day` | Calendar |
| `GET /jobs`, `/quotes`, `/invoices` | Lists with status filter |
| `POST /jobs/<id>/visits/start` / `…/end` | One-tap field action |
| `POST /jobs/<id>/status/<new>` | Status transition |
| `POST /quotes/<id>/convert-to-job` | Lifecycle conversion |
| `POST /invoices/<id>/payments` | Record a payment (recomputes status) |
| `GET /clients/<id>` | Customer profile (jobs + quotes + invoices + balance) |
| `GET /assistant` / `POST /assistant/c/<id>/send` | Claude chat |
| `GET /reports/sales-tax`, `/revenue`, `/ar-aging`, `/year-end` | Accounting reports (CSV-exportable) |
| `GET /inbox` | Notifications |
| `GET/POST /intake/request` | Public quote-request form (browser) |
| `POST /intake/api/request` | Public quote-request JSON API (for WordPress) |
| `GET /jobber` | Jobber sync status / Connect / Pull buttons |
| `POST /jobber/sync/all` | Pull clients + jobs + quotes + invoices + payments |
| `GET /settings/audit?entity_type=…&entity_id=…&operation=…` | Audit log viewer |
| `GET /health` | Liveness check (no auth) |

---

## License

Private business software for Lakewood Original. Not open-source.
