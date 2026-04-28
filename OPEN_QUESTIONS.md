# Open Questions for Jake (current state of env vars + decisions)

Defaults are picked so the app runs out of the box. These are the ones
where you should override the default before going live (or sooner).

---

## Required env vars (app won't start without these)

| Setting | Default | What to set |
|---|---|---|
| `SECRET_KEY` | dev fallback (insecure) | A 48+ char random string. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `DATABASE_URL` | `sqlite:///./data/app.db` | On Railway: `sqlite:////data/app.db` (4 slashes = absolute) |
| `PHOTO_DIR` / `ARCHIVE_DIR` / `BACKUP_DIR` | `./data/photos` etc. | On Railway: `/data/photos` etc. |
| `ADMIN_EMAIL` | `Jakewood@lakewoodoriginal.com` | Your real email |
| `ADMIN_PASSWORD` | `change-me-on-first-login` | A strong password |

## Required for the app to look right

| Setting | Default | Notes |
|---|---|---|
| `BUSINESS_NAME` | "Lakewood Original" | Used on invoice/quote headers + nav brand |
| `BUSINESS_ADDRESS` | (empty) | Set to your real address — appears on invoices |
| `BUSINESS_PHONE` | (empty) | Recommend: `(216) 770-7034` (your business phone) |
| `BUSINESS_EMAIL` | "Jakewood@lakewoodoriginal.com" | Email shown on invoices |
| `DEFAULT_COUNTY` | "Cuyahoga" | Default tax county for new properties when ZIP doesn't resolve |
| `APP_TIMEZONE` | "America/New_York" | Used for "today" semantics + scheduled jobs |

## Phase 5 — Claude assistant (recommended)

| Setting | Default | When |
|---|---|---|
| `ANTHROPIC_API_KEY` | unset | Phase 5 — generate at console.anthropic.com |
| `ANTHROPIC_MODEL` | `claude-opus-4-7` | Default; switch to `claude-sonnet-4-6` for ~5× cheaper |

## SMTP (for self-notifications — optional)

Customer email never goes through this. Only briefings, reminders, event
notices to YOU. Provider-agnostic.

| Setting | Default | Notes |
|---|---|---|
| `SMTP_HOST` | `smtp-mail.outlook.com` | Outlook personal default. For Gmail: `smtp.gmail.com`. For M365 work: `smtp.office365.com`. |
| `SMTP_PORT` | `587` | STARTTLS. For Gmail SSL: `465`. |
| `SMTP_USE_TLS` | `1` | STARTTLS. For Gmail SSL on 465: set to `0`. |
| `SMTP_USER` | (also reads legacy `GMAIL_USER`) | Your email |
| `SMTP_PASSWORD` | (also reads legacy `GMAIL_APP_PASSWORD`) | App Password from your provider |
| `NOTIFY_EMAIL` | (empty) | Comma-separated for multiple recipients: `jake@gmail.com, jake@outlook.com` |

App Password setup links:
- Outlook personal: https://account.live.com/proofs/AppPassword
- Microsoft 365: https://myaccount.microsoft.com (admin must enable SMTP AUTH)
- Gmail: https://myaccount.google.com/apppasswords

## Off-site backups (optional)

| Setting | Default | When |
|---|---|---|
| `B2_ENDPOINT_URL` | unset | e.g. `https://s3.us-east-005.backblazeb2.com` |
| `B2_KEY_ID` / `B2_APPLICATION_KEY` | unset | Generated at b2.backblazeb2.com |
| `B2_BUCKET` | unset | Create a private bucket; set its name |

If unset, backups still run nightly but stay local-only on the volume.

## Jobber migration (one-time use)

| Setting | Default | When |
|---|---|---|
| `JOBBER_CLIENT_ID` | unset | From developer.getjobber.com → your app |
| `JOBBER_CLIENT_SECRET` | unset | Same place |
| `JOBBER_REDIRECT_URI` | (auto-derived from request URL) | Override if you want explicit, e.g. `https://web-production-c8c82.up.railway.app/jobber/callback` |
| `JOBBER_GRAPHQL_VERSION` | `2025-04-16` | Jobber's latest stable API version. Bump as Jobber publishes new dates. |

## Phase 6 — Stripe (deferred)

| Setting | Default | Notes |
|---|---|---|
| `STRIPE_SECRET_KEY` | unset | Phase 6 only |
| `STRIPE_WEBHOOK_SECRET` | unset | Phase 6 only |
| Manual payment methods (Zelle, Venmo) | Already shown on invoices | Add your handles via Settings → Business |

---

## Decisions that are still open

| Decision | Status |
|---|---|
| Custom domain | None yet — you're on `web-production-c8c82.up.railway.app`. Buy at Cloudflare ($10/yr) when ready, point a CNAME at Railway. |
| Logo | Not in repo. Drop a PNG/SVG into `app/static/img/logo.png` when you have one — Phase 3 invoice templates will use it. |
| Whether to skip Larry Stoskus | Has your email + your address attached. Could be a real client (keep) or stale test (skip). Your call when you re-import. |
| Cloudflare Turnstile on intake form | Add if spam becomes a real problem. Free, ~5 lines of code. |
| Customer-facing accept-quote pages | Phase 3.5 — token URLs work but no UI yet. |
| Stripe Payment Links | Phase 6 — manual payment recording covers v1. |

---

## Setup checklist for first deploy

If you're spinning this up from scratch on Railway:

1. **Push the repo to GitHub.**
2. **Create Railway project** from the GitHub repo.
3. **Add 1GB volume** mounted at `/data`.
4. **Set the required env vars** above (all in the first table).
5. **Recommended:** also set the Anthropic + SMTP vars before first
   deploy so notifications and the assistant work immediately.
6. **Push to `main`** — Railway auto-deploys; release step runs migrations
   and creates the admin user.
7. **Settings → Networking → Generate Domain** for the `*.up.railway.app` URL.
8. **Sign in** with `ADMIN_EMAIL` + `ADMIN_PASSWORD`.
9. **Settings → Business info** → fill in real address + phone.
10. **Settings → Theme** → pick if you want non-default.
11. **Settings → Notifications** → pick your channels + recipients.
12. **Settings → Assistant** → check it's connected; edit CLAUDE.md.
13. **Settings → Import Jobber clients** OR **Settings → Jobber sync** →
    bring over your existing data.
14. **Drop the WordPress intake snippet** (see WEBSITE_INTAKE_SNIPPET.md)
    onto your contact page.
