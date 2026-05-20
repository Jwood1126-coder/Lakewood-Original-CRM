# Jobber Core Parity Roadmap

> **Status:** Draft v1 — based on a read-only audit of `main` as of 2026-05-20.
> Update this document as issues are landed; treat each section heading as the source of truth for scope and acceptance criteria when filing GitHub issues.

---

## 1. Executive Decision

### What "Core parity" means

Lakewood Original CRM must replace **Jobber Core** (single-user tier) for a one-person field-service operation. Concretely, before we cancel the Jobber subscription, the app must support the full **quote-to-cash** lifecycle:

| Capability | Required for Core parity |
|---|---|
| Single operator user | Yes (already present) |
| Client hub / customer portal | Yes — token-scoped, read-only-ish |
| Online requests (lead intake form) | Yes (intake exists; harden CORS) |
| Online booking (customer-selected slot) | Yes — basic only |
| Unlimited quotes / jobs / invoices | Yes (no quotas) |
| Customer online quote approval | **Yes — missing today** |
| One-off jobs | Yes (already present) |
| Recurring jobs / visits | **Yes — missing today** |
| Invoices, online card/debit payments | **Yes — missing today** |
| Deposits & tips | **Yes — missing today** |
| Lead management | Yes (intake → client/property) |
| Basic customer details | Yes (already present) |

### What is explicitly **out of scope** for Core parity (defer)

These map to Jobber Connect/Grow/Plus and should be tracked but **not block** Jobber cancellation:

- Multi-user roles, crews, time tracking, GPS
- Two-way SMS conversations
- Custom automation builder / workflow rules
- Route optimization, advanced dispatch boards
- Job costing, profitability reports
- QuickBooks Online / Zapier sync (unless the user actively uses it today)
- Marketing automation, review requests, referral programs
- AI/assistant features beyond what already ships

If a Core capability above forces design decisions that would block these later (e.g., recurring jobs schema), call it out in the issue's "Future-proofing" note — don't build them now.

---

## 2. Milestone Roadmap (Sequenced)

Milestones are **sequential**; each one is shippable and reduces risk for the next. Do not start a later milestone before its predecessor is in production.

| # | Milestone | Goal | Exit criteria |
|---|---|---|---|
| **M0** | **Stabilize** | Stop the bleeding: production no longer crashes or times out on known paths. | Settings > Notifications loads, `/jobber/sync/all` returns within deploy timeout, intake CORS works from production site without code edits, transition guards prevent invalid quote states. |
| **M1** | **Migration-safe import** | Re-importable, idempotent Jobber data with provenance. | `external_id` columns on Client/Property/Quote/Invoice/Job/Payment; imports use `received_at` from Jobber payload (not `utcnow()`); tax is snapshotted at quote send time; soft-delete columns in place; re-running import is a no-op. |
| **M2** | **Customer portal — quote approval** | Customers can view and approve quotes online via a public token URL. | `/q/<token>` route serves a customer-safe quote page; "Approve" button transitions quote to `accepted` with audit trail; email links point to public URL. |
| **M3** | **Invoice payment / deposits / tips** | Customers can pay online (card/debit). Deposits and tips supported. | `/i/<token>` invoice page with Stripe Checkout or Payment Link; webhook records `Payment` rows; deposit-on-quote and tip-on-invoice flows live; receipts emailed. |
| **M4** | **Recurring jobs + basic online booking** | Jobs can repeat on a schedule; customers can request a slot. | `JobSchedule`/`Visit` model emits visits; booking page accepts a date/window from a fixed set of slots and creates a `Request` (lead) tied to a client. |
| **M5** | **Products / services catalog** | Quoting uses a reusable price list. | `Service`/`Product` model; quote line items can reference a catalog entry; price changes don't retroactively alter sent quotes (snapshot). |
| **M6** | **Data export + cutover** | Full JSON/CSV export of every entity. Sign-off checklist passes. | `/admin/export` produces a downloadable archive of all data; spot-checks vs Jobber match; Jobber subscription canceled with a documented rollback path. |

---

## 3. Prioritized Issue Backlog

Each entry below is shaped for direct paste into GitHub Issues. Priorities: **P0** (production-breaking), **P1** (blocks Core parity), **P2** (Core parity quality), **P3** (nice-to-have / post-cancel). Effort: **S** (<½ day), **M** (½–2 days), **L** (3–5 days), **XL** (>1 week).

---

### M0 — Stabilize

#### [P0][bug] Settings > Notifications crashes because `notify_email_to` lives on `ImportClientsForm`

- **Priority:** P0
- **Type:** bug
- **Effort:** S
- **Rationale:** `app/settings/forms.py:135` defines `notify_email_to` inside `ImportClientsForm` instead of `NotificationForm`. Rendering the Notifications settings page raises an `AttributeError` (or silently drops the field), and saving never persists the email recipients.
- **Affected:** `app/settings/forms.py`, `app/settings/routes.py`, `app/templates/settings/notifications.html` (or equivalent).
- **Implementation approach:**
  1. Move the `notify_email_to` field out of `ImportClientsForm` and into `NotificationForm`.
  2. Remove the duplicate `submit = SubmitField("Save notification preferences")` from `ImportClientsForm`.
  3. Confirm the route binds the right form to the right template.
- **Dependencies:** none.
- **Acceptance criteria:**
  - Settings > Notifications renders without error on a clean DB.
  - Saving an email value persists and round-trips.
  - Import Clients form still submits as before and no longer surfaces the email field.
- **Tests:**
  - Add a smoke test that `GET /settings/notifications` returns 200.
  - Add a form test that submitting `notify_email_to=foo@bar` saves to `Setting`.
- **Migration:** none.

#### [P0][bug] `/jobber/sync/all` exceeds Railway/gunicorn timeout

- **Priority:** P0
- **Type:** bug / infra
- **Effort:** M
- **Rationale:** The sync route runs synchronously inside the web worker. `Procfile` declares `--timeout 600` but `railway.json` overrides with `--timeout 120`, so Railway kills the worker partway. Symptom: half-imported state and 502s.
- **Affected:** `app/jobber/routes.py:226` (`/sync/all`), `Procfile`, `railway.json`.
- **Implementation approach:**
  - **Short-term:** Align `Procfile` and `railway.json` to the **same** timeout. Pick the lower one Railway will accept (e.g., 300s) and reduce sync batch size so a single request fits.
  - **Right answer:** Move sync to a background job. Two acceptable options for a 1-user app:
    - APScheduler + a small in-process job queue persisted to SQLite (`apscheduler.jobstores.sqlalchemy`).
    - A separate Railway worker process (`worker:` in Procfile) reading a tiny `jobs` table.
  - Make the route enqueue a job and return immediately with a job id; expose `/jobber/sync/status/<id>`.
- **Dependencies:** none for short-term; M1 benefits from this being in place.
- **Acceptance criteria:**
  - Calling `/jobber/sync/all` returns within 5s with a job id.
  - Job progress is observable from the UI.
  - Re-running while a job is in flight is a no-op (or queues behind it).
- **Tests:** unit test for enqueue dedup; integration test that the worker drains a synthetic job.
- **Migration:** add `jobber_sync_runs` table (id, started_at, finished_at, status, stats_json).

#### [P0][security] Intake CORS hardcoded to a single origin

- **Priority:** P0
- **Type:** bug / config
- **Effort:** S
- **Rationale:** `app/intake/routes.py:237` hardcodes `Access-Control-Allow-Origin: https://lakewoodoriginal.com`. Any future marketing site, staging domain, or local dev breaks silently.
- **Implementation approach:** Read allowed origins from `INTAKE_ALLOWED_ORIGINS` env var (comma-separated). Echo back the request `Origin` only if it's in the allowlist; otherwise omit the header. Keep `Vary: Origin`.
- **Acceptance criteria:** Allowed origins from env load correctly; unlisted origin gets no ACAO header; preflight `OPTIONS` works.
- **Tests:** unit test the header decision function with several origins.
- **Migration:** none. Update `.env.example`.

#### [P0][bug] `quote.change_status` allows any → any transition

- **Priority:** P0
- **Type:** bug
- **Effort:** S
- **Rationale:** `app/quotes/routes.py:211` flips status and timestamps without guarding the FSM. A user can move a `declined` quote to `accepted`, or re-send an already accepted one, corrupting the audit trail.
- **Implementation approach:** Define an allowed-transitions map (e.g., `draft→sent`, `sent→accepted|declined`, `accepted→converted`, terminal: `converted`, `declined`). Reject disallowed moves with 409 and an audit log entry.
- **Acceptance criteria:** Invalid transitions return an error and do not mutate state; valid transitions still work.
- **Tests:** parametrized test over the transition matrix.
- **Migration:** none.

---

### M1 — Migration-safe import

#### [P1][bug] Imported Jobber payments use `utcnow()` for `received_at`

- **Priority:** P1
- **Type:** bug / data quality
- **Effort:** S
- **Rationale:** When a Jobber payment is imported, its `received_at` is set to the moment of import, not the real payment date. This breaks revenue reports and any reconciliation against bank deposits.
- **Affected:** Jobber sync code path that creates `Payment` rows (search for `utcnow` near payment creation).
- **Implementation approach:** Map the Jobber payment's `paymentDate`/`receivedAt`/`createdAt` (whichever Jobber actually returns — confirm in `JOBBER_INTEGRATION.md`) into `Payment.received_at`. Fall back to `utcnow()` **only** if absent, and log a warning.
- **Acceptance criteria:** Re-running import overwrites historical `received_at` with the Jobber value once; subsequent runs are idempotent.
- **Tests:** import fixture with known dates; assert exact `received_at`.
- **Migration:** one-time backfill script that walks existing imported payments and corrects `received_at` from the cached Jobber payload (the recent commit `c78a073` already captures custom fields and `ended_at` — extend it).

#### [P1][feature] Add `external_id` / source columns on all imported entities

- **Priority:** P1
- **Type:** feature / migration
- **Effort:** M
- **Rationale:** Without a stable foreign key to Jobber ids, repeat imports create duplicates and we cannot reconcile against Jobber after cancellation.
- **Affected models:** `Client`, `Property`, `Quote`, `Invoice`, `Job`, `Visit`, `Payment`, `LineItem` (where applicable).
- **Implementation approach:**
  - Add `external_source` (`'jobber'|'manual'|...`) and `external_id` (string) columns. Unique index on `(external_source, external_id)`.
  - Update importers to upsert on `(source, id)` instead of email/name matching.
- **Acceptance criteria:** Running import twice on the same dataset produces 0 inserts the second time; updates only touch changed fields.
- **Tests:** golden-file import + re-import diff is empty.
- **Migration:** Alembic migration adds nullable columns, then backfills from any existing `jobber_id` fields, then creates the unique index.

#### [P1][feature] Soft delete (`deleted_at`) on core entities

- **Priority:** P1
- **Type:** feature
- **Effort:** M
- **Rationale:** Hard deletes break audit trails, payment history, and Jobber re-import. A 1-user CRM should never lose a client by misclick.
- **Affected models:** `Client`, `Property`, `Quote`, `Invoice`, `Job`, `Payment`, `Photo`.
- **Implementation approach:**
  - Add `deleted_at: datetime | None` column.
  - Default ORM queries filter `deleted_at IS NULL` via a SQLAlchemy event or explicit query helper. Keep a `with_deleted()` escape hatch for admin/export.
  - Delete buttons set `deleted_at`; add a "Restore" affordance on detail pages.
- **Acceptance criteria:** Deleted records do not appear in normal lists; export still includes them with a `deleted_at` field.
- **Tests:** delete-then-list returns empty; delete-then-restore returns the record.
- **Migration:** add `deleted_at` columns; no backfill.

#### [P1][bug] Quote tax recomputed from current property tax rate

- **Priority:** P1
- **Type:** bug / data integrity
- **Effort:** S
- **Rationale:** `app/models/quote.py:109` (`effective_tax_rate`) falls back to `self.prop.tax_rate` at read time. If the property's tax rate changes after a quote is sent, totals silently shift — including on already-accepted quotes. This is also an accounting risk.
- **Implementation approach:**
  - On `quote.status` transitioning to `sent` (or on first save), snapshot the effective tax rate into `tax_rate_snapshot` on the quote.
  - Update `effective_tax_rate` to prefer: `tax_rate_override` → `tax_rate_snapshot` → `property.tax_rate`.
  - Do the same for invoices generated from a quote — copy the quote's snapshot.
- **Acceptance criteria:** Changing a property's tax rate after a quote is sent does not change the quote's total or any derived invoice.
- **Tests:** unit test that flips property rate post-send and asserts quote total unchanged.
- **Migration:** add `tax_rate_snapshot` to `Quote` and `Invoice`; backfill snapshots from the property's current rate for legacy rows and flag with a `tax_snapshot_backfilled_at` audit log entry.

#### [P2][bug] HEIC upload handling

- **Priority:** P2
- **Type:** bug
- **Effort:** M
- **Rationale:** iPhone-captured photos are HEIC by default and currently fail or render as broken images. For a field-service CRM, this is a daily papercut.
- **Implementation approach:**
  - Add `pillow-heif` to `requirements.txt`; register the opener on app start.
  - On upload, convert HEIC → JPEG (quality 85) before storage. Keep the original in object storage if disk allows, but serve only the JPEG.
  - Reject `.heic` mimetypes only if conversion fails; otherwise transparent.
- **Acceptance criteria:** Uploading an iPhone HEIC produces a viewable photo with EXIF orientation respected.
- **Tests:** unit test the converter with a sample HEIC fixture (small one in `tests/fixtures/`).
- **Migration:** none.

---

### M2 — Customer portal: quote approval

#### [P1][feature] Public token route `/q/<token>` with customer-safe template

- **Priority:** P1
- **Type:** feature
- **Effort:** L
- **Rationale:** `Quote.token` already exists (`app/models/quote.py:56`) but there is no public route that uses it. The single biggest gap vs Jobber Core today.
- **Implementation approach:**
  - New blueprint `app/portal/` (no `@login_required`).
  - Route `GET /q/<token>` looks up the quote by token (constant-time compare), returns 404 on miss or on `deleted_at IS NOT NULL`.
  - Customer-safe template — strip admin fields (margins, internal notes), show: business header, line items, totals, tax (from snapshot), terms, expiry, Approve / Decline buttons.
  - `POST /q/<token>/approve` requires a typed name (e-signature stand-in), records IP/UA, transitions status with the FSM from the M0 fix, writes `AuditLog`.
  - Throttle by IP (e.g., `Flask-Limiter`) — 10/min is generous.
  - `Cache-Control: no-store` on all portal responses.
- **Affected:** new blueprint, register in `app/__init__.py`, share `customer_safe_quote.html` partial with quote PDF if it exists.
- **Acceptance criteria:**
  - Quote email link opens a non-authenticated, mobile-friendly view.
  - Approve writes `accepted_at`, captures signer name, and is replay-safe (second click is a no-op or 409).
  - Decline captures an optional reason.
- **Tests:** route test for 404 on bad token; approve flow; double-approve idempotency; throttling kicks in.
- **Migration:** add `accepted_by_name`, `accepted_ip`, `declined_reason` to `Quote`.

#### [P1][feature] Send quote email links use the public URL

- **Priority:** P1
- **Type:** feature
- **Effort:** S
- **Rationale:** Approval route is useless if emails still point to the authenticated admin URL.
- **Implementation approach:** Use `url_for('portal.view_quote', token=...., _external=True)` in the quote send email. Add a "Copy customer link" button on the quote detail page for the operator to paste into texts.
- **Acceptance criteria:** Email body contains the public URL; clicking from a logged-out browser works.
- **Tests:** template rendering test asserting the public URL is in the body.

#### [P2][feature] Token rotation on demand

- **Priority:** P2
- **Effort:** S
- **Rationale:** If a customer forwards a link or it leaks, the operator needs a "regenerate link" affordance. Old token returns 410.
- **Migration:** add `token_rotated_at` to `Quote`.

---

### M3 — Invoice payment, deposits, tips

#### [P1][feature] Public invoice route `/i/<token>` + online payment

- **Priority:** P1
- **Type:** feature
- **Effort:** XL
- **Rationale:** Core parity requires online card/debit payment with deposits and tips. `Invoice.token` exists; no public route or payment integration does.
- **Implementation approach (Stripe-first; cheapest path):**
  - **MVP path — Stripe Payment Links:** generate a one-off Payment Link per invoice from the API, store `external_payment_link_id` on the invoice. Customer clicks Pay → Stripe handles the rest. Listen for `checkout.session.completed` and `payment_intent.succeeded` webhooks to create a `Payment` row with `external_source='stripe'` and `external_id=<intent_id>`.
  - **Better path — Stripe Checkout from our portal:** `/i/<token>/pay` calls `stripe.checkout.Session.create` with `payment_intent_data.metadata.invoice_id`. Success URL routes back to `/i/<token>?paid=1`. Same webhook handling.
  - **Tips:** include an optional `tip` line item or use Stripe's `payment_intent_data.application_fee_amount` only if a Connect account; otherwise model tip as a separate `Payment` row component or a positive adjustment on the invoice. Simpler: a tip field on the portal that adjusts the Stripe amount before redirect, persisted to `Payment.tip_cents`.
  - **Deposits:** see next issue.
  - **Reconciliation:** webhook is the source of truth; UI shows "Awaiting Stripe confirmation" until webhook arrives.
- **Affected:** `app/portal/` (new), `app/models/payment.py` (add `external_source`, `external_id`, `tip_cents`, `fees_cents`), webhook endpoint `POST /webhooks/stripe`.
- **Acceptance criteria:**
  - Customer can pay an invoice in test mode end-to-end.
  - Webhook is idempotent (replay of same event does not duplicate `Payment`).
  - Receipt email is sent on success.
  - Failed payments surface a clear message and do not advance invoice status.
- **Tests:** webhook unit tests with sample Stripe payloads; signature verification test; idempotency test by replaying.
- **Migration:** new columns on `Payment`; `stripe_events` table for idempotency (event id, processed_at).
- **Config:** `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PUBLISHABLE_KEY` in env. Update `.env.example`.

#### [P1][feature] Deposits on quote acceptance

- **Priority:** P1
- **Type:** feature
- **Effort:** L
- **Rationale:** Core supports requiring a deposit at quote approval. Many service businesses depend on this.
- **Implementation approach:**
  - Add `deposit_required_cents` and `deposit_percent` (one of them, not both) to `Quote`.
  - On `/q/<token>/approve`, if a deposit is required, route to a Stripe Checkout for the deposit amount before marking the quote `accepted`. Quote moves to `pending_deposit` then `accepted` after webhook.
  - The deposit creates a `Payment` row linked to the future invoice (or stored on `Quote` and transferred when the invoice is generated).
- **Acceptance criteria:** Quote with a required deposit cannot be approved without paying; deposit appears as a credit on the generated invoice.
- **Tests:** approval-with-deposit flow integration test.
- **Migration:** new columns on `Quote`; new status values.

#### [P1][feature] Tips on invoice payment

- **Priority:** P1
- **Type:** feature
- **Effort:** M
- **Rationale:** Core supports tipping at invoice pay time. Simple to add once payments work.
- **Implementation approach:** On the portal pay page, show a tip selector (15/18/20/custom). Tip flows into Stripe as part of the charged amount; on webhook, split into `Payment.amount_cents` (invoice portion) and `Payment.tip_cents`. Reports show tips separately from revenue.
- **Acceptance criteria:** Tips appear as a distinct line in payment history; do not affect invoice balance owed.
- **Tests:** end-to-end with a $5 tip on a $100 invoice → invoice fully paid, $5 attributed to tips.

---

### M4 — Recurring jobs + basic online booking

#### [P1][feature] Recurring jobs / visits model

- **Priority:** P1
- **Type:** feature
- **Effort:** XL
- **Rationale:** Lawn-care, cleaning, and pool-service businesses depend on recurring schedules. Core supports this; today the app does not.
- **Implementation approach:**
  - Introduce `JobSchedule` (parent) and `Visit` (concrete dated occurrence). `JobSchedule` holds rrule-like fields: `frequency` (weekly/biweekly/monthly), `interval`, `byweekday`, `start_date`, `end_date_or_count`.
  - Use the `python-dateutil` rrule for expansion; store a horizon (e.g., next 90 days) of materialized `Visit` rows so the calendar UI is fast and edits to a single visit don't affect siblings.
  - A nightly APScheduler task (re-using infra from M0 `/jobber/sync/all` fix) extends the horizon.
  - Edits: "this visit only" vs "this and future" vs "all" — match Google Calendar semantics.
- **Affected:** new models, `app/jobs/` routes/templates, calendar view.
- **Acceptance criteria:** A weekly recurring job for 12 weeks produces 12 visits visible on the schedule; editing a single visit detaches it from the schedule.
- **Tests:** rrule expansion unit tests; "edit this and future" behavior test.
- **Migration:** new tables; backfill existing one-off jobs as `JobSchedule` with `frequency=none, count=1` if it simplifies the code.
- **Future-proofing note:** keep the door open for crew assignment later by referencing `assignee_user_id` (nullable, defaults to the single user) — don't model it now.

#### [P2][feature] Basic online booking

- **Priority:** P2
- **Type:** feature
- **Effort:** L
- **Rationale:** Core includes "online booking" — but the user is one person and probably doesn't want random self-serve scheduling. Implement as **request a time window** (lead intake with a preferred slot), not real-time calendar booking.
- **Implementation approach:** Extend the intake form (`app/intake/`) with a "preferred service window" selector showing a fixed set of slots (e.g., next 2 weeks, AM/PM). Stores on the `Request`/lead. Operator confirms in-app, which converts to a `Visit`.
- **Acceptance criteria:** Customer can submit a preferred date/time; operator sees it on the request; operator-confirmed slot becomes a visit.
- **Tests:** intake form submission with slot persists; conversion creates a visit.
- **Migration:** add `preferred_slot_start`, `preferred_slot_end` to the intake/request model.

---

### M5 — Products / services catalog

#### [P2][feature] `Service` / `Product` catalog

- **Priority:** P2
- **Type:** feature
- **Effort:** L
- **Rationale:** Today quote line items are free-form. A catalog speeds up quoting and ensures pricing consistency. Required if the user has more than ~5 standard services.
- **Implementation approach:**
  - New `Service` model: name, description, default_unit_price_cents, default_quantity, taxable (bool), active (bool).
  - `LineItem` gains nullable `service_id` FK. **Crucially, line items still store their own description, qty, price, and taxable at write time — the catalog is a template, not a live link.** This prevents historical quotes/invoices from shifting when catalog prices change.
  - Quote/invoice editor: "Add from catalog" picker; selecting a service fills the line item but leaves it editable.
- **Acceptance criteria:** Changing a catalog price does not alter existing quotes/invoices.
- **Tests:** unit test that updating `Service.default_unit_price_cents` leaves existing `LineItem.unit_price_cents` untouched.
- **Migration:** new `services` table; nullable `service_id` on `line_items`.

---

### M6 — Data export + cutover

#### [P1][feature] Full data export (JSON + CSV bundle)

- **Priority:** P1
- **Type:** feature
- **Effort:** M
- **Rationale:** We will not cancel Jobber until we have a tested, downloadable, complete export of Lakewood CRM data. This is also the disaster-recovery story.
- **Implementation approach:**
  - `GET /admin/export` (auth required) streams a ZIP containing:
    - `clients.json`, `properties.json`, `quotes.json`, `invoices.json`, `jobs.json`, `visits.json`, `payments.json`, `line_items.json`, `photos_manifest.json`, `audit_log.json`, `settings.json`.
    - Mirror CSVs for the big tables.
    - `README.txt` with schema version and timestamp.
  - Include soft-deleted records with `deleted_at` set.
  - Photos: include URLs and checksums in the manifest; provide a separate "Download all photos" zip endpoint (or use object-storage URLs).
- **Acceptance criteria:** A fresh import of the exported JSON into a clean DB reproduces the same totals (count per entity, sum of payments, etc.).
- **Tests:** round-trip test on a small fixture dataset.
- **Migration:** none.

#### [P1][checklist] Pre-cancel cutover validation

- **Priority:** P1
- **Type:** checklist
- **Effort:** M
- **Rationale:** Final guardrail before pulling the Jobber plug. See §5.

---

### Post-Core (P3, optional)

- **Two-way SMS** (Twilio inbound webhook → `Conversation`).
- **QuickBooks Online sync** (only if the user actually uses QBO today).
- **Automated review requests** post-invoice-payment.
- **Route optimization** (defer; not Core).
- **Reports**: A/R aging, revenue by service, repeat-customer rate.

---

## 4. Technical Implementation Notes (Flask / SQLite / Railway)

### 4.1 Public token routes

- Put them in a separate blueprint `app/portal/` with **no** `@login_required` decorator.
- Use `secrets.compare_digest` (or just SQLAlchemy `==` since tokens come from `secrets.token_urlsafe`) — never trust user-supplied length or characters.
- Always return 404 (not 403) on unknown/expired token to avoid leaking existence.
- Set `Cache-Control: no-store, max-age=0` and `X-Robots-Tag: noindex, nofollow` on every portal response.
- Rate-limit by IP using `Flask-Limiter`; persist counters in the same DB.

### 4.2 Customer-safe templates

- Inherit from a `portal/base.html` that does **not** include the admin nav.
- Never render `internal_notes`, `cost_cents`, audit log, or other operator-only fields. Codify this with a `quote.to_customer_dict()` and `invoice.to_customer_dict()` method so templates can't accidentally pull a wrong field.
- All money is rendered from snapshotted fields (see tax snapshot in M1), never recomputed at view time.

### 4.3 Stripe integration

- Use **Payment Links** for MVP (less code, no PCI scope concerns). Move to **Checkout Sessions** for tips/deposits which need dynamic amounts.
- Always verify webhook signatures with `stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)`.
- Idempotency: store every processed `event.id` in a `stripe_events` table; check before processing.
- Test mode keys live in dev/staging env; prod keys only on Railway prod.
- Stripe webhook endpoint must be public — no auth — but signature verification is mandatory.

### 4.4 Background sync

- Single-process app with gunicorn `--workers 1` can run **APScheduler** in-process with a SQLAlchemy job store. Avoid threading the scheduler with multiple workers (locking pitfalls).
- For longer or beefier tasks, add a Railway `worker:` process in the Procfile that runs `python -m app.worker`. Use the same `data/app.db` (Railway shared volume) or, ideally, move off SQLite for prod (see 4.8).
- The sync runner must be **resumable**: persist last-cursor per resource so a crash mid-run picks up.

### 4.5 `external_id` / provenance fields

- Pattern on every imported model:
  ```python
  external_source: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
  external_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
  __table_args__ = (UniqueConstraint("external_source", "external_id", name="uq_<table>_external"),)
  ```
- Importers always upsert on `(external_source, external_id)`. Manual records have `external_source IS NULL`.

### 4.6 Tax snapshots

- Snapshot at the moment a quote transitions to `sent`. After that, only `tax_rate_override` can change the rate, and only by an explicit operator action that should write an audit log entry.
- Invoices inherit the tax rate from their source quote, not from the property.

### 4.7 Recurring schedule model

- Don't reinvent rrule. Use `python-dateutil`'s `rrule` + `rruleset` for expansion. Persist the **rule fields** (frequency, interval, byweekday, start, end/count) — not the rrule string — so they're queryable.
- Materialize `Visit` rows on a rolling 90-day horizon; let APScheduler extend nightly.
- "Edit this only" detaches the visit from the schedule (set `Visit.detached_from_schedule_at`); "Edit all future" splits the schedule into two (close the old, start a new from this date).

### 4.8 SQLite on Railway

- SQLite is fine for one user, but Railway containers are ephemeral. Confirm the DB is on a **persistent volume** (or `DATABASE_URL` points at a managed Postgres). If on a volume, ensure backups (a nightly `sqlite3 .backup` to object storage).
- Long-term: migrate to Postgres before adding background workers, before adding Stripe webhook concurrency, and before exposing public portal routes that might thundering-herd on launch day. The existing `app/__init__.py` already skips SQLite-only pragmas on other dialects (`e44648c`), so the codebase is dialect-aware.

### 4.9 Full data export

- Stream the ZIP using `zipstream-ng` or Python's `zipfile` in append mode to avoid loading everything in memory.
- Include a `schema_version` field per record so future importers can adapt.
- For photos, prefer linking to URLs (with HMAC-signed expiring URLs if private) rather than embedding bytes — keeps the export small and the photos durable.

### 4.10 Safe cutover validation

- Run import twice into a fresh staging DB; diff. Expected diff: zero.
- Spot-check 10 random clients, 10 random invoices, total revenue YTD, total A/R against Jobber's reports. All must match within rounding.
- Send a real test quote and a real test invoice to the operator's own email; click through both portals from a fresh browser profile.

---

## 5. Release Sequencing / Pre-Cancel Checklist

**Do not cancel Jobber until every box below is checked.**

### Code & data

- [ ] M0 complete (Notifications fix, sync timeout, CORS env, quote FSM)
- [ ] M1 complete (`external_id`, payment dates, tax snapshots, soft delete)
- [ ] M2 complete (public quote portal + approval)
- [ ] M3 complete (online invoice payment via Stripe, deposits, tips, webhooks verified in prod)
- [ ] M4 complete (recurring jobs working end-to-end for at least one real job)
- [ ] M6 export endpoint produces a clean, round-trippable archive

### Operational

- [ ] Stripe live keys configured; one real $1 payment processed end-to-end
- [ ] Email deliverability verified (SPF/DKIM/DMARC on the sending domain)
- [ ] Backups: nightly DB backup landing in object storage, retention ≥ 30 days
- [ ] Disaster recovery dry run: restore yesterday's backup into a fresh Railway env and confirm app boots
- [ ] All active Jobber quotes either accepted/declined or re-issued from Lakewood
- [ ] All open Jobber invoices closed or migrated to Lakewood with a customer-visible explanation
- [ ] At least 2 consecutive weeks of recurring visits successfully run from Lakewood without Jobber as a backstop

### Documentation

- [ ] `README.md` and `JOBBER_INTEGRATION.md` updated to reflect post-cancellation state
- [ ] Customer-facing comms drafted: "We've moved to our own portal — here's your new link"
- [ ] This roadmap doc updated: each milestone section marked complete or its remaining gaps acknowledged

### Rollback plan

- [ ] Documented procedure to re-enable Jobber within 30 days of cancellation (Jobber's reactivation policy permitting)
- [ ] Last full Jobber CSV/PDF export archived in object storage
- [ ] Lakewood DB backup snapshot tagged `pre-cutover-YYYY-MM-DD`

---

## 6. Living-document note

This roadmap is based on a **read-only audit** of `main` as of 2026-05-20. It is not a contract: as issues land, edit the relevant section to reflect what actually shipped (and link the merged PR). When a milestone exit criterion changes, change it here first, then in the GitHub issue, then in the code. Stale roadmaps are worse than no roadmap.

When in doubt, the priority order is: **don't lose customer data → don't lose customer money → don't lose customer trust → ship features.**
