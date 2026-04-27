# Lakewood Original CRM

A self-hosted, mobile-first field-service CRM built for **Lakewood Original** —
a solo handyman business in Cleveland, OH. Replaces Jobber for the
operator's day-to-day workflow at a fraction of the cost, with a built-in
Claude assistant and an automated daily-briefing pipeline.

> **Design philosophy:** simple is elegant. Every dependency earns its
> slot. The whole system is one Python process, one SQLite file, and a
> folder of photos. If your house is on fire, you can restore from a
> 200KB backup.

---

## Documents

- [README.md](README.md) — you are here. Overview, run instructions, deploy guide.
- [ARCHITECTURE.md](ARCHITECTURE.md) — non-technical: how the pieces fit, why each tool was chosen.
- [DATA_SCHEMA.md](DATA_SCHEMA.md) — non-technical: every table, every relationship, plain English.
- [DECISIONS.md](DECISIONS.md) — every non-trivial default with the reasoning.
- [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md) — env vars + decisions still pending.
- [RESTORE.md](RESTORE.md) — disaster-recovery playbook.

---

## What it does

| Capability | Status |
|---|---|
| Client + property CRM | ✅ Phase 1 |
| Photos attached to properties / jobs / visits | ✅ Phase 1 |
| Job scheduling + multi-visit tracking | ✅ Phase 2 |
| Calendar (month / week / day) with view switcher | ✅ |
| Quotes with line items + tax + status lifecycle | ✅ Phase 3 |
| Invoices with line items + multi-payment tracking | ✅ Phase 3 |
| Quote → Job conversion, Job → Invoice creation | ✅ Phase 3 |
| Customer-facing token URLs (no login) | ⏳ Phase 3.5 |
| Stripe Payment Links | ⏳ Phase 6 |
| Claude assistant (chat, tool-use, editable system prompt) | ✅ Phase 5 |
| Daily / weekly / monthly briefings via Claude + email | ✅ Phase 5 |
| Reminders (job-day; quote/invoice follow-ups) | ⏳ Partial |
| In-app inbox + email channel via Gmail SMTP | ✅ |
| Automatic audit log of every data change | ✅ |
| Nightly backups (local + Backblaze B2) | ✅ |
| Manual on-demand backups + downloads | ✅ |
| Themes (Dark / AMOLED / Light) | ✅ |
| Mobile bottom-nav + iPhone PWA install | ✅ |

29 tests passing.

---

## Quick start (run locally, 5 minutes)

```bash
# 1. Create venv + install deps
python -m venv .venv
.venv\Scripts\activate         # Windows
# source .venv/bin/activate    # macOS/Linux
pip install -r requirements.txt

# 2. Copy env template, set SECRET_KEY at minimum
cp .env.example .env
# Edit .env: set SECRET_KEY to any long random string

# 3. Apply migrations
flask db upgrade

# 4. Create the admin user (uses ADMIN_EMAIL/ADMIN_PASSWORD from .env)
python -m scripts.create_admin --only-if-missing

# 5. Run the dev server
flask run
# → http://127.0.0.1:5000
```

Run tests:

```bash
pytest
```

---

## Deploy to Railway

The repo is configured for Railway out of the box (`railway.json`, `Procfile`,
`runtime.txt`). One-time setup:

1. Push the repo to GitHub.
2. Railway → New Project → Deploy from GitHub repo.
3. **Add a Volume** mounted at `/data` (1 GB to start).
4. Set environment variables in Railway → Variables → Raw Editor:

```
SECRET_KEY=<long random — generate with: python -c "import secrets; print(secrets.token_urlsafe(48))">
DATABASE_URL=sqlite:////data/app.db
PHOTO_DIR=/data/photos
ARCHIVE_DIR=/data/archive
BACKUP_DIR=/data/backups
ADMIN_EMAIL=you@example.com
ADMIN_PASSWORD=<a strong password>
BUSINESS_NAME=Lakewood Original
BUSINESS_ADDRESS=<your address>
BUSINESS_PHONE=<your phone>
BUSINESS_EMAIL=<invoice email>
DEFAULT_COUNTY=Cuyahoga
APP_TIMEZONE=America/New_York

# Optional but recommended:
ANTHROPIC_API_KEY=sk-ant-...      # Phase 5 assistant
ANTHROPIC_MODEL=claude-opus-4-7   # default; can also use sonnet-4-6 for cheaper

GMAIL_USER=you@gmail.com           # Phase 5 email channel
GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx
NOTIFY_EMAIL=you@gmail.com

# Optional cloud backups (Phase 1):
B2_ENDPOINT_URL=https://s3.us-east-005.backblazeb2.com
B2_KEY_ID=
B2_APPLICATION_KEY=
B2_BUCKET=lakewood-crm-backups

# Optional payments (Phase 6, not yet wired):
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
```

5. Push to `main` — Railway auto-deploys. The `release` step in Procfile
   runs `flask db upgrade && python -m scripts.create_admin --only-if-missing`
   so the schema is up to date and an admin user exists on first run.
6. Settings → Networking → **Generate Domain** to get your `*.up.railway.app` URL.
7. Sign in with `ADMIN_EMAIL` + `ADMIN_PASSWORD`.

---

## Tech stack at a glance

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Familiar, well-supported |
| Web framework | Flask 3 | Familiar; right size for this app |
| ORM + migrations | SQLAlchemy 2.x + Alembic | Industry standard; Alembic is the migration system |
| Database | SQLite (WAL mode) | Single-writer, fits in one file, backup = `cp` |
| HTML | Jinja2 (built into Flask) | — |
| Interactivity | HTMX 2.x | Server returns HTML fragments — no JSON API, no React |
| CSS | Pico.css 2 + small overrides | Classless, zero build step |
| Auth | Flask-Login + Argon2id | Solid baseline, no password-reset email needed |
| Background jobs | APScheduler in-process | Simple cron, no Redis |
| AI assistant | Anthropic SDK (Opus 4.7) | Tool use + prompt caching |
| Email | Gmail SMTP via App Password | Free, perfect deliverability for self-notifications |
| PDF | HTML-first, browser print | No native deps |
| Backups | sqlite3 .backup + tar.gz → Backblaze B2 | Simple, durable |
| Hosting | Railway (Hobby) | One always-on container + persistent volume |
| Photos | Pillow resize to 1600px, EXIF rotate | Phone-uploaded photos shrink ~10× |
| Audit | SQLAlchemy session events → AuditLog table | Captured atomically with the change |

[Read the full reasoning in ARCHITECTURE.md](ARCHITECTURE.md).

---

## Project structure

```
app/
  __init__.py             # Flask application factory (create_app)
  config.py               # All env-driven config in one place
  extensions.py           # SQLAlchemy, Login, Migrate, CSRF; SQLite pragmas

  models/                 # SQLAlchemy ORM models
    audit_log.py          #   Automatic change log
    client.py             #   Customer (with reverse rels to jobs/quotes/invoices + balance_owed)
    conversation.py       #   Assistant chat history
    invoice.py            #   Invoice + status state machine
    job.py                #   Job + status state machine
    line_item.py          #   Used by both Quote and Invoice
    notification.py       #   In-app inbox / email digest content
    payment.py            #   Recorded against an Invoice
    photo.py              #   Polymorphic over Property/Job/Visit
    property.py           #   Service location tied to a Client
    quote.py              #   Quote + status state machine
    setting.py            #   Singleton key-value store (business info etc.)
    user.py               #   Operator login
    visit.py              #   One trip to a job site

  auth/      clients/      jobs/        quotes/      invoices/
  properties/  assistant/  settings/    main/

    # Each blueprint folder has routes.py + forms.py.
    # Templates live under app/templates/<blueprint>/

  services/               # Domain logic — keep views thin
    assistant.py          #   Claude chat + tool-use loop + CLAUDE.md persistence
    audit.py              #   SQLAlchemy event listeners (before_flush + after_flush)
    backup.py             #   sqlite3 .backup → tarball → optional B2 upload
    briefing.py           #   Daily briefing assembly + Claude narrative + email
    email.py              #   Gmail SMTP sender
    money.py              #   Cents/Decimal math; never floats
    photos.py             #   Resize + serve
    reminders.py          #   Hourly tick — fires job-day reminders
    scheduler.py          #   APScheduler init + reschedule on settings change

  templates/              # Jinja templates
  static/                 # CSS / JS / manifest.json
  utils/                  # phone normalize, Ohio ZIP→county→tax_rate

migrations/               # Alembic versioned migrations
scripts/                  # CLI helpers (create_admin, run_backup)
tests/                    # pytest test suite
data/                     # Runtime: SQLite db + photos + backups + CLAUDE.md
                          #   ⚠ contents not in git — lives on the volume
wsgi.py                   # Gunicorn entry point
Procfile, railway.json    # Deploy configuration
```

---

## Atomic transactions + automatic audit log

**Atomic by design.** Every Flask route call commits its changes once at
the end. If anything raises, SQLAlchemy rolls back the whole transaction.
Multi-step operations (e.g., creating a Quote with line items) flush
mid-request to get auto-incremented IDs but do not commit until the very
end. There are no two-step operations that can leave the DB
half-updated.

**Audit log captures every change**, atomically, in the same transaction
as the change itself:

- `before_flush` SQLAlchemy event captures the before/after column values
  for inserts, updates, deletes on tracked models (Client, Property, Job,
  Visit, Quote, Invoice, LineItem, Payment).
- `after_flush` materializes the AuditLog rows now that auto-incremented
  IDs are known.
- Both run in the same DB transaction → audit log can never be out of sync
  with the data.
- AuditLog itself is intentionally *not* tracked, and is read-only from the
  UI. Even if a row is deleted, the audit log keeps the full before-snapshot,
  so nothing is ever truly lost.

View the audit log at **Settings → Audit log**, filterable by entity type,
entity ID, and operation.

---

## Live URLs (after deploy)

- `/` — Today dashboard
- `/jobs/calendar?view=month|week|day` — Calendar
- `/jobs`, `/quotes`, `/invoices` — list + filter by status
- `/clients/<id>` — Customer profile with all jobs/quotes/invoices + balance owed
- `/assistant` — Claude chat
- `/inbox` — Notifications (briefings + reminders)
- `/settings` — Profile, theme, business info, password, backups, audit log,
  assistant config, notifications config

---

## Contributing / next steps

This is a single-operator app. There's no public contribution flow — but if
you fork it, see the phased roadmap in DECISIONS.md to understand
in-progress vs deferred work.
