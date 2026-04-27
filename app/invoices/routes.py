"""Invoice + Payment routes."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.invoices.forms import InvoiceForm, PaymentForm
from app.models.client import Client
from app.models.invoice import INVOICE_STATUS_LABELS, INVOICE_STATUSES, Invoice
from app.models.job import Job
from app.models.line_item import LineItem
from app.models.payment import Payment
from app.models.property import Property
from app.services.money import dollars_to_cents, parse_qty

bp = Blueprint("invoices", __name__, template_folder="../templates/invoices")


def _populate_choices(form: InvoiceForm, preselect_client_id: int | None = None) -> None:
    clients = db.session.scalars(select(Client).order_by(Client.name)).all()
    form.client_id.choices = [(c.id, c.name) for c in clients] or [(0, "— add a client —")]

    chosen = preselect_client_id or form.client_id.data
    if chosen:
        props = db.session.scalars(
            select(Property).where(Property.client_id == chosen).order_by(Property.label)
        ).all()
        form.property_id.choices = [(p.id, f"{p.label} — {p.address_line1}") for p in props] \
                                    or [(0, "— add a property —")]
        jobs = db.session.scalars(
            select(Job).where(Job.client_id == chosen).order_by(Job.created_at.desc())
        ).all()
        form.job_id.choices = [(0, "— none / standalone invoice —")] + \
                               [(j.id, f"#{j.id} {j.title}") for j in jobs]
    else:
        form.property_id.choices = []
        form.job_id.choices = [(0, "— none —")]


def _save_line_items(invoice: Invoice) -> None:
    descs = request.form.getlist("li_description[]")
    qtys = request.form.getlist("li_qty[]")
    prices = request.form.getlist("li_price[]")
    taxable_indexes = set(request.form.getlist("li_taxable_idx[]"))

    for li in list(invoice.line_items):
        db.session.delete(li)
    db.session.flush()

    pos = 0
    for i, desc in enumerate(descs):
        d = (desc or "").strip()
        if not d:
            continue
        try:
            qty = parse_qty(qtys[i] if i < len(qtys) else "1")
            price_cents = dollars_to_cents(prices[i] if i < len(prices) else "0")
        except ValueError:
            continue
        db.session.add(LineItem(
            invoice_id=invoice.id,
            position=pos,
            description=d,
            quantity=qty,
            unit_price_cents=price_cents,
            taxable=str(i) in taxable_indexes,
        ))
        pos += 1


@bp.route("/")
@login_required
def list_invoices():
    status = request.args.get("status")
    stmt = (select(Invoice)
            .options(joinedload(Invoice.client), joinedload(Invoice.prop))
            .order_by(Invoice.created_at.desc()))
    if status and status in INVOICE_STATUSES:
        stmt = stmt.where(Invoice.status == status)
    elif status == "overdue":
        stmt = stmt.where(
            Invoice.status.in_(["sent", "partial"]),
            Invoice.due_date < date.today(),
        )
    invoices = db.session.scalars(stmt).all()
    return render_template("invoices/list.html", invoices=invoices, status=status,
                           statuses=INVOICE_STATUSES, status_labels=INVOICE_STATUS_LABELS)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_invoice():
    preselect_client = request.args.get("client_id", type=int)
    preselect_property = request.args.get("property_id", type=int)
    from_job_id = request.args.get("from_job", type=int)
    form = InvoiceForm()

    job = db.session.get(Job, from_job_id) if from_job_id else None

    if request.method == "GET":
        if job:
            form.client_id.data = job.client_id
            form.property_id.data = job.property_id
            form.job_id.data = job.id
            form.subject.data = job.title
        elif preselect_client and not form.client_id.data:
            form.client_id.data = preselect_client
        if preselect_property and not form.property_id.data:
            form.property_id.data = preselect_property
        if not form.due_date.data:
            form.due_date.data = date.today() + timedelta(days=14)

    _populate_choices(form, preselect_client_id=form.client_id.data)

    if form.validate_on_submit():
        invoice = Invoice(
            client_id=form.client_id.data,
            property_id=form.property_id.data,
            job_id=form.job_id.data if form.job_id.data else None,
            number=Invoice.next_number(db.session),
            subject=form.subject.data.strip(),
            notes=(form.notes.data or "").strip() or None,
            tax_rate_override=form.tax_rate_override.data,
            due_date=form.due_date.data,
            status="draft",
        )
        db.session.add(invoice)
        db.session.flush()
        _save_line_items(invoice)
        db.session.commit()
        flash(f"Created invoice #{invoice.number}.", "success")
        return redirect(url_for("invoices.view_invoice", invoice_id=invoice.id))

    # Pre-fill line items from a source job's visits if creating from job
    seed_items = []
    if request.method == "GET" and job and job.visits:
        for v in job.visits:
            if v.duration:
                hours = round(v.duration.total_seconds() / 3600, 2)
                seed_items.append({
                    "description": f"Labor — {v.scheduled_date or 'visit'}",
                    "quantity": hours,
                    "unit_price_dollars": "",
                    "taxable": False,
                })
    return render_template("invoices/edit.html", form=form, invoice=None,
                           line_items=[], seed_items=seed_items)


@bp.route("/<int:invoice_id>")
@login_required
def view_invoice(invoice_id: int):
    invoice = db.session.get(Invoice, invoice_id) or abort(404)
    payment_form = PaymentForm()
    return render_template("invoices/view.html", invoice=invoice,
                           payment_form=payment_form)


@bp.route("/<int:invoice_id>/edit", methods=["GET", "POST"])
@login_required
def edit_invoice(invoice_id: int):
    invoice = db.session.get(Invoice, invoice_id) or abort(404)
    form = InvoiceForm(obj=invoice)
    if request.method == "GET":
        form.client_id.data = invoice.client_id
        form.property_id.data = invoice.property_id
        form.job_id.data = invoice.job_id or 0
    _populate_choices(form, preselect_client_id=form.client_id.data)

    if form.validate_on_submit():
        invoice.client_id = form.client_id.data
        invoice.property_id = form.property_id.data
        invoice.job_id = form.job_id.data if form.job_id.data else None
        invoice.subject = form.subject.data.strip()
        invoice.notes = (form.notes.data or "").strip() or None
        invoice.tax_rate_override = form.tax_rate_override.data
        invoice.due_date = form.due_date.data
        _save_line_items(invoice)
        invoice.recompute_status()
        db.session.commit()
        flash("Saved.", "success")
        return redirect(url_for("invoices.view_invoice", invoice_id=invoice.id))

    return render_template("invoices/edit.html", form=form, invoice=invoice,
                           line_items=invoice.line_items, seed_items=[])


@bp.route("/<int:invoice_id>/delete", methods=["POST"])
@login_required
def delete_invoice(invoice_id: int):
    invoice = db.session.get(Invoice, invoice_id) or abort(404)
    db.session.delete(invoice)
    db.session.commit()
    flash("Invoice deleted.", "info")
    return redirect(url_for("invoices.list_invoices"))


@bp.route("/<int:invoice_id>/status/<new_status>", methods=["POST"])
@login_required
def change_status(invoice_id: int, new_status: str):
    from app.services.events import notify_invoice_paid, notify_invoice_sent

    invoice = db.session.get(Invoice, invoice_id) or abort(404)
    if new_status not in INVOICE_STATUSES:
        abort(400)
    prev = invoice.status
    invoice.status = new_status
    if new_status == "sent" and not invoice.sent_at:
        invoice.sent_at = datetime.utcnow()
    if new_status == "paid" and not invoice.paid_at:
        invoice.paid_at = datetime.utcnow()
    db.session.commit()

    if new_status != prev:
        if new_status == "sent":
            notify_invoice_sent(invoice)
        elif new_status == "paid":
            notify_invoice_paid(invoice)

    flash(f"Invoice marked {INVOICE_STATUS_LABELS[new_status]}.", "success")
    return redirect(url_for("invoices.view_invoice", invoice_id=invoice.id))


# ---------- Payments ----------

@bp.route("/<int:invoice_id>/payments", methods=["POST"])
@login_required
def record_payment(invoice_id: int):
    invoice = db.session.get(Invoice, invoice_id) or abort(404)
    form = PaymentForm()
    if not form.validate_on_submit():
        for field, errs in form.errors.items():
            for e in errs:
                flash(f"{field}: {e}", "error")
        return redirect(url_for("invoices.view_invoice", invoice_id=invoice.id))

    try:
        cents = dollars_to_cents(form.amount.data)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("invoices.view_invoice", invoice_id=invoice.id))

    if cents <= 0:
        flash("Payment amount must be greater than zero.", "error")
        return redirect(url_for("invoices.view_invoice", invoice_id=invoice.id))

    from app.services.events import notify_invoice_paid, notify_payment_received

    p = Payment(
        invoice_id=invoice.id,
        amount_cents=cents,
        method=form.method.data,
        reference=(form.reference.data or "").strip() or None,
        notes=(form.notes.data or "").strip() or None,
        received_at=form.received_at.data or datetime.utcnow(),
    )
    db.session.add(p)
    db.session.flush()
    prev_status = invoice.status
    invoice.recompute_status()
    db.session.commit()

    notify_payment_received(p)
    # If this payment closed out the invoice, send a paid-in-full notice too
    if invoice.status == "paid" and prev_status != "paid":
        notify_invoice_paid(invoice)

    flash(f"Recorded payment of ${cents/100:.2f}.", "success")
    return redirect(url_for("invoices.view_invoice", invoice_id=invoice.id))


@bp.route("/payments/<int:payment_id>/delete", methods=["POST"])
@login_required
def delete_payment(payment_id: int):
    p = db.session.get(Payment, payment_id) or abort(404)
    invoice_id = p.invoice_id
    invoice = p.invoice
    db.session.delete(p)
    db.session.flush()
    invoice.recompute_status()
    db.session.commit()
    flash("Payment removed.", "info")
    return redirect(url_for("invoices.view_invoice", invoice_id=invoice_id))
