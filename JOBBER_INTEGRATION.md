# Jobber Integration — Deep Dive

This document covers how the CRM pulls data from Jobber for migration.
Two paths: **CSV import** (for the data Jobber's UI exports easily) and
**API sync** (for everything else, when CSV emails aren't arriving).

---

## TL;DR

For migrating off Jobber:
1. **Settings → Import Jobber clients** — upload the CSV from Jobber's
   Clients export. Idempotent re-runs are safe.
2. **Settings → Jobber sync → 🚀 Pull EVERYTHING** — pulls jobs,
   quotes, invoices, payments via OAuth + GraphQL. Same dedup so it
   skips anything already imported.

After the initial migration, both paths can be re-run anytime to pull
new records. Existing records aren't touched.

---

## CSV import path

**When to use:** Jobber's UI lets you export Clients reliably, and the
CSV has all properties on the same row (one row per client × property
combination).

### Flow

```
You: Jobber → Clients → More Actions → Export Clients (CSV emailed to you)
You: Settings → Import Jobber clients → Upload the CSV

App:
  1. Group rows by Jobber client_id (the part before "_" in J-ID)
  2. For each unique client:
       - Find or create the local Client (matched via the
         "[Imported from Jobber, client #<id>]" stamp in notes)
       - Add Property rows for each row's address (auto-fill OH
         county + tax_rate via ZIP)
       - Stamp the Jobber property_id into Property.notes for later
         API sync matching
  3. Skip any clients in the operator-supplied skip list
     (pre-populated with detected dupes + Jacob Wood test entries)
  4. Audit log captures every insert
```

### Deduplication

The script detects probable duplicates **within** a single CSV via:
- Same email (case-insensitive)
- Same name + same phone

Reports them in dry-run mode so you can decide which to skip via the
skip-list field.

For **re-runs**, dedup is by Jobber client_id stamped in notes —
already-imported clients are skipped silently.

### Files

- Importer: `scripts/import_jobber_clients.py` (also reusable as a CLI)
- Web UI: `Settings → Import Jobber clients` (template:
  `app/templates/settings/import_jobber_clients.html`)
- The same `write_clients()` function is reused by the API sync, so
  we don't have two parallel implementations.

---

## API sync path

**When to use:** Jobber's CSV export emails aren't arriving (their email
queue can be slow or broken), or you need data Jobber doesn't expose
neatly via CSV (jobs, quotes, invoices, payments).

### Setup (one-time, ~10 minutes)

1. **Sign in at developer.getjobber.com** with your Jobber account
2. **Open your developer app** (e.g. "Lakewood Original Assistant").
   If you don't have one, create a new app in DRAFT mode — that's enough
   for own-account use.
3. **Set the Callback URL** to your Railway domain + `/jobber/callback`:
   ```
   https://web-production-c8c82.up.railway.app/jobber/callback
   ```
   (Replace with your custom domain if you have one.)
4. **Save the developer app.**
5. **Copy the Client ID and Client Secret.**
6. **Add to Railway env vars:**
   ```
   JOBBER_CLIENT_ID=<from developer page>
   JOBBER_CLIENT_SECRET=<from developer page>
   ```
   Wait for Railway to redeploy (~1 min).
7. **Open the live CRM → Settings → 🔌 Jobber sync (API)**
8. Click **Connect to Jobber** → consent on Jobber's page → redirected back
9. Status flips to **✓ Connected**.

### Sync flow

Click **🚀 Pull EVERYTHING** to run all four syncs in dependency order:

```
1. Clients + properties
   - GraphQL: paginate `clients` connection
   - For each client, extract Client.properties (plain list, NOT a
     Relay connection)
   - Reuses the CSV importer's write_clients()

2. Wait 8 seconds (Jobber rate limit cooldown)

3. Jobs
   - GraphQL: paginate `jobs` connection
   - For each job: match Client by Jobber id (notes lookup),
     match Property by Jobber id (notes lookup), insert Job
   - Status mapping: LATE/TODAY/UPCOMING → scheduled,
     IN_PROGRESS → in_progress, COMPLETED → complete,
     ARCHIVED → canceled

4. Wait 8 seconds

5. Quotes (with line items)
   - GraphQL: paginate `quotes` with nested lineItems { name,
     description, quantity, unitPrice, taxable }
   - Status mapping: DRAFT → draft, AWAITING_RESPONSE → sent,
     APPROVED → accepted, CHANGES_REQUESTED → declined,
     ARCHIVED → expired, CONVERTED → converted

6. Wait 8 seconds

7. Invoices (with line items + per-invoice payments)
   - GraphQL: paginate `invoices` with nested lineItems
   - Note: Invoice uses `propertyIds` (a list of strings), NOT
     `property` (a singular reference). We take the first.
   - Status mapping: DRAFT → draft, AWAITING_PAYMENT → sent,
     PARTIAL → partial, PAID → paid, BAD_DEBT → void
   - For each new invoice: follow-up GraphQL call for paymentRecords
   - Each Payment record: stamp Jobber id in notes for dedup
   - After importing payments: invoice.recompute_status()
```

### Throttle handling

Jobber's API is rate-limited (~2500 points/min default; varies by
endpoint cost). The CRM handles this in three ways:

1. **Pre-call sleep**: every GraphQL call sleeps 0.35s before sending
   — caps sustained throughput around 3 req/sec.
2. **Exponential backoff on `THROTTLED` errors**: 5s, 10s, 20s, 40s,
   60s (capped). Up to 8 retries before giving up.
3. **`Retry-After` header**: if Jobber sends an HTTP 429 with a
   `Retry-After`, we honor it instead of using our backoff schedule.
4. **Cool-down between stages**: `/sync/all` waits 8 seconds between
   jobs/quotes/invoices.
5. **Smaller page sizes**: 25 records per page (instead of 50) reduces
   per-call point cost.

A full sync of ~50 clients / 50 jobs / 50 quotes / 50 invoices takes
**2-4 minutes** with these guards. Trade-off: slower, but reliably
finishes without baby-sitting.

### Idempotency

Every imported record gets a Jobber-ID stamp in its notes field:

| Entity | Stamp pattern | Where stored |
|---|---|---|
| Client | `[Imported from Jobber, client #<id>]` | `client.notes` |
| Property | `[Jobber property #<id>]` | `property.notes` |
| Job | `[Jobber job #<id>]` | `job.notes` |
| Quote | `[Jobber quote #<id>]` | `quote.internal_notes` |
| Invoice | `[Jobber invoice #<id>]` | `invoice.notes` |
| Payment | `[Jobber payment #<id>]` | `payment.notes` |

Re-runs do `WHERE notes LIKE '%[Jobber X #<id>]%'` to find existing
matches and skip them. Run **🚀 Pull EVERYTHING** as many times as you
want — only NEW records get inserted.

### Per-record error handling

Each entity is wrapped in a try/except inside the loop. A single bad
record (malformed data, missing field, etc.) doesn't fail the whole
batch — it's counted in `stats["errors"]` and the rest continue.
Errors are logged + included in the success flash.

---

## Token storage (security)

Jobber OAuth tokens are bearer credentials — anyone who reads the
plaintext can call Jobber's API as you. We encrypt them at rest:

- **Cipher**: Fernet (AES-128-CBC + HMAC-SHA256, RFC-conformant)
- **Key**: derived via HKDF-SHA256 from `SECRET_KEY` with stable salt
  + `"jobber-token-v1"` info string
- **Storage**: single row in the existing `settings` table with key
  `jobber_oauth_token_encrypted`, value = JSON blob with access_token
  + refresh_token + computed `expires_at` epoch seconds
- **Refresh**: `_refresh_if_needed()` checks expiry before every API
  call; auto-refreshes 60s before expiry; preserves the refresh_token
  across refreshes (some providers don't reissue it)
- **Crypto helper refuses to encrypt with the dev SECRET_KEY** — won't
  silently fail-open with a predictable key

If you rotate `SECRET_KEY`, the stored Jobber token becomes unreadable.
Just reconnect via the Connect to Jobber button.

---

## API version pinning

Jobber requires the `X-JOBBER-GRAPHQL-VERSION` header on every call.
Older versions deprecate ~12 months after a successor releases.

We pin to `2025-04-16` (their latest stable as of build). If Jobber
publishes new versions and you want to upgrade, set
`JOBBER_GRAPHQL_VERSION=YYYY-MM-DD` in Railway env vars (don't have to
redeploy code). Check the changelog at
[developer.getjobber.com/docs/changelog](https://developer.getjobber.com/docs/changelog/).

If the version is wrong, Jobber returns HTTP 404 from the GraphQL
endpoint (not 400 — easy to mis-diagnose). The error message from the
sync UI will say so.

---

## Schema gotchas (quirks discovered during build)

These are non-obvious things about Jobber's GraphQL schema. Documenting
them here so future-you knows.

| Field | Quirk |
|---|---|
| `Client.properties` | Plain `[Property!]` list, NOT a Relay-style `PropertyConnection` with `nodes { ... }`. Don't wrap in `nodes`. |
| `Invoice.property` | Doesn't exist — use `propertyIds` (list of String). An invoice can technically span multiple properties; we take the first. |
| `LineItem.unitCost` | Doesn't exist — use `unitPrice`. Both Quote and Invoice line items. |
| Money fields | Returned as **floats in dollars** (e.g. `45.50`), not integer cents. We convert via `Decimal + ROUND_HALF_UP`. |
| Date fields | ISO 8601 strings (`2025-04-16T12:34:56Z`). We strip the timezone for storage as UTC-naive. |

---

## Routes

| Route | Method | Purpose |
|---|---|---|
| `/jobber` | GET | Status page — Connect button or sync buttons depending on connection |
| `/jobber/connect` | POST | Generate OAuth state, redirect to Jobber's authorize page |
| `/jobber/callback` | GET | Receive code, exchange for token, store encrypted (CSRF-exempt; verifies state from session) |
| `/jobber/sync/clients` | POST | Pull clients + properties |
| `/jobber/sync/jobs` | POST | Pull jobs |
| `/jobber/sync/quotes` | POST | Pull quotes (with line items) |
| `/jobber/sync/invoices` | POST | Pull invoices (with line items + nested payments) |
| `/jobber/sync/all` | POST | Run all four in dependency order with cool-downs |
| `/jobber/disconnect` | POST | Wipe the stored token |

---

## Files

| File | What it does |
|---|---|
| `app/jobber/routes.py` | All Jobber routes |
| `app/services/jobber.py` | OAuth + GraphQL client + token persistence |
| `app/services/jobber_sync.py` | Per-entity sync functions (jobs/quotes/invoices/payments) |
| `app/utils/crypto.py` | Fernet + HKDF helpers for token encryption |
| `scripts/import_jobber_clients.py` | CSV importer (also reused by API sync via `write_clients`) |
| `app/templates/jobber/index.html` | Status page UI |
| `app/templates/settings/import_jobber_clients.html` | CSV upload UI |

---

## What this integration deliberately does NOT do

- **No bidirectional sync.** This is a one-way pull, designed for
  migration. We don't push changes back to Jobber.
- **No incremental sync via webhooks.** Each "Pull X" reads everything
  fresh and uses the dedup pattern to skip already-imported. Simpler
  than maintaining last-sync timestamps.
- **No write operations against Jobber.** OAuth scope is read-only
  (`read_clients read_jobs read_quotes read_invoices`). We can't
  accidentally clobber Jobber's data.
- **No long-running background sync job.** The button initiates a
  request that runs in the foreground (with a "Pulling…" indicator).
  Takes 2-4 min for a full sync. If you need to migrate larger volumes
  (>500 clients), a background-task pattern would be worth adding.
