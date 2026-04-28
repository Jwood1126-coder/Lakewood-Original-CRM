"""Event-driven notifications.

When meaningful business events happen (quote sent, invoice paid, payment
received, job complete), we emit a Notification — which lands in the in-app
inbox AND optionally emails the operator (subject to Settings → Notifications
toggles).

Pattern: route handlers call notify_X(...) after the DB write commits.
That way:
  - The notification fires on success only (no false "invoice paid" if the
    DB rolled back).
  - Email failures don't block the route response.

Each helper is small + idempotent. Call sites are explicit; we deliberately
do NOT subscribe to audit_log events — that would couple business meaning
("paid") to incidental schema changes ("status column went from X to Y").
"""
from __future__ import annotations

from datetime import datetime
from html import escape

from flask import current_app
from sqlalchemy import select

from app.extensions import db
from app.models.invoice import Invoice
from app.models.job import Job
from app.models.notification import Notification
from app.models.payment import Payment
from app.models.quote import Quote
from app.models.setting import get_setting


# ---------- internal: deliver via the configured channels ----------

def _emit(kind: str, title: str, body_html: str) -> Notification:
    """Persist a Notification; optionally email per user settings.

    Always inserts the Notification row (in-app inbox is always on).
    Emails only if (a) the email channel toggle is on AND (b) SMTP is
    configured AND (c) at least one recipient is set.
    """
    notif = Notification(kind=kind, title=title, body_html=body_html)
    db.session.add(notif)
    db.session.commit()

    if get_setting("notify_email", "1") != "1":
        return notif

    to = (get_setting("notify_email_to")
          or current_app.config.get("NOTIFY_EMAIL")
          or "").strip()
    if not to:
        return notif
    if not (current_app.config.get("SMTP_USER") and
            current_app.config.get("SMTP_PASSWORD")):
        return notif

    try:
        from app.services.email import send_email
        send_email(to=to, subject=title, html=body_html)
        notif.sent_email_at = datetime.utcnow()
        db.session.commit()
    except Exception as e:
        current_app.logger.warning("Event email %s failed: %s", kind, e)

    return notif


def _client_link(client_id: int, name: str, base_url: str) -> str:
    return f'<a href="{base_url}/clients/{client_id}">{escape(name)}</a>'


def _base_url() -> str:
    """Best-effort absolute URL for the current request, or empty string."""
    try:
        from flask import request
        return request.url_root.rstrip("/")
    except Exception:
        return ""


# ---------- Intake events ----------

def notify_quote_request_received(quote: Quote, source: str = "website") -> None:
    """A new quote-request just came in from the public intake form."""
    if get_setting("notify_event_quote_request_received", "1") != "1":
        return
    base = _base_url()
    title = f"📩 New request from {quote.client.name} ({source})"
    body = f"""
      <h2 style='margin:0 0 0.4rem;color:#1d4ed8'>New service request</h2>
      <p><b>{escape(quote.client.name)}</b></p>
      <p>
        {('📞 ' + escape(quote.client.display_phone)) if quote.client.phone else ''}
        {('<br>✉️ ' + escape(quote.client.email)) if quote.client.email else ''}
      </p>
      <p><b>What they want:</b><br>{escape(quote.subject)}</p>
      {f'<p><b>Address:</b> {escape(quote.prop.address_one_line)}</p>' if quote.prop else ''}
      {f"<p style='white-space:pre-wrap'><b>Their description:</b><br>{escape(quote.internal_notes or '')}</p>" if quote.internal_notes else ''}
      <p style='font-size:0.85rem;color:#888'>
        <a href="{base}/quotes/{quote.id}">Open in CRM ↗</a> · drafted as Q-{quote.number}
      </p>
    """
    _emit("event_quote_request_received", title, body)


# ---------- Quote events ----------

def notify_quote_sent(quote: Quote) -> None:
    if get_setting("notify_event_quote_sent", "1") != "1":
        return
    base = _base_url()
    title = f"Quote Q-{quote.number} marked sent — {quote.client.name}"
    body = f"""
      <h2 style='margin:0 0 0.4rem'>Quote sent</h2>
      <p><b>Q-{quote.number}</b> · {escape(quote.subject)}</p>
      <p>Client: {escape(quote.client.name)}<br>
         Total: ${quote.total_cents/100:.2f}</p>
      <p style='font-size:0.85rem;color:#888'>
        <a href="{base}/quotes/{quote.id}">View quote ↗</a>
      </p>
    """
    _emit("event_quote_sent", title, body)


def notify_quote_accepted(quote: Quote) -> None:
    if get_setting("notify_event_quote_accepted", "1") != "1":
        return
    base = _base_url()
    title = f"✓ Quote Q-{quote.number} ACCEPTED — {quote.client.name}"
    body = f"""
      <h2 style='margin:0 0 0.4rem;color:#15803d'>Quote accepted</h2>
      <p><b>Q-{quote.number}</b> · {escape(quote.subject)} — ${quote.total_cents/100:.2f}</p>
      <p>Client: {escape(quote.client.name)}</p>
      <p style='font-size:0.85rem;color:#888'>
        <a href="{base}/quotes/{quote.id}">View quote ↗</a> · ready to convert to a job
      </p>
    """
    _emit("event_quote_accepted", title, body)


def notify_quote_converted(quote: Quote, job: Job) -> None:
    if get_setting("notify_event_quote_converted", "1") != "1":
        return
    base = _base_url()
    title = f"Quote Q-{quote.number} → Job #{job.id} created"
    body = f"""
      <h2 style='margin:0 0 0.4rem'>Quote converted to job</h2>
      <p><b>{escape(job.title)}</b> for {escape(quote.client.name)}</p>
      <p style='font-size:0.85rem;color:#888'>
        <a href="{base}/jobs/{job.id}">View job ↗</a> · pick a date next
      </p>
    """
    _emit("event_quote_converted", title, body)


# ---------- Job events ----------

def notify_job_complete(job: Job) -> None:
    if get_setting("notify_event_job_complete", "1") != "1":
        return
    base = _base_url()
    title = f"✓ Job #{job.id} complete — {job.client.name}"
    body = f"""
      <h2 style='margin:0 0 0.4rem;color:#15803d'>Job marked complete</h2>
      <p><b>{escape(job.title)}</b></p>
      <p>Client: {escape(job.client.name)}<br>
         {escape(job.prop.address_one_line) if job.prop else ''}</p>
      <p>Visits: {len(job.visits)} · {job.total_visit_hours}h on site
         {f'· {job.total_miles} miles' if job.total_miles else ''}</p>
      <p style='font-size:0.85rem;color:#888'>
        <a href="{base}/jobs/{job.id}">View job ↗</a> ·
        <a href="{base}/invoices/new?from_job={job.id}">Create invoice ↗</a>
      </p>
    """
    _emit("event_job_complete", title, body)


# ---------- Invoice events ----------

def notify_invoice_sent(invoice: Invoice) -> None:
    if get_setting("notify_event_invoice_sent", "1") != "1":
        return
    base = _base_url()
    title = f"Invoice #{invoice.number} marked sent — {invoice.client.name}"
    body = f"""
      <h2 style='margin:0 0 0.4rem'>Invoice sent</h2>
      <p><b>#{invoice.number}</b> · {escape(invoice.subject)} — ${invoice.total_cents/100:.2f}</p>
      <p>Client: {escape(invoice.client.name)}<br>
         Due: {invoice.due_date.strftime('%b %d, %Y') if invoice.due_date else 'Not set'}</p>
      <p style='font-size:0.85rem;color:#888'>
        <a href="{base}/invoices/{invoice.id}">View invoice ↗</a>
      </p>
    """
    _emit("event_invoice_sent", title, body)


def notify_invoice_paid(invoice: Invoice) -> None:
    if get_setting("notify_event_invoice_paid", "1") != "1":
        return
    base = _base_url()
    title = f"✓ Invoice #{invoice.number} PAID — {invoice.client.name} (${invoice.total_cents/100:.2f})"
    body = f"""
      <h2 style='margin:0 0 0.4rem;color:#15803d'>Invoice paid in full 💰</h2>
      <p><b>#{invoice.number}</b> · {escape(invoice.subject)}</p>
      <p>Client: {escape(invoice.client.name)}<br>
         Total: ${invoice.total_cents/100:.2f}</p>
      <p style='font-size:0.85rem;color:#888'>
        <a href="{base}/invoices/{invoice.id}">View invoice ↗</a>
      </p>
    """
    _emit("event_invoice_paid", title, body)


def notify_payment_received(payment: Payment) -> None:
    if get_setting("notify_event_payment_received", "1") != "1":
        return
    if not payment.invoice:
        return
    inv = payment.invoice
    base = _base_url()
    title = f"💵 Payment received: ${payment.amount_cents/100:.2f} from {inv.client.name} (#{inv.number})"
    body = f"""
      <h2 style='margin:0 0 0.4rem'>Payment recorded</h2>
      <p><b>${payment.amount_cents/100:.2f}</b> via {escape(payment.method_label)}
         {f'· ref {escape(payment.reference)}' if payment.reference else ''}</p>
      <p>Invoice <b>#{inv.number}</b> — {escape(inv.subject)}<br>
         Client: {escape(inv.client.name)}<br>
         Balance now: ${inv.balance_cents/100:.2f} of ${inv.total_cents/100:.2f}</p>
      <p style='font-size:0.85rem;color:#888'>
        <a href="{base}/invoices/{inv.id}">View invoice ↗</a>
      </p>
    """
    _emit("event_payment_received", title, body)
