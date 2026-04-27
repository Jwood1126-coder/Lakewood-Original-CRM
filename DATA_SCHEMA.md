# Data Schema (in plain English)

A guided tour of every table in the database, what's in it, and how it
connects to other tables. No SQL knowledge required.

If you want to see this in code form, look in `app/models/`. Each `.py`
file there corresponds to one table.

---

## How to read the diagrams

```
A ──n── B    means "one A has many Bs"
A ──1── B    means "one A is linked to exactly one B"
   │ FK      means "B has a column pointing to A"
```

---

## The complete picture

```
                  ┌──────────────┐
                  │   Client     │  ← The customer (you only)
                  │   "person"   │
                  └──────────────┘
                     │ 1     1     1     1
                     ▼ n     ▼ n   ▼ n   ▼ n
              ┌──────────┐  ┌────┐ ┌─────┐ ┌────────┐
              │ Property │  │Job │ │Quote│ │Invoice │
              └──────────┘  └────┘ └─────┘ └────────┘
                     │           │ 1     │ 1
                     │ 1     1   ▼ n   ▼ n
                     ▼ n     n   Visit  Payment
                  ┌────────┐ ┌────────┐ ┌────────┐
                  │ Photo  │ │Visit   │ │Payment │
                  └────────┘ └────────┘ └────────┘

      Quote → Job  (Quote.converted_to_job_id ──→ Job)
      Job   → Invoice (Invoice.job_id ──→ Job)

   Plus three "system" tables:
     User ── you (one row)
     Setting ── key-value config
     AuditLog ── every change to the above

   Plus assistant + notifications:
     Conversation → Message
     Notification (briefings + reminders)
```

---

## The nine "business" tables

### `clients` — The customer

The root of everything. A client is a person or business you do work for.

| Field | What it is |
|---|---|
| `id` | Unique number (1, 2, 3...) — auto-assigned |
| `name` | "Mrs. Anderson" or "Smith Rentals" |
| `phone` | 10 digits, stored as just digits ("2165550142"). Display formatting (`(216) 555-0142`) happens at render time. |
| `email` | Optional |
| `notes` | Free-text — payment habits, gate codes you keep at the customer level, etc. |
| `created_at`, `updated_at` | Timestamps |

**A client has many properties, jobs, quotes, and invoices.** When you
delete a client, all of those are deleted too (cascade). Audit log keeps
the snapshot, so a delete is recoverable.

A client also has a computed `balance_owed_cents` — the sum of all open
invoice balances. Shown as a red pill on the client view if > $0.

---

### `properties` — Where the work happens

A property is a service location tied to a client. One client can have
many (e.g., Smith Rentals has 3 rental houses).

| Field | What it is |
|---|---|
| `id` | Unique number |
| `client_id` | Which client owns this property |
| `label` | "Home", "Rental #1", "Mom's House" — your label |
| `address_line1`, `line2`, `city`, `state`, `zip_code` | Address |
| `county` | Auto-filled from ZIP via the Ohio lookup table |
| `tax_rate` | Decimal fraction (e.g., 0.0800 = 8%). Auto-set from county. |
| `notes` | Access codes, gate codes, dog warnings |

**Why is `tax_rate` on the property and not the client?** Ohio is a
*destination-based* sales tax state — the rate depends on where the
work happens, not who's paying. A landlord client might have rentals in
two counties with different rates.

---

### `jobs` — The work order

A job is the agreement of "I will do X at Y on Z date for $." Jobs go
through a status lifecycle:

```
   draft ── (none — we skip draft, jobs start scheduled)
   scheduled ─→ in_progress ─→ complete
       │            │            │
       └────────────┴─→ canceled ┘
```

| Field | What it is |
|---|---|
| `id` | Unique number |
| `client_id` | The customer |
| `property_id` | Where the work happens |
| `title` | One-line summary ("Replace kitchen faucet") |
| `scope` | Free-text description |
| `status` | scheduled / in_progress / complete / canceled |
| `scheduled_date`, `scheduled_time` | When |
| `est_hours` | Your estimate |
| `notes` | Internal notes (only you see) |

**A job has many visits.** A job may have invoices (usually 0 or 1,
sometimes more for split-billing). A job may be the destination of a
converted quote (`Quote.converted_to_job_id` points back here).

The job page exposes one-tap "Start visit" / "End visit" buttons that
record arrival/departure timestamps automatically.

---

### `visits` — One trip to the job site

A multi-visit job (most are) needs separate records of when you actually
showed up.

| Field | What it is |
|---|---|
| `id` | Unique number |
| `job_id` | Which job this visit was for |
| `scheduled_date` | Calendar date of the visit |
| `arrived_at` | Timestamp (UTC) — when you tapped "Start visit" |
| `departed_at` | Timestamp (UTC) — when you tapped "End visit" |
| `miles` | Optional — miles you drove for this visit |
| `notes` | What you did on this visit |

Computed: `duration` (departed − arrived). The job page shows total
visit hours and total miles across all visits.

---

### `quotes` — The estimate

A quote is what you send to a customer for approval. Status lifecycle:

```
   draft → sent → (accepted | declined | expired)
                       │
                       ▼
                   converted   ← when you turn it into a Job
```

| Field | What it is |
|---|---|
| `id`, `number` | DB ID + human-friendly number (Q-1, Q-2...) |
| `client_id`, `property_id` | Linked customer + location |
| `subject` | One-line summary |
| `message_to_customer` | What the customer sees |
| `internal_notes` | Only you see |
| `status` | draft / sent / accepted / declined / expired / converted |
| `token` | 32-char random URL-safe string. Used for the customer-facing `/q/<token>` URL. |
| `tax_rate_override` | Optional — if blank, uses property's tax rate |
| `valid_until` | Quote expires after this date |
| `converted_to_job_id` | If accepted and converted, points to the new Job |
| Various timestamps | created_at, updated_at, sent_at, accepted_at, declined_at |

**A quote has many line items.** The total is computed (no `total_cents`
column) — sum of line items + tax.

---

### `invoices` — The bill

An invoice is what you bill the customer. Status lifecycle:

```
   draft → sent → partial → paid
                    │         │
                    └─→ void ─┘
   "overdue" is computed from due_date, not stored.
```

| Field | What it is |
|---|---|
| `id`, `number` | DB ID + human-friendly number (#1001, #1002...) |
| `client_id`, `property_id` | Linked customer + location |
| `job_id` | Optional — if billing for a specific job |
| `subject` | One-line summary |
| `notes` | Free-text shown on the invoice |
| `status` | draft / sent / partial / paid / void |
| `token` | Customer-facing URL token |
| `tax_rate_override` | Same as quote |
| `due_date` | When payment is due |

**An invoice has many line items and many payments.** Status updates
automatically based on payment progress (we call
`invoice.recompute_status()` after every payment).

Computed properties:
- `subtotal_cents`, `tax_cents`, `total_cents`
- `paid_cents` — sum of all payments
- `balance_cents` — total minus paid
- `is_overdue` — true if balance > 0 and due_date < today
- `days_overdue` — for the overdue pill

---

### `line_items` — The things on a quote or invoice

A line item is one row on a quote or invoice. Each line item has either a
`quote_id` OR an `invoice_id` (never both — a CHECK constraint enforces
at least one is set).

| Field | What it is |
|---|---|
| `id` | Unique number |
| `quote_id` | If on a quote |
| `invoice_id` | If on an invoice |
| `position` | Display order (0, 1, 2...) |
| `description` | "Replace kitchen faucet", "Labor (1.5 hr)", etc. |
| `quantity` | Decimal — supports 1.5 hours, etc. |
| `unit_price_cents` | Stored as integer cents. **Never floats.** |
| `taxable` | Bool — only taxable items contribute to tax |

`line_total_cents` = quantity × unit_price_cents (computed).

---

### `payments` — Recorded against an invoice

Multiple payments per invoice are allowed (deposits, partial payments,
etc.).

| Field | What it is |
|---|---|
| `id` | Unique number |
| `invoice_id` | Which invoice |
| `amount_cents` | Integer cents |
| `method` | cash / check / zelle / venmo / card / other |
| `reference` | Check number, Venmo handle, etc. |
| `notes` | Free-text |
| `received_at` | Timestamp |

When you add or remove a payment, `invoice.recompute_status()`
automatically updates the invoice status (sent → partial → paid).

---

### `photos` — Attached to property, job, or visit

A photo has exactly one of three parent FKs set: `property_id`, `job_id`,
or `visit_id`. Enforced by a CHECK constraint.

| Field | What it is |
|---|---|
| `id` | Unique number |
| `rel_path` | Path under `/data/photos/` (e.g. `properties/42/abc123.jpg`) |
| `original_filename` | What the user uploaded as |
| `mimetype`, `bytes`, `width`, `height` | Metadata |
| `caption` | Optional |
| `property_id`, `job_id`, `visit_id` | Polymorphic parent — exactly one is set |

Photos are auto-resized on upload to 1600px long-edge JPEG @ q=85
(typically ~300KB from a 5MB phone photo). EXIF rotation is applied so
phone-portrait photos display correctly.

---

## The four "system" tables

### `users` — The operator (you)

Currently always one row. Holds:
- `email`, `password_hash` (Argon2id)
- `display_name` (optional)
- `theme` (dark / amoled / light)
- `last_login_at`

If you ever add a crew member, this table is ready.

---

### `settings` — Singleton key-value store

A flat key → value store for things you'd otherwise need a one-row
config table for.

Currently used for:
- `business_name`, `business_address`, `business_phone`, `business_email`
- `assistant_enabled`, `assistant_model`
- `notify_daily`, `notify_daily_time`, `notify_weekly`, `notify_monthly`,
  `notify_job_day`, `notify_email`, `notify_email_to`

Reads fall back to env-var defaults if the key isn't set.

---

### `audit_log` — The change history

One row per change to a tracked table. Tracked tables:
Client, Property, Job, Visit, Quote, Invoice, LineItem, Payment.

Not tracked: User, Setting, Conversation, Message, Notification, AuditLog
itself, Photo. (These are either internal/operational or — for Setting —
already capture their last-updated time.)

| Field | What it is |
|---|---|
| `id` | Unique number |
| `created_at` | When the change happened |
| `operation` | insert / update / delete |
| `entity_type` | "Client", "Job", etc. |
| `entity_id` | The ID of the row that changed |
| `actor_email` | Your email if the change came from a logged-in request |
| `actor_kind` | user / system / cli |
| `before_json` | Full row snapshot before (for updates and deletes) |
| `after_json` | Full row snapshot after (for inserts and updates) |
| `summary` | One-liner for display ("Job #42 status: scheduled → complete") |

The audit row is added inside the same DB transaction as the change.
So either both succeed or both roll back — the log can't be missing
events or out of sync.

---

### `notifications` — Inbox + email digest content

Each row represents one briefing or reminder.

| Field | What it is |
|---|---|
| `id` | Unique number |
| `kind` | daily_briefing / weekly_briefing / monthly_report / job_day_reminder |
| `title` | Subject line |
| `body_html`, `body_text` | The content |
| `created_at` | When it was generated |
| `sent_email_at` | When (and if) it was emailed |
| `read_at` | When you marked it read (or viewed inbox) |

---

## The two "assistant" tables

### `conversations` and `messages`

Each chat at `/assistant` is one Conversation. Each message in the chat
is one Message row (role: user / assistant / system, content, optional
tool-calls JSON).

You can scroll through old conversations from the assistant index.
Deleting a conversation cascades to its messages.

---

## Money: stored as integer cents, always

We never store money as floating-point. `Float * 100` lies. Every money
column is an `Integer` storing cents:

- `unit_price_cents`, `amount_cents`, etc.

Math uses `Decimal` (Python's decimal arithmetic) with `ROUND_HALF_UP` to
the cent for tax calculations. The conversion happens in
`app/services/money.py` — `dollars_to_cents()` and `cents_to_str()`.

Tax math:
```
subtotal_cents      = sum of all line items
taxable_subtotal_cents = sum of taxable line items only
tax_cents           = round(taxable_subtotal_cents × tax_rate, 0 cents)
total_cents         = subtotal_cents + tax_cents
```

---

## Time zones: stored UTC, rendered local

All timestamps are stored as UTC. Display uses the operator's
`APP_TIMEZONE` env var (default `America/New_York`). Scheduled cron jobs
use that same TZ so the daily briefing fires at 06:30 *your* time.

---

## How relationships cascade on delete

When you delete a row, what happens to its dependents?

| Parent | Child | What happens |
|---|---|---|
| Client | Property | CASCADE — properties go with the client |
| Client | Job | CASCADE |
| Client | Quote | CASCADE |
| Client | Invoice | CASCADE |
| Property | Job | CASCADE — moving a property is rare; if it happens, you delete + recreate |
| Property | Quote / Invoice | CASCADE |
| Property | Photo | CASCADE |
| Job | Visit | CASCADE |
| Job | Photo (via visit) | CASCADE indirectly through Visit |
| Quote | Job (converted_to_job_id) | SET NULL — deleting a quote doesn't kill the job |
| Job | Invoice (job_id) | SET NULL — deleting a job doesn't kill the invoice |
| Invoice | Payment | CASCADE |
| Quote | LineItem | CASCADE |
| Invoice | LineItem | CASCADE |

**Audit log preserves everything regardless** — the full row snapshot
is in `before_json` for every delete. You can always reconstruct.

---

## Migrations: how the schema evolves

The `migrations/versions/` folder has one file per schema version. They
apply in order:

| File | What changed |
|---|---|
| `0001_initial_schema.py` | users, clients, properties, photos |
| `0002_jobs_visits_photo_fks.py` | jobs, visits; photos can attach to jobs/visits |
| `0003_user_theme_and_settings.py` | user.theme; settings key-value table |
| `0004_assistant_and_notifications.py` | conversations, messages, notifications |
| `0005_quotes_invoices_payments.py` | quotes, invoices, line_items, payments |
| `0006_audit_log_and_soft_delete.py` | audit_log table |

Every Railway deploy runs `flask db upgrade` first (in the Procfile's
`release` step) — applies any new migrations automatically.

When changing the schema:
1. Update the model in `app/models/`.
2. Generate a migration: `flask db migrate -m "describe what changed"`
3. Inspect the generated migration file. Edit if needed.
4. Apply: `flask db upgrade`
5. Test, then commit + push.

**Always test migrations on a copy of prod data first** for any
non-trivial change. The audit log + nightly backup mean recovery is
possible from a bad migration, but better to avoid.
