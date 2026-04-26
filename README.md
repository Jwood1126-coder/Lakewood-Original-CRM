# Handyman CRM

A solo-operator handyman CRM. Phase 0 + Phase 1 are in this commit:
clients, properties (with auto Ohio tax-rate from ZIP), photos, login,
nightly backups.

## ⚠ Open questions for Jake

These need your input before going live. Defaults are chosen so the app works
out of the box, but you'll want to override most of them in Railway env vars.

See [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md) for the full list.

The big ones:

1. **What's your business name + address?** — used on invoice headers in Phase 3.
   Set `BUSINESS_NAME`, `BUSINESS_ADDRESS`, `BUSINESS_PHONE`, `BUSINESS_EMAIL`.
2. **What domain do you want?** — Railway gives you `*.up.railway.app` for
   free. Buy a custom domain at Cloudflare ($10/yr) when you're ready.
3. **What admin email + password?** — set `ADMIN_EMAIL` / `ADMIN_PASSWORD`
   in Railway. If `ADMIN_PASSWORD` is empty, the create-admin script will
   generate one and print it to logs (one-time only).
4. **Anthropic API key?** — Phase 5 (assistant). Leave unset until then.
5. **Backblaze B2 credentials?** — Phase 1 cloud backup. App works without
   them; backups stay local-only.

---

## Run locally (5 minutes)

```bash
# 1. Create venv and install deps
python -m venv .venv
.venv\Scripts\activate         # Windows
# source .venv/bin/activate    # macOS/Linux
pip install -r requirements.txt

# 2. Copy env template and edit
cp .env.example .env
# At minimum, set SECRET_KEY (any long random string)

# 3. Run migrations to create the SQLite DB
flask db upgrade

# 4. Create the admin user
python -m scripts.create_admin
# Note the password it prints if you didn't set ADMIN_PASSWORD

# 5. Start the dev server
flask run
# Visit http://127.0.0.1:5000
```

## Run tests

```bash
pytest
```

## Deploy to Railway

1. Push this repo to GitHub.
2. Create a new Railway project, link the GitHub repo.
3. Add a **Volume** mounted at `/data`.
4. Set env vars (in Railway dashboard → Variables):
   ```
   SECRET_KEY=<long random string>
   DATABASE_URL=sqlite:////data/app.db
   PHOTO_DIR=/data/photos
   ARCHIVE_DIR=/data/archive
   BACKUP_DIR=/data/backups
   ADMIN_EMAIL=you@yourdomain.com
   ADMIN_PASSWORD=<a strong password>
   BUSINESS_NAME=Your Business Name
   BUSINESS_ADDRESS=123 Main St, Your City, OH 44000
   BUSINESS_PHONE=(555) 555-5555
   BUSINESS_EMAIL=you@gmail.com
   DEFAULT_COUNTY=Cuyahoga
   ```
5. Deploy. Railway runs `flask db upgrade` on release, then `gunicorn`.
6. Open Railway shell, run `python -m scripts.create_admin` once.
7. Visit your `*.up.railway.app` URL and log in.

When you're ready, optionally set the B2 vars to enable off-site backups.

## Project structure

```
app/
  __init__.py        # create_app() factory
  config.py          # all env-driven config in one place
  extensions.py      # SQLAlchemy, Flask-Login, Migrate, CSRF
  models/            # User, Client, Property, Photo
  auth/              # login, logout, change-password
  main/              # dashboard + /health
  clients/           # client CRUD + search
  properties/        # property CRUD + photo upload
  services/          # backup, photos, scheduler
  templates/         # Jinja templates (Pico.css + HTMX)
  static/            # CSS / JS / img
  utils/             # phone normalization, Ohio tax lookups
migrations/          # Alembic migrations
scripts/             # create_admin, run_backup
tests/               # pytest
data/                # ⚠ runtime — NOT in git (DB, photos, backups, archive)
wsgi.py              # Gunicorn entry point
```

## What's done

- ✅ Phase 0 — Flask app skeleton, auth, deploy pipeline
- ✅ Phase 1 — Clients + Properties + photo upload + nightly backup
- ⏳ Phase 2 — Jobs + Visits + "Today" view
- ⏳ Phase 3 — Quotes + Invoices + tax + customer token URLs
- ⏳ Phase 4 — Expenses + reports + monthly summary
- ⏳ Phase 4.5 — Reminders + daily/weekly briefings
- ⏳ Phase 5 — Claude assistant
- ⏳ Phase 6 — Stripe Payment Links (optional)

See [DECISIONS.md](DECISIONS.md) for every default choice and why.
