# Lakewood Original CRM

A self-hosted, mobile-first field-service CRM for a single-operator handyman
business. Replaces Jobber for the day-to-day workflow at a fraction of the
cost, with a built-in Claude assistant, automated daily-briefing pipeline,
and a full audit log of every data change.

[![tests](https://img.shields.io/badge/tests-40%20passing-brightgreen)]()
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

---

## Capabilities

| Feature | Status |
|---|---|
| Client + property CRM with photos | ✅ |
| Job scheduling, status state machine, multi-visit tracking | ✅ |
| Calendar (month / week / day) with view switcher | ✅ |
| Quotes with line items + Ohio destination-based tax | ✅ |
| Invoices with multi-payment ledger, auto status recompute | ✅ |
| Quote → Job conversion, Job → Invoice creation | ✅ |
| Customer profile: jobs + quotes + invoices + balance owed in one view | ✅ |
| Today dashboard with "needs attention" pipeline tiles | ✅ |
| Reports: sales tax, revenue (cash + accrual), A/R aging, year-end packet — all CSV-exportable | ✅ |
| Claude assistant (chat, tool-use, editable system prompt at `/data/CLAUDE.md`) | ✅ |
| Daily briefings via Claude + Gmail SMTP email | ✅ |
| In-app notification inbox with unread badge | ✅ |
| Automatic audit log of every data change (atomic with the change) | ✅ |
| Nightly backups (local + Backblaze B2 S3-compatible upload) | ✅ |
| Manual on-demand backup with download | ✅ |
| Themes (Dark / AMOLED / Light), per-user | ✅ |
| Mobile-first PWA with bottom-nav, iPhone "Add to Home Screen" | ✅ |
| Login rate limiting (8/min, 30/hr per IP) | ✅ |
| Customer-facing accept/decline pages via token URLs | ⏳ Phase 3.5 |
| Stripe Payment Links | ⏳ Phase 6 |

40 tests passing.

---

## Tech stack at a glance

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Operator's existing stack; mature ecosystem |
| Web framework | Flask 3.0 | Minimal, app-factory pattern, blueprints |
| ORM | SQLAlchemy 2.0 (Mapped types) | Industry standard; modern typed API |
| Migrations | Alembic via Flask-Migrate | Versioned schema; `render_as_batch=True` for SQLite ALTER |
| Database | SQLite (WAL, foreign_keys=ON) | One file; backup = `cp`; sufficient for one writer |
| Templating | Jinja2 (Flask default) | — |
| Interactivity | HTMX 2.0 | Server returns HTML fragments; no JSON API, no React |
| CSS | Pico.css 2.0 + ~800 lines of overrides | Classless baseline; zero build step |
| Auth (operator) | Flask-Login + Argon2id (`argon2-cffi`) | Modern recommended hash; cookie sessions |
| Auth (customer) | Unguessable URL tokens (`secrets.token_urlsafe(24)`) | No customer accounts; magic-link UX |
| Forms / CSRF | Flask-WTF (global CSRFProtect) | Auto-applied to all POST/PUT/DELETE |
| Rate limiting | Flask-Limiter (memory backend) | Login throttle: 8/min, 30/hr per IP |
| Scheduling | APScheduler 3.10 (BackgroundScheduler) | In-process cron; no Redis |
| Email | `smtplib` over Gmail SMTP (App Password) | Free, perfect deliverability for self-notifications |
| AI | `anthropic` SDK 0.39 (Opus 4.7 default) | Tool use + prompt caching |
| Money | Integer cents in DB, `Decimal` arithmetic, `ROUND_HALF_UP` | Float-free math (see `app/services/money.py`) |
| Audit | SQLAlchemy session events (`before_flush` + `after_flush`) | Atomic with the change; never out of sync |
| Backups | `sqlite3.backup()` + `tar.gz` → Backblaze B2 (S3 API) | Consistent snapshot; off-site optional |
| Hosting | Railway (Hobby plan, 1GB volume) | One container + persistent volume; deploys on `git push` |

[Read the full reasoning in ARCHITECTURE.md.](ARCHITECTURE.md)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Browser (HTMX-enhanced)                   │
└─────────────────────────────────────┬───────────────────────┘
                                      │ HTTPS
┌─────────────────────────────────────▼───────────────────────┐
│   Railway edge (TLS termination, *.up.railway.app)           │
└─────────────────────────────────────┬───────────────────────┘
                                      │
┌─────────────────────────────────────▼───────────────────────┐
│  Gunicorn 23 (1 worker, 4 threads, 120s timeout)             │
│   ├─ Flask 3.0 application factory                           │
│   ├─ Flask-Login (Argon2id sessions)                         │
│   ├─ Flask-WTF (global CSRF)                                 │
│   ├─ Flask-Limiter (per-route opt-in)                        │
│   ├─ SQLAlchemy 2.0 (typed Mapped[], joinedload eager-load)  │
│   ├─ Alembic migrations                                      │
│   ├─ APScheduler (in-process; 03:00 backup, 06:30 briefing,  │
│   │   hourly reminder tick)                                  │
│   └─ Anthropic SDK (tool-use loop, prompt caching)           │
└──────┬──────────────────────────┬──────────────────────────┘
       │                          │
       ▼                          ▼
┌──────────────┐         ┌────────────────────┐    ┌──────────────┐
│ SQLite (WAL) │         │  Anthropic API     │    │ Gmail SMTP   │
│ /data/app.db │         │  Claude Opus 4.7   │    │ (App Pwd)    │
│ + /photos    │         └────────────────────┘    └──────────────┘
│ + /backups   │                                        ▲
│ + /CLAUDE.md │              ┌────────────────┐        │
│ on persistent│──nightly────▶│ Backblaze B2   │        │  notifications-to-self
│   volume     │              │ off-site backup│        │  (briefings + reminders)
└──────────────┘              └────────────────┘        │
                                                        │
                                              ◀ used by APScheduler jobs
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

# 4. Create the admin user (idempotent — uses ADMIN_EMAIL/ADMIN_PASSWORD from .env)
python -m scripts.create_admin --only-if-missing

# 5. Run the dev server
flask run

# Open http://127.0.0.1:5000
```

Common dev commands:

```bash
pytest                                   # run the 40-test suite
flask db migrate -m "describe change"    # generate a new migration after model change
flask db upgrade                         # apply pending migrations
flask db downgrade -1                    # roll back one migration
python -m scripts.run_backup             # trigger a backup manually
```

---

## Deploy to Railway

The repo ships with `railway.json`, `Procfile`, and `runtime.txt`.

1. Push to GitHub.
2. Railway → **New Project → Deploy from GitHub repo**.
3. Service → **Volumes** → mount 1GB at `/data`.
4. Service → **Variables** → Raw Editor → paste:

```
SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_urlsafe(48))">
DATABASE_URL=sqlite:////data/app.db
PHOTO_DIR=/data/photos
ARCHIVE_DIR=/data/archive
BACKUP_DIR=/data/backups
ADMIN_EMAIL=you@example.com
ADMIN_PASSWORD=<strong password>
BUSINESS_NAME=Lakewood Original
BUSINESS_ADDRESS=<your address>
BUSINESS_PHONE=<your phone>
BUSINESS_EMAIL=<email shown on invoices>
DEFAULT_COUNTY=Cuyahoga
APP_TIMEZONE=America/New_York

# Recommended:
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-4-7
# Outlook (default) — or set SMTP_HOST/PORT/USE_TLS for Gmail/Yahoo/etc.
SMTP_USER=you@outlook.com
SMTP_PASSWORD=xxxxxxxxxxxxxxxx
NOTIFY_EMAIL=you@outlook.com, you@gmail.com   # comma-sep = multiple recipients

# Optional cloud backups:
B2_ENDPOINT_URL=https://s3.us-east-005.backblazeb2.com
B2_KEY_ID=
B2_APPLICATION_KEY=
B2_BUCKET=lakewood-crm-backups
```

5. Push to `main` → Railway auto-deploys. The `release` step in `Procfile` runs:
   `flask db upgrade && python -m scripts.create_admin --only-if-missing`
6. **Settings → Networking → Generate Domain** for a `*.up.railway.app` URL.

The four-slash `////` in `DATABASE_URL` is intentional — it's an absolute SQLite path.

---

## Project structure

```
app/                              # Application package
  __init__.py                     # Flask application factory (create_app)
  config.py                       # All env-driven config + path resolution
  extensions.py                   # SQLAlchemy, Login, Migrate, CSRF, Limiter
                                  #   Plus SQLite pragma listener (WAL/FK/synchronous)

  models/                         # SQLAlchemy ORM (Mapped[] typed columns)
    audit_log.py                  # Append-only change history
    client.py                     # Customer + computed balance_owed
    conversation.py               # Assistant chat history
    invoice.py                    # State machine + paid_cents query + recompute_status
    job.py                        # State machine; relationships to invoices, source_quotes
    line_item.py                  # Polymorphic via two nullable FKs (CHECK constraint)
    notification.py               # Inbox content
    payment.py                    # Per-invoice ledger
    photo.py                      # Polymorphic over Property/Job/Visit
    property.py                   # Address + Ohio tax_rate (auto-resolved from ZIP)
    quote.py                      # State machine + Quote→Job conversion link
    setting.py                    # Singleton key-value store
    user.py                       # Operator login (Argon2id)
    visit.py                      # arrived_at/departed_at, computed duration

  auth/      clients/      jobs/        quotes/      invoices/
  reports/   properties/   assistant/   settings/    main/
                                  # Each is a Blueprint folder with routes.py + forms.py.
                                  # Templates live under app/templates/<blueprint>/.

  services/                       # Domain logic — keep views thin
    assistant.py                  #   Anthropic tool-use loop; CLAUDE.md persistence
    audit.py                      #   before_flush + after_flush listeners
    backup.py                     #   sqlite3.backup() → tar.gz → optional B2
    briefing.py                   #   Daily briefing assembly + Claude narrative + email
    email.py                      #   Gmail SMTP (App Password)
    money.py                      #   Cents/Decimal — float-free
    photos.py                     #   Pillow resize + EXIF rotate + auth-gated serve
    reminders.py                  #   Hourly tick — emits Notifications
    scheduler.py                  #   APScheduler bootstrap + reschedule_recurring_jobs

  templates/                      # Jinja templates organized by blueprint
  static/                         # CSS, manifest.json
  utils/                          # Pure stateless helpers
    ohio_tax.py                   #   ZIP → county → tax-rate lookup table
    phone.py                      #   US-only digit normalization

migrations/                       # Alembic versions (0001 → 0006)
scripts/                          # CLI entry points (create_admin, run_backup)
tests/                            # pytest (40 tests)
data/                             # Runtime — NOT in git (contents gitignored;
                                  #   directory structure preserved via .gitkeep)
wsgi.py                           # Gunicorn entry point
Procfile, railway.json            # Deploy config
runtime.txt                       # Python version pin for Railway nixpacks
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
the relationship cache hasn't refreshed.

### Ohio destination-based sales tax
`tax_rate` lives on `Property`, auto-resolved from ZIP via a curated
`ZIP_TO_COUNTY` table in [`app/utils/ohio_tax.py`](app/utils/ohio_tax.py).
Per-invoice `tax_rate_override` falls back to property's rate when null.
Cleveland metro + major OH cities seeded; expand annually as Ohio
Department of Taxation publishes new rates.

### State machines
`Job`, `Quote`, `Invoice` each have explicit transition tables. Job has
guarded `can_transition_to()` / `transition_to()` methods (invalid
transitions raise). Quote/Invoice transitions are simpler and gated at
the route level.

### Customer connectivity
Strong reverse relationships: `Client.jobs`, `Client.quotes`,
`Client.invoices`, `Client.balance_owed_cents` (computed property,
sums open-invoice balances). `Job` has back-populates to `client` and
`prop`, plus relationships to `invoices` and `source_quotes`.

### Security
- Global `CSRFProtect` from Flask-WTF, auto-applied to all state-changing
  HTTP methods.
- Jinja autoescape on. The single `|safe` use is on `Notification.body_html`,
  which is server-generated using `html.escape()` on every user-derived string.
- `?next=` parameter on login validated via `_is_safe_url()` to block
  open redirects.
- Argon2id password hashing (`argon2-cffi`) with auto-rehash on parameter
  upgrade.
- Login rate limit: 8/min, 30/hr per IP via Flask-Limiter (in-memory).
- Photos served behind `@login_required`; filenames are
  `secrets.token_urlsafe(8)` to prevent enumeration.

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
| `GET /settings/audit?entity_type=…&entity_id=…&operation=…` | Audit log viewer |
| `GET /health` | Liveness check (no auth) |

---

## License

Private business software for Lakewood Original. Not open-source.
