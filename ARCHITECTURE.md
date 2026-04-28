# How this program works (in plain English)

This document explains every meaningful design choice and the
architecture of the system, with no assumed technical background. If
you've ever asked "why did we use X instead of Y?" — the answer is here.

---

## 1. The big picture

Imagine a single computer somewhere. On that computer:

1. A **web server** is running, listening for requests from your phone or laptop.
2. When you tap something in the app, your phone sends a request to that
   computer over the internet.
3. The server reads the request, looks something up in a **database file**
   sitting next to it, builds an HTML page in response, and sends it back.
4. Your phone displays the page. The cycle repeats with the next tap.

That's the whole system. There are no separate "frontend servers" and
"backend servers", no message queues, no caches, no microservices. One
process does everything.

Why this shape? Because for one user with under 500 customers, anything
fancier is just more pieces that can break.

---

## 2. The five things that hold all your data

### Where data lives

```
/data/
   app.db                     ← every customer, job, invoice, etc.
   photos/                    ← every photo you upload
   backups/                   ← nightly snapshot tarballs
   archive/                   ← (Phase 3.5+) sent quote/invoice HTML snapshots
   CLAUDE.md                  ← the assistant's persistent instructions
```

The whole business runs out of that one folder. **If you copy that folder
to a thumb drive, you have a complete copy of the business.** Restore
that folder onto any computer with Python and the app starts back up.

### What's a "database file"?

`app.db` is a single SQLite file. Inside it are tables — think of them as
spreadsheets. Each table holds one kind of thing:

- `clients` — one row per customer
- `properties` — one row per service location
- `jobs` — one row per work order
- `visits` — one row per trip to a job site
- `quotes` — one row per estimate
- `invoices` — one row per bill
- `line_items` — one row per item on a quote or invoice
- `payments` — one row per payment received
- `photos` — one row per uploaded photo
- `users` — currently one row (you, the operator)
- `audit_log` — one row per change made to any of the above
- `notifications` — one row per briefing or reminder
- `conversations` + `messages` — assistant chat history
- `settings` — key-value pairs (business name, OAuth tokens, etc.)

[See DATA_SCHEMA.md for what's in each one.](DATA_SCHEMA.md)

### Why SQLite instead of Postgres?

Postgres is the standard answer for production apps because it handles
many simultaneous writers. You're one writer. SQLite handles thousands
of writes per second on a Raspberry Pi. The only tradeoff is "many
concurrent writers" — which doesn't exist for you.

Big practical wins from SQLite:
- **Backup is `cp app.db backup.db`.** That's it. Three keystrokes.
- **Restore is `cp backup.db app.db`** — same idea.
- Zero server to install, no port to open, no service to monitor.
- The whole DB is one file, you can open it on your laptop with
  [DB Browser for SQLite](https://sqlitebrowser.org/) and click around
  in any backup forever.

If you ever outgrow it (say, hire 5 employees who all submit jobs from the
field at the same time), Postgres is a one-line config change away.

---

## 3. The pieces of software ("the stack")

### Python 3.12

The programming language. Familiar = maintainable.

### Flask

The web framework. Receives a request, runs your code, returns HTML.
Flask is intentionally minimal — you assemble the pieces you want, no
more.

### SQLAlchemy + Alembic

SQLAlchemy is the **ORM** — Object Relational Mapper. Instead of writing
SQL by hand, you write Python: `client.name = "Mrs. Anderson"`,
`db.session.commit()`. SQLAlchemy translates that to SQL.

Alembic is the **migration system**. Whenever the database schema changes
(new column, new table), Alembic records the change as a versioned
"migration" file. On every deploy, Alembic checks which migrations have
already run and applies any new ones. **This is how you can change the
schema later without losing data.**

### Jinja2

The HTML templating engine. Lets us write `<h1>{{ client.name }}</h1>`
in templates that render with real data. Comes with Flask.

### HTMX

The "interactivity" library. Normally, building a real-feeling app means
a SPA (single-page app) like React — and a separate API. HTMX skips all
that: HTML pages can do `hx-get="/clients/?q=Smith"` and the response
HTML is swapped into the page. **No JavaScript framework. No build step.
No JSON API.**

### Pico.css

A tiny CSS framework that makes plain HTML look decent without us writing
a thousand class names. We layer a small `app.css` on top with our amber
"Lakewood" branding and the dark themes.

### APScheduler

Runs scheduled jobs (cron) inside the Python process — no separate
worker, no Redis. Used for nightly backups, daily briefings, and the
hourly reminder tick.

### Anthropic SDK (Claude)

The Python library for talking to Claude. Used by:
- The chat assistant at `/assistant`
- The daily briefing's narrative paragraph

We use **prompt caching** so the system prompt is sent once and reused
for ~5 minutes — drops cost ~10× for follow-up messages in a
conversation.

### SMTP (Outlook / Gmail / etc.)

The "email sender". Provider-agnostic via env vars. Defaults to Outlook.com
personal; one config swap and it's Gmail or Microsoft 365 instead.

You generate an **App Password** in your email account once and the app
uses it to send emails *from* your account *to* whichever recipients
you've configured. **Customers never receive email from the app** — the
SMTP integration is operator-only (briefings, reminders, event notices).

### Pillow

Image library. Resizes photos you upload to 1600px max so a 5MB phone
photo becomes a ~300KB stored image. Auto-rotates per EXIF metadata so
photos don't appear sideways.

### Backblaze B2

The off-site backup destination. Cheap (~$6/TB/month — practically free
at our volume). The app writes a tarball nightly and uploads it via the
S3-compatible API.

### Cloudflare DNS / Railway

**Railway** is where the app runs in production. One always-on container,
one persistent volume mounted at `/data`. Auto-deploys when you `git push`
to `main`.

### ProxyFix middleware (subtle but important)

Railway terminates HTTPS at its edge proxy and forwards plain HTTP to
the container. Without ProxyFix, the app thinks it's serving HTTP and
generates `http://...` URLs everywhere — which broke the Jobber OAuth
flow because Jobber requires the redirect URI to match exactly. ProxyFix
reads `X-Forwarded-Proto: https` from Railway's edge and tells the rest
of Flask "you're really behind HTTPS."

### Cryptography (Fernet + HKDF)

For encrypting Jobber OAuth tokens at rest. The encryption key is
derived from `SECRET_KEY` via HKDF-SHA256, so we don't need a separate
secret to manage. If you rotate `SECRET_KEY`, stored Jobber tokens
become unreadable and you'd just reconnect Jobber.

### Requests

The HTTP client we use to talk to Jobber's GraphQL API. Not pulled in
transitively by anything else (anthropic uses httpx, boto3 uses its own
client) — explicitly listed in requirements.txt.

---

## 4. How a request flows

When you tap "Mrs. Anderson" in the clients list:

```
Your phone
   │  GET /clients/42
   ▼
Railway edge (terminates HTTPS, sets X-Forwarded-Proto=https)
   │
   ▼
ProxyFix middleware (tells Flask "scheme is https")
   │
   ▼
Gunicorn (web server) in the Railway container
   │
   ▼
Flask app
   │
   │  1. Check session cookie → confirm you're logged in
   │  2. Load Client #42 from SQLite (one query)
   │  3. Render templates/clients/view.html with that client
   │
   ▼
HTML response back to your phone
```

The whole round trip is typically 50–100ms. There's no front-end build
step, no API contract to maintain, no second service to deploy.

---

## 5. Atomic transactions ("nothing half-written")

**Every page load that changes data is one transaction.** That means:

- All the changes happen together, OR none of them happen.
- If anything fails partway through (network drops, code crashes, disk
  fills), the whole thing rolls back as if nothing happened.

Concretely: when you save a quote with 5 line items:
1. The Quote row is staged in memory.
2. SQLAlchemy "flushes" to get the auto-assigned Quote ID.
3. The 5 LineItem rows are staged.
4. All 6 INSERTs go through together as one DB commit.
5. If step 4 fails for any reason, all 6 rows vanish — the DB is exactly
   as it was before.

This is enforced by SQLAlchemy's per-request session model. There are
**no multi-commit operations** anywhere in the codebase that could leave
data half-updated.

---

## 6. The audit log ("nothing is ever lost")

Every change to your data is automatically logged in the `audit_log`
table — *in the same transaction as the change itself.* That means the
audit row and the change either both succeed or both roll back; they
can never get out of sync.

Each audit log entry records:
- **When**: timestamp
- **What**: insert / update / delete
- **Which**: entity type + ID (e.g., `Quote #42`)
- **Who**: your email if logged in, or "system" for scheduled jobs
- **Before**: full row snapshot (for updates and deletes)
- **After**: full row snapshot (for inserts and updates)
- **Summary**: human-readable one-liner ("Job #42 status: scheduled → complete")

You view it at Settings → Audit log, filterable by table, ID, and
operation. **Even deleted records survive in the log.** If you need to
restore a deleted client, the audit row's `before_json` has every column
value — you can recreate the row by hand.

How is this implemented? SQLAlchemy session events. We hook
`before_flush` (capture changes) and `after_flush` (write the log row
now that auto-incremented IDs exist). It's about 200 lines of code
(`app/services/audit.py`) and zero changes to your route code — every
table is captured automatically.

---

## 7. Backup strategy ("when, not if")

Three layers of backup:

1. **Railway's persistent volume** is replicated within their infra. This
   protects against disk failure but is not really a "backup" — if you
   accidentally delete a client at 2pm, the volume snapshot has the delete.
2. **Nightly tarball at 03:00 your local time.** A SQL-consistent SQLite
   snapshot + the photos folder + CLAUDE.md, all packed into one
   `snapshot-YYYY-MM-DDTHH-MM-SSZ.tar.gz`.
   - Local copy stays on the volume for 7 days.
   - If Backblaze B2 env vars are set, copy is also uploaded to B2.
   - If they aren't, it stays local-only — the app still works, you just
     don't have off-site copies.
3. **Quarterly local pull** (your discipline). Once a quarter, download
   the latest backup to a USB drive at home. Insurance against
   "everything cloud is gone."

Manual "Backup now" button at Settings → Backups. Each backup file is
downloadable from the same page.

[Restore procedure in RESTORE.md.](RESTORE.md)

---

## 8. The Claude assistant

The assistant is a chat sidebar at `/assistant`. You can ask it about
your data — "What's on tomorrow?", "Who is Mrs. Anderson?", "What's
overdue?" — and it answers using **tool use**, which means it calls
small Python functions that read your DB and feeds the results back to
itself.

### Tools the assistant has access to (read-only)

- `get_today_summary` — today's jobs + in-progress + overdue counts
- `list_jobs(start, end, status)` — filtered job list
- `get_job(id)` — full job detail with visits
- `search_clients(query)` — fuzzy match by name/phone/email
- `get_client(id)` — full client detail with properties + recent jobs

The assistant **cannot write to the database**. This is intentional. A
hallucinated "scheduled Mrs. Smith for Tuesday" when she actually said
Wednesday is real money. Future versions may add propose-confirm tools
where the assistant suggests an action and you click Confirm.

### CLAUDE.md — the assistant's instructions

Lives at `/data/CLAUDE.md` on the persistent volume (so it survives
deploys). Contains your work hours, customer notes, communication style,
and anything else you want the assistant to know. **Edit it from the
browser** at Settings → Assistant. Changes take effect on the next message.

### Models

You can pick from:
- **Opus 4.7** (default) — smartest, ~$15/M input tokens
- **Sonnet 4.6** — fast, ~$3/M input tokens
- **Haiku 4.5** — fastest, cheapest

Realistic monthly cost on Opus with daily briefings + ~50 chat messages:
**$10–15/mo.** Sonnet would be ~$2–4/mo. Set a budget alert in the
Anthropic console as a circuit breaker.

---

## 9. The notification system

Two delivery channels:
1. **In-app inbox** at `/inbox`. Always on. Unread badge in the nav.
2. **Email** via SMTP (Outlook, Gmail, M365, Yahoo, etc.). Optional —
   only if you set `SMTP_USER` + `SMTP_PASSWORD`. Multi-recipient via
   `NOTIFY_EMAIL=jake@gmail.com, jake@outlook.com`.

### Scheduled briefings (configurable per-rule at Settings → Notifications)

- **Daily** at 06:30 your local time. Today's jobs + overdue + 7-day
  outlook + a one-sentence narrative from Claude.
- **Weekly** (planned: Sunday 17:00).
- **Monthly report** (planned: 1st of month at 08:00).
- **Job-day reminder** at 06:00 if the daily briefing is off.

### Event triggers (Jobber-style)

Per-event email + in-app notifications when meaningful things happen:

- 📩 New website request received
- Quote sent / accepted / converted
- Job marked complete
- Invoice sent / paid in full
- Payment recorded

Each one has its own toggle. You can disable any individually without
disabling the email channel.

### Why this design (event helpers vs. audit-log subscription)

Route handlers call the helpers (`notify_invoice_paid(invoice)`)
explicitly after the DB commit. We **don't** subscribe to the audit log
because that would couple business meaning ("paid") to incidental schema
changes ("status went from X to Y"). The event helpers stay readable and
easy to test.

---

## 10. The website "request a quote" intake

Your WordPress site at lakewoodoriginal.com posts customer requests
directly into the CRM via `POST /intake/api/request`. The endpoint:

1. Validates required fields + checks honeypot for bots
2. Per-IP rate-limited (8/hour)
3. Matches existing client by phone+name OR creates new
4. Creates a Property at the given address (auto Ohio tax-rate from ZIP)
5. Creates a Quote in `draft` status with the customer's description
6. Fires an event notification (📩 New website request) → operator inbox + email

CORS is locked to `https://lakewoodoriginal.com` so only your site can
post. The route is CSRF-exempt because it's cross-origin (your WordPress
site is a different domain than the CRM).

A self-hosted fallback form lives at `/intake/request` if the WordPress
embed isn't ready or you want a direct shareable URL.

[See WEBSITE_INTAKE_SNIPPET.md for the WordPress copy-paste.](WEBSITE_INTAKE_SNIPPET.md)

---

## 11. Jobber migration (one-time)

Two paths because Jobber's CSV export emails sometimes don't arrive:

### CSV path (Settings → Import Jobber clients)
You download the Clients CSV from Jobber's UI, upload it to the CRM.
The importer:
- Groups rows by Jobber's client_id (multi-property rows collapse to one client)
- Auto-fills Ohio county + tax rate from ZIP
- Skip-list field for known dupes / test entries (pre-populated based on your data)
- Idempotent re-runs (Jobber ID stamped in client notes)

### API path (Settings → Jobber sync)
When CSV exports aren't working, this pulls data directly from
Jobber's GraphQL API:
- OAuth flow → encrypted token storage
- Pages through clients, jobs, quotes, invoices, payments
- Throttle handling: pre-call sleep + exponential backoff + cool-down between stages
- Same dedup as the CSV importer
- Single "🚀 Pull EVERYTHING" button runs all syncs in dependency order

[Detailed flow in JOBBER_INTEGRATION.md.](JOBBER_INTEGRATION.md)

---

## 12. Authentication (very simple, on purpose)

- **You** log in with email + password (Argon2id-hashed).
- One user. No registration page. Admin user is created by the
  `create_admin` script on first deploy from the `ADMIN_EMAIL` and
  `ADMIN_PASSWORD` env vars.
- Sessions via signed cookie. "Remember me" extends to 30 days.
- **No password reset by email** — by design, since we don't send
  customer email and don't want to depend on an email service just for
  one self-recovery flow. Forgot your password? Open Railway's web
  shell and run `python -m scripts.create_admin --password "newpass"`.
- **Login rate limit**: 8/min, 30/hr per IP via Flask-Limiter. Friendly
  429 page if exceeded.

**Customers** never log in. Quote/invoice URLs use a 32-character random
token (`/q/<token>`, `/i/<token>` — Phase 3.5) so you text or email the
URL and they click to view.

---

## 13. Themes

Three themes selectable from Settings → Theme:

- **Dark** (default) — comfortable dark UI with amber accent.
- **AMOLED** — pure black background. Better on OLED phone screens at
  night, slightly easier on the battery. Layered on top of Pico's "dark"
  theme via a custom `data-app-theme="amoled"` attribute (Pico itself
  only knows light/dark).
- **Light** — for daytime / bright outdoor use.

Theme is per-user (one user, but the column is there for the future) and
stored on the User row.

---

## 14. Mobile-first UI

The app was designed for phone use first, desktop second:

- **Bottom navigation bar** on phones (Today / Calendar / [Assistant FAB] /
  Clients / More) — thumb-reachable.
- **Top navigation bar** on tablets and desktop — full menu.
- **Tables collapse to cards** on narrow screens (clients list, etc.).
- **Form inputs are 16px** to prevent iOS zoom-on-focus.
- **44px minimum tap targets** everywhere.
- **`safe-area-inset` support** for iPhone notch and home indicator.
- **PWA manifest** so you can "Add to Home Screen" and the app opens
  full-screen like a native app.

---

## 15. Time zones (critical detail)

Everything stored in the DB is **UTC** (`datetime.utcnow()`). Everything
the operator sees is converted to **operator-local** via the
`APP_TIMEZONE` env var (default `America/New_York`).

Why this matters: server clocks run in UTC. If we used `date.today()`
on the server, around midnight Eastern the dashboard's "today" would
disagree with the wall clock for 4–5 hours. We avoid this with
`app/utils/timezone.py` — `today_local()` and `now_local()` — used in
the dashboard, briefing, reminder dedup, and invoice overdue check.

---

## 16. What we deliberately didn't build (yet)

| Feature | Why deferred |
|---|---|
| Customer-facing accept page | Phase 3.5 — token URLs work, accept-by-click coming |
| Stripe Payment Links | Phase 6 — manual payment recording covers v1 needs |
| Recurring jobs (RRULE) | Repeat-job button covers most cases |
| SMS reminders | Use your phone |
| Customer login portal | Magic-link tokens cover the use case at zero friction |
| Photo AI tagging | Future nice-to-have |
| Multi-user / crew accounts | Single-operator for now |
| Photo upload on intake form | Phase 4 nice-to-have |
| Cloudflare Turnstile on intake | Add only if spam becomes a real problem |
| Soft delete (`deleted_at`) | Audit log captures full delete snapshot — recovery is possible without a deleted_at column |

---

## 17. What "simple is elegant" actually meant

When designing the system, we explicitly rejected several "industry standard"
choices because they don't pull their weight at this scale:

- **Postgres** — overkill for one writer. Adds a service to manage.
- **Redis + Celery** — needed for queue workers we don't have.
- **React/Vue/SPA frontend** — quadruples the project. HTMX gives 80%
  of the UX with 5% of the effort.
- **Tailwind CSS with build pipeline** — Pico classless gets the same
  polish without Node.
- **Postmark/SES for transactional email** — Outlook/Gmail handles our use case.
- **Docker Compose / Kubernetes** — one process is just a process.
- **JWT / OAuth** for our own users — cookie sessions for one user, full stop.
  (Jobber is a separate use of OAuth — we're a *client* of Jobber's API.)

Each "no" represents present operational simplicity in exchange for some
future flexibility. If you ever genuinely outgrow a choice, the
alternative is one or two refactors away.
