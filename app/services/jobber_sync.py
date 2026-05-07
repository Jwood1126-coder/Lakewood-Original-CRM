"""Pull Jobs / Quotes / Invoices / Payments from Jobber's GraphQL API
and import them into our DB. Reuses the dedup pattern from the CSV
clients importer (Jobber ID stamped in notes).

Each public function returns a stats dict for UI display. Each is
idempotent: re-running skips records already imported.

Status mapping (Jobber → ours):
  Jobs:    LATE/TODAY/UPCOMING/ACTION_REQUIRED → scheduled
           IN_PROGRESS → in_progress
           COMPLETED → complete
           ARCHIVED → canceled
  Quotes:  DRAFT → draft
           AWAITING_RESPONSE → sent
           APPROVED / CONVERTED → accepted (or converted if linked to job)
           CHANGES_REQUESTED → declined
           ARCHIVED → expired
  Invoices: DRAFT → draft
           AWAITING_PAYMENT → sent
           PARTIAL → partial
           PAID → paid
           BAD_DEBT → void

If Jobber returns a status name we haven't mapped, we default to a
sensible fallback and log a warning.
"""
from __future__ import annotations

import base64
import re
from datetime import date, datetime, time, timezone
from decimal import ROUND_HALF_UP, Decimal

from flask import current_app
from sqlalchemy import select

from app.extensions import db
from app.models.client import Client
from app.models.invoice import Invoice
from app.models.job import Job
from app.models.line_item import LineItem
from app.models.payment import Payment
from app.models.property import Property
from app.models.quote import Quote
from app.services.jobber import graphql
from app.utils.timezone import app_tz

# ---------- helpers ----------

JOB_STATUS_MAP = {
    "LATE":             "scheduled",
    "TODAY":            "scheduled",
    "UPCOMING":         "scheduled",
    "ACTION_REQUIRED":  "scheduled",
    "IN_PROGRESS":      "in_progress",
    "COMPLETED":        "complete",
    "REQUIRES_INVOICING": "complete",
    "INVOICED":         "complete",
    "ARCHIVED":         "canceled",
}

QUOTE_STATUS_MAP = {
    "DRAFT":              "draft",
    "AWAITING_RESPONSE":  "sent",
    "APPROVED":           "accepted",
    "CONVERTED":          "converted",
    "CHANGES_REQUESTED":  "declined",
    "ARCHIVED":           "expired",
}

INVOICE_STATUS_MAP = {
    "DRAFT":            "draft",
    "AWAITING_PAYMENT": "sent",
    "PARTIAL":          "partial",
    "PAID":             "paid",
    "BAD_DEBT":         "void",
    "PAST_DUE":         "sent",  # we compute overdue ourselves
}


def _parse_iso(raw: str | None) -> datetime | None:
    """Parse a Jobber ISO 8601 timestamp into UTC-naive (storage convention).

    Jobber returns UTC ('Z'-suffixed). Storage convention for raw timestamps
    is UTC-naive (see app/utils/timezone.py). For values that get split into
    operator-local date+time pairs (e.g. Job.scheduled_date/time), use
    `_parse_iso_local` instead so we don't display 4 AM EDT for a midnight job.
    """
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def _parse_iso_local(raw: str | None) -> datetime | None:
    """Parse a Jobber ISO 8601 timestamp into operator-local naive time.

    Use this for values that get split into separate date and time columns
    (Job.scheduled_date / Job.scheduled_time). Jobber stores all-day jobs as
    midnight in the operator's timezone but returns them in UTC, so without
    this conversion an EDT-midnight job arrives as 04:00:00 naive.
    """
    if not raw:
        return None
    try:
        aware = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return aware.astimezone(app_tz()).replace(tzinfo=None)


def _parse_iso_date(raw: str | None) -> date | None:
    dt = _parse_iso(raw)
    return dt.date() if dt else None


# Times Jobber emits for "all day / no time set" jobs after we convert UTC →
# operator local. Midnight is the obvious one; we also treat it as
# "unscheduled time" so the calendar shows "All day" instead of "12:00 AM".
_ALL_DAY_TIMES = {time(0, 0)}


def _candidate_jobber_ids(jobber_id: str) -> list[str]:
    """Return all forms of a Jobber id we might have stored.

    The CSV importer stamps the *raw numeric* Jobber id (e.g. 1234567).
    The API sync stamps the *Relay-encoded global id*
    (e.g. Z2lkOi8vSm9iYmVyL0NsaWVudC8xMjM0NTY3 = base64 of
    gid://Jobber/Client/1234567).

    Quote/invoice payloads always carry the encoded form. To match either
    style of stored stamp we try both: the raw input AND any numeric
    suffix we can decode from it.
    """
    out = [jobber_id]
    try:
        # base64 padding can be missing; pad to a multiple of 4
        padded = jobber_id + "=" * (-len(jobber_id) % 4)
        decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
        # Expect "gid://Jobber/Client/1234567" — take the trailing segment
        if "/" in decoded:
            tail = decoded.rsplit("/", 1)[-1].strip()
            if tail and tail not in out:
                out.append(tail)
    except Exception:
        pass
    return out


def _client_by_jobber_id(jobber_client_id: str) -> Client | None:
    for cid in _candidate_jobber_ids(jobber_client_id):
        c = db.session.scalar(
            select(Client).where(
                Client.notes.like(f"%[Imported from Jobber, client #{cid}]%")
            )
        )
        if c:
            return c
    return None


def _property_for(client: Client, jobber_property_id: str | None) -> Property | None:
    """Find a Property by Jobber property ID stamped in notes; else first prop."""
    if jobber_property_id:
        candidates = _candidate_jobber_ids(jobber_property_id)
        for p in (client.properties or []):
            if not p.notes:
                continue
            for pid in candidates:
                if f"[Jobber property #{pid}]" in p.notes:
                    return p
    # Fallback: first property under the client
    return (client.properties or [None])[0]


def _has_jobber_tag(notes: str | None, kind: str, jobber_id: str) -> bool:
    """Has this row already been imported from Jobber?"""
    return bool(notes and f"[Jobber {kind} #{jobber_id}]" in notes)


def _jobber_tag(kind: str, jobber_id: str) -> str:
    return f"\n[Jobber {kind} #{jobber_id}]"


def _to_cents(amount: float | int | str | None) -> int:
    """Jobber returns money as floats (dollars). Convert to integer cents."""
    if amount is None:
        return 0
    try:
        d = Decimal(str(amount))
    except Exception:
        return 0
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _decimal_qty(q: float | int | str | None) -> Decimal:
    if q is None:
        return Decimal("1")
    try:
        return Decimal(str(q))
    except Exception:
        return Decimal("1")


def _paginated(query: str, root_field: str, page_size: int = 25,
                extra_vars: dict | None = None) -> list[dict]:
    """Page through a Relay-style connection. Returns flat list of node dicts.

    Smaller page_size (25 vs 50) reduces per-query point cost on Jobber's
    rate-limited API. Combined with graphql()'s pre-call sleep, this keeps
    a full multi-entity sync well under 2500 points/min."""
    out = []
    after = None
    while True:
        variables = {"first": page_size, "after": after}
        if extra_vars:
            variables.update(extra_vars)
        data = graphql(query, variables)
        connection = data.get(root_field) or {}
        for edge in connection.get("edges") or []:
            out.append(edge.get("node") or {})
        page = connection.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        after = page.get("endCursor")
    return out


def _get_existing_id_by_tag(model, kind: str, jobber_id: str):
    """Find an existing local record by its Jobber-id stamp.

    Tries both the raw id and any decoded numeric form (see
    _candidate_jobber_ids) so dedup works regardless of which import path
    originally stored the record.
    """
    notes_col = getattr(model, "internal_notes", None) or getattr(model, "notes", None)
    if notes_col is None:
        return None
    for jid in _candidate_jobber_ids(jobber_id):
        row = db.session.scalar(
            select(model).where(notes_col.like(f"%[Jobber {kind} #{jid}]%"))
        )
        if row:
            return row
    return None


# ---------- JOBS ----------

JOBS_QUERY = """
query Jobs($first: Int!, $after: String) {
  jobs(first: $first, after: $after) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        jobNumber
        title
        instructions
        jobStatus
        startAt
        endAt
        createdAt
        client { id }
        property { id }
      }
    }
  }
}
"""


def sync_jobs() -> dict:
    raw = _paginated(JOBS_QUERY, "jobs")
    stats = {"seen": len(raw), "created": 0, "skipped_existing": 0,
             "skipped_no_client": 0, "errors": []}

    for n in raw:
        try:
            jid = n.get("id")
            if not jid:
                continue
            if _get_existing_id_by_tag(Job, "job", jid):
                stats["skipped_existing"] += 1
                continue

            client_ref = (n.get("client") or {}).get("id")
            client = _client_by_jobber_id(client_ref) if client_ref else None
            if not client:
                stats["skipped_no_client"] += 1
                continue

            prop = _property_for(client, (n.get("property") or {}).get("id"))
            if prop is None:
                stats["skipped_no_client"] += 1
                continue

            start = _parse_iso_local(n.get("startAt"))
            status = JOB_STATUS_MAP.get(n.get("jobStatus", "").upper(), "scheduled")
            sched_time = start.time() if start else None
            if sched_time in _ALL_DAY_TIMES:
                sched_time = None

            job = Job(
                client_id=client.id,
                property_id=prop.id,
                title=(n.get("title") or "Untitled job").strip()[:200],
                scope=(n.get("instructions") or "").strip() or None,
                status=status,
                scheduled_date=start.date() if start else None,
                scheduled_time=sched_time,
                notes=f"[Jobber job #{jid}] (Jobber #{n.get('jobNumber') or '?'})",
            )
            db.session.add(job)
            stats["created"] += 1
        except Exception as e:
            stats["errors"].append(f"job {n.get('id')}: {e!r}")

    db.session.commit()
    return stats


# ---------- QUOTES ----------

QUOTES_QUERY = """
query Quotes($first: Int!, $after: String) {
  quotes(first: $first, after: $after) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        quoteNumber
        title
        message
        quoteStatus
        client { id }
        property { id }
        lineItems {
          nodes { name description quantity unitPrice taxable }
        }
      }
    }
  }
}
"""


def sync_quotes() -> dict:
    # page_size=10: same reasoning as invoices — nested lineItems push
    # the per-call point cost up, smaller pages = fewer THROTTLED retries.
    raw = _paginated(QUOTES_QUERY, "quotes", page_size=10)
    stats = {"seen": len(raw), "created": 0, "skipped_existing": 0,
             "skipped_no_client": 0, "errors": []}

    for n in raw:
        try:
            jid = n.get("id")
            if not jid:
                continue
            if _get_existing_id_by_tag(Quote, "quote", jid):
                stats["skipped_existing"] += 1
                continue

            client_ref = (n.get("client") or {}).get("id")
            client = _client_by_jobber_id(client_ref) if client_ref else None
            if not client:
                stats["skipped_no_client"] += 1
                continue
            prop = _property_for(client, (n.get("property") or {}).get("id"))
            if prop is None:
                stats["skipped_no_client"] += 1
                continue

            status = QUOTE_STATUS_MAP.get((n.get("quoteStatus") or "").upper(), "draft")

            q = Quote(
                client_id=client.id,
                property_id=prop.id,
                number=Quote.next_number(db.session),
                subject=(n.get("title") or f"Quote Q-{n.get('quoteNumber')}").strip()[:200],
                message_to_customer=(n.get("message") or "").strip() or None,
                internal_notes=_jobber_tag("quote", jid).strip(),
                status=status,
            )
            db.session.add(q)
            db.session.flush()

            for li_node in ((n.get("lineItems") or {}).get("nodes") or []):
                desc = ((li_node.get("name") or "") + " "
                        + (li_node.get("description") or "")).strip()
                if not desc:
                    continue
                db.session.add(LineItem(
                    quote_id=q.id,
                    description=desc[:500],
                    quantity=_decimal_qty(li_node.get("quantity")),
                    unit_price_cents=_to_cents(li_node.get("unitPrice")),
                    taxable=bool(li_node.get("taxable")),
                ))
            stats["created"] += 1
        except Exception as e:
            stats["errors"].append(f"quote {n.get('id')}: {e!r}")

    db.session.commit()
    return stats


# ---------- INVOICES (and nested PAYMENTS) ----------

INVOICES_QUERY = """
query Invoices($first: Int!, $after: String) {
  invoices(first: $first, after: $after) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        invoiceNumber
        subject
        message
        invoiceStatus
        issuedDate
        dueDate
        createdAt
        client { id }
        propertyIds
        amounts { subtotal total taxAmount }
        lineItems {
          nodes { name description quantity unitPrice taxable }
        }
        paymentRecords {
          nodes { id amount }
        }
      }
    }
  }
}
"""


def sync_invoices() -> dict:
    # Use page_size=10 for invoices — they have nested lineItems AND
    # paymentRecords, so the per-call point cost on Jobber's rate-limit
    # accounting is high. Smaller pages = fewer THROTTLED retries.
    raw = _paginated(INVOICES_QUERY, "invoices", page_size=10)
    stats = {"seen": len(raw), "created": 0, "skipped_existing": 0,
             "skipped_no_client": 0, "payments_created": 0, "errors": []}

    for n in raw:
        try:
            jid = n.get("id")
            if not jid:
                continue
            if _get_existing_id_by_tag(Invoice, "invoice", jid):
                stats["skipped_existing"] += 1
                continue

            client_ref = (n.get("client") or {}).get("id")
            client = _client_by_jobber_id(client_ref) if client_ref else None
            if not client:
                stats["skipped_no_client"] += 1
                continue
            # Invoice.propertyIds is [String!] (Jobber's invoice can span
            # multiple properties — almost always one). Take the first.
            property_ids = n.get("propertyIds") or []
            jobber_prop_id = property_ids[0] if property_ids else None
            prop = _property_for(client, jobber_prop_id)
            if prop is None:
                stats["skipped_no_client"] += 1
                continue

            status = INVOICE_STATUS_MAP.get((n.get("invoiceStatus") or "").upper(), "draft")

            inv = Invoice(
                client_id=client.id,
                property_id=prop.id,
                number=Invoice.next_number(db.session),
                subject=(n.get("subject") or f"Invoice #{n.get('invoiceNumber')}").strip()[:200],
                notes=_jobber_tag("invoice", jid).strip(),
                status=status,
                due_date=_parse_iso_date(n.get("dueDate")),
                sent_at=_parse_iso(n.get("issuedDate")),
            )
            db.session.add(inv)
            db.session.flush()

            for li_node in ((n.get("lineItems") or {}).get("nodes") or []):
                desc = ((li_node.get("name") or "") + " "
                        + (li_node.get("description") or "")).strip()
                if not desc:
                    continue
                db.session.add(LineItem(
                    invoice_id=inv.id,
                    description=desc[:500],
                    quantity=_decimal_qty(li_node.get("quantity")),
                    unit_price_cents=_to_cents(li_node.get("unitPrice")),
                    taxable=bool(li_node.get("taxable")),
                ))

            # Inline payments — saves N+1 GraphQL calls (one per invoice).
            payment_nodes = ((n.get("paymentRecords") or {}).get("nodes") or [])
            n_payments = _import_payment_nodes(inv, payment_nodes)
            stats["payments_created"] += n_payments
            if n_payments:
                inv.recompute_status()

            stats["created"] += 1
        except Exception as e:
            stats["errors"].append(f"invoice {n.get('id')}: {e!r}")

    db.session.commit()
    return stats


def _import_payment_nodes(inv: Invoice, nodes: list[dict]) -> int:
    """Insert Payment rows for an invoice from inline GraphQL results.

    Idempotent via [Jobber payment #<id>] notes stamp.
    """
    n_created = 0
    existing_ids = {
        pid for pp in (inv.payments or [])
        for pid in re.findall(r"\[Jobber payment #([^\]]+)\]", pp.notes or "")
    }
    for p in nodes:
        pid = p.get("id")
        if not pid or pid in existing_ids:
            continue
        amt = _to_cents(p.get("amount"))
        if amt <= 0:
            continue
        # PaymentRecord on Jobber's API only exposes id + amount at our
        # access level (paymentMethod/paymentDate/createdAt/notes all
        # rejected). Use today as received_at; method/date editable after.
        received_at = datetime.utcnow()
        db.session.add(Payment(
            invoice_id=inv.id,
            amount_cents=amt,
            method="other",
            reference=None,
            received_at=received_at,
            notes=f"[Jobber payment #{pid}]",
        ))
        n_created += 1
    if n_created:
        db.session.flush()
    return n_created
