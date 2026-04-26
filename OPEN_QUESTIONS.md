# Open Questions for Jake

Defaults are picked so the app runs out of the box. These are the ones
where you should override the default before going live (or sooner).

---

## Branding / display

| Setting | Default | Action |
|---|---|---|
| `BUSINESS_NAME` | "Your Business Name" | Set to your real business name |
| `BUSINESS_ADDRESS` | "123 Main St, Anytown, OH 44000" | Set to your real address |
| `BUSINESS_PHONE` | "(555) 555-5555" | Set to your real phone |
| `BUSINESS_EMAIL` | "" | Set to the email you want on invoices |
| Logo | None | Drop a PNG/SVG into `app/static/img/logo.png`, I'll wire it into the header in Phase 3 |

## Auth

| Setting | Default | Notes |
|---|---|---|
| `ADMIN_EMAIL` | "admin@example.com" | Set to your real email (used to log in) |
| `ADMIN_PASSWORD` | (none) | If unset, `python -m scripts.create_admin` generates one and prints to logs ONCE — save it then |

## Hosting

| Question | My assumption | Override? |
|---|---|---|
| Domain name | Use Railway's `*.up.railway.app` URL until you decide | Buy a `.com` at Cloudflare ($10/yr) when ready |
| Persistent volume mount path | `/data` on Railway | Confirmed in deploy steps |
| Single Gunicorn worker | Yes (so APScheduler doesn't run jobs 2x) | Don't change without revisiting scheduler.py |

## Tax

| Question | Default | Notes |
|---|---|---|
| Default Ohio county | Cuyahoga (8.0%) | Override via `DEFAULT_COUNTY` env. Per-property values auto-fill from ZIP when known. |
| ZIP→county lookup | Curated subset (Cleveland metro + major OH cities) | Add ZIPs as customers come from new counties — see `app/utils/ohio_tax.py` |
| Annual rate refresh | Manual update of `ohio_tax.py` each January | Ohio Dept of Taxation publishes the table |

## Phase 5 — Claude assistant

| Setting | Default | When to set |
|---|---|---|
| `ANTHROPIC_API_KEY` | unset | Phase 5 — generate at console.anthropic.com |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Don't change in Phase 5; revisit if cost matters |
| `CLAUDE.md` (system prompt) | not yet created | Phase 5 — created on persistent volume, editable via `/admin/system-prompt` |

## Phase 4.5 — Notifications

| Setting | Default | When to set |
|---|---|---|
| `GMAIL_USER` | unset | Phase 4.5 — your real Gmail |
| `GMAIL_APP_PASSWORD` | unset | Phase 4.5 — generate at myaccount.google.com → Security → App Passwords |
| `NOTIFY_EMAIL` | unset | Phase 4.5 — usually same as GMAIL_USER |

## Phase 1 — Backups

| Setting | Default | When to set |
|---|---|---|
| `B2_ENDPOINT_URL` | unset | Set to enable off-site backups |
| `B2_KEY_ID` / `B2_APPLICATION_KEY` | unset | Generated at b2.backblazeb2.com |
| `B2_BUCKET` | unset | Create a private bucket; set its name here |

If unset, backups still run nightly but stay local-only on the volume.

## Phase 6 — Payments

| Setting | Default | Notes |
|---|---|---|
| `STRIPE_SECRET_KEY` | unset | Phase 6 only |
| `STRIPE_WEBHOOK_SECRET` | unset | Phase 6 only |
| Manual payment methods (Zelle, Venmo) | Will appear on invoice in Phase 3 | Add your handles via env in Phase 3 |
