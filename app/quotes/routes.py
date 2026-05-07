"""Quote routes — list, create, view, edit, send, accept/decline, convert to job."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required
from sqlalchemy import String, or_, select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.client import Client
from app.models.job import Job
from app.models.line_item import LineItem
from app.models.photo import Photo
from app.models.property import Property
from app.models.quote import QUOTE_STATUS_LABELS, QUOTE_STATUSES, Quote
from app.quotes.forms import QuoteForm
from app.services.money import dollars_to_cents, parse_qty
from app.services.photos import delete_photo, save_photo_for_quote

bp = Blueprint("quotes", __name__, template_folder="../templates/quotes")


def _populate_choices(form: QuoteForm, preselect_client_id: int | None = None) -> None:
    clients = db.session.scalars(select(Client).order_by(Client.name)).all()
    form.client_id.choices = [(c.id, c.name) for c in clients] or [(0, "— add a client first —")]
    chosen = preselect_client_id or form.client_id.data
    if chosen:
        props = db.session.scalars(
            select(Property).where(Property.client_id == chosen).order_by(Property.label)
        ).all()
        form.property_id.choices = [(p.id, f"{p.label} — {p.address_line1}") for p in props] \
                                    or [(0, "— add a property to this client first —")]
    else:
        form.property_id.choices = []


def _save_line_items(quote: Quote) -> list[str]:
    """Replace the quote's line items from request.form arrays.

    Returns a list of warnings for any rows that were rejected so the
    caller can surface them. (H5 fix: previously silent drops.)
    """
    descs = request.form.getlist("li_description[]")
    qtys = request.form.getlist("li_qty[]")
    prices = request.form.getlist("li_price[]")
    taxable_indexes = set(request.form.getlist("li_taxable_idx[]"))

    warnings: list[str] = []

    for li in list(quote.line_items):
        db.session.delete(li)
    db.session.flush()

    pos = 0
    for i, desc in enumerate(descs):
        d = (desc or "").strip()
        if not d:
            # Empty description silently skipped — that's how "delete a row"
            # works in the JS editor. Not a warning.
            continue
        try:
            qty = parse_qty(qtys[i] if i < len(qtys) else "1")
            price_cents = dollars_to_cents(prices[i] if i < len(prices) else "0")
        except (ValueError, TypeError) as e:
            warnings.append(
                f"Row {i+1} '{d[:40]}' skipped — bad number ({e})"
            )
            continue
        taxable = str(i) in taxable_indexes
        db.session.add(LineItem(
            quote_id=quote.id,
            position=pos,
            description=d,
            quantity=qty,
            unit_price_cents=price_cents,
            taxable=taxable,
        ))
        pos += 1
    return warnings


@bp.route("/")
@login_required
def list_quotes():
    status = request.args.get("status")
    q = (request.args.get("q") or "").strip()
    stmt = (select(Quote)
            .options(joinedload(Quote.client), joinedload(Quote.prop))
            .order_by(Quote.created_at.desc()))
    if status and status in QUOTE_STATUSES:
        stmt = stmt.where(Quote.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.join(Quote.client).where(
            or_(
                Quote.subject.ilike(like),
                Quote.number.cast(String).ilike(like),
                Client.name.ilike(like),
            )
        )
    quotes = db.session.scalars(stmt).all()
    return render_template("quotes/list.html", quotes=quotes, status=status, q=q,
                           statuses=QUOTE_STATUSES, status_labels=QUOTE_STATUS_LABELS)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_quote():
    preselect_client = request.args.get("client_id", type=int)
    preselect_property = request.args.get("property_id", type=int)
    form = QuoteForm()

    if request.method == "GET":
        if preselect_client and not form.client_id.data:
            form.client_id.data = preselect_client
        if preselect_property and not form.property_id.data:
            form.property_id.data = preselect_property
        if not form.valid_until.data:
            form.valid_until.data = date.today() + timedelta(days=30)

    _populate_choices(form, preselect_client_id=form.client_id.data)

    if form.validate_on_submit():
        quote = Quote(
            client_id=form.client_id.data,
            property_id=form.property_id.data,
            number=Quote.next_number(db.session),
            subject=form.subject.data.strip(),
            message_to_customer=(form.message_to_customer.data or "").strip() or None,
            internal_notes=(form.internal_notes.data or "").strip() or None,
            tax_rate_override=form.tax_rate_override.data,
            valid_until=form.valid_until.data,
            scheduled_date=form.scheduled_date.data,
            scheduled_time=form.scheduled_time.data,
            status="draft",
        )
        db.session.add(quote)
        db.session.flush()
        warnings = _save_line_items(quote)
        db.session.commit()
        for w in warnings:
            flash(w, "warning")
        flash(f"Created quote Q-{quote.number}.", "success")
        return redirect(url_for("quotes.view_quote", quote_id=quote.id))

    return render_template("quotes/edit.html", form=form, quote=None, line_items=[])


@bp.route("/<int:quote_id>")
@login_required
def view_quote(quote_id: int):
    quote = db.session.get(Quote, quote_id) or abort(404)
    return render_template("quotes/view.html", quote=quote)


@bp.route("/<int:quote_id>/edit", methods=["GET", "POST"])
@login_required
def edit_quote(quote_id: int):
    quote = db.session.get(Quote, quote_id) or abort(404)
    form = QuoteForm(obj=quote)
    if request.method == "GET":
        form.client_id.data = quote.client_id
        form.property_id.data = quote.property_id
    _populate_choices(form, preselect_client_id=form.client_id.data)

    if form.validate_on_submit():
        quote.client_id = form.client_id.data
        quote.property_id = form.property_id.data
        quote.subject = form.subject.data.strip()
        quote.message_to_customer = (form.message_to_customer.data or "").strip() or None
        quote.internal_notes = (form.internal_notes.data or "").strip() or None
        quote.tax_rate_override = form.tax_rate_override.data
        quote.valid_until = form.valid_until.data
        quote.scheduled_date = form.scheduled_date.data
        quote.scheduled_time = form.scheduled_time.data
        warnings = _save_line_items(quote)
        db.session.commit()
        for w in warnings:
            flash(w, "warning")
        flash("Saved.", "success")
        return redirect(url_for("quotes.view_quote", quote_id=quote.id))

    return render_template("quotes/edit.html", form=form, quote=quote,
                           line_items=quote.line_items)


@bp.route("/<int:quote_id>/delete", methods=["POST"])
@login_required
def delete_quote(quote_id: int):
    quote = db.session.get(Quote, quote_id) or abort(404)
    db.session.delete(quote)
    db.session.commit()
    flash("Quote deleted.", "info")
    return redirect(url_for("quotes.list_quotes"))


@bp.route("/<int:quote_id>/status/<new_status>", methods=["POST"])
@login_required
def change_status(quote_id: int, new_status: str):
    from app.services.events import notify_quote_accepted, notify_quote_sent

    quote = db.session.get(Quote, quote_id) or abort(404)
    if new_status not in QUOTE_STATUSES:
        abort(400)
    prev_status = quote.status
    quote.status = new_status
    if new_status == "sent" and not quote.sent_at:
        quote.sent_at = datetime.utcnow()
    if new_status == "accepted" and not quote.accepted_at:
        quote.accepted_at = datetime.utcnow()
    if new_status == "declined" and not quote.declined_at:
        quote.declined_at = datetime.utcnow()
    db.session.commit()

    # Fire event notifications only on actual transitions
    if new_status != prev_status:
        if new_status == "sent":
            notify_quote_sent(quote)
        elif new_status == "accepted":
            notify_quote_accepted(quote)

    flash(f"Quote marked {QUOTE_STATUS_LABELS[new_status]}.", "success")
    return redirect(url_for("quotes.view_quote", quote_id=quote.id))


@bp.route("/<int:quote_id>/convert-to-job", methods=["POST"])
@login_required
def convert_to_job(quote_id: int):
    from app.services.events import notify_quote_converted
    quote = db.session.get(Quote, quote_id) or abort(404)
    if quote.converted_to_job_id:
        flash("Quote already converted.", "warning")
        return redirect(url_for("jobs.view_job", job_id=quote.converted_to_job_id))

    # H2 fix: previously allowed converting from any status (draft, declined,
    # expired). Conversion is only meaningful from sent or accepted.
    if quote.status not in ("sent", "accepted"):
        flash(f"Cannot convert a {quote.status_label.lower()} quote. "
              f"Mark it sent or accepted first.", "error")
        return redirect(url_for("quotes.view_quote", quote_id=quote.id))

    job = Job(
        client_id=quote.client_id,
        property_id=quote.property_id,
        title=quote.subject,
        scope=(
            (quote.message_to_customer or "")
            + ("\n\n— Quote line items —\n" + "\n".join(
                f"  • {li.description} ({li.quantity} × ${li.unit_price_cents/100:.2f})"
                for li in quote.line_items
            ) if quote.line_items else "")
        ).strip() or None,
        status="scheduled",
    )
    db.session.add(job)
    db.session.flush()
    quote.converted_to_job_id = job.id
    # H2 fix: previously had dead intermediate "accepted" assignment that was
    # immediately overwritten. accepted_at must always be set if null since
    # converted implies it was accepted.
    if not quote.accepted_at:
        quote.accepted_at = datetime.utcnow()
    quote.status = "converted"
    db.session.commit()
    notify_quote_converted(quote, job)
    flash(f"Created job from quote Q-{quote.number}. Pick a date next.", "success")
    return redirect(url_for("jobs.edit_job", job_id=job.id))


# ---------- Photos ----------

@bp.route("/<int:quote_id>/photos", methods=["POST"])
@login_required
def upload_photo(quote_id: int):
    quote = db.session.get(Quote, quote_id) or abort(404)
    files = request.files.getlist("photos")
    if not files:
        flash("No photos selected.", "error")
        return redirect(url_for("quotes.view_quote", quote_id=quote.id))
    saved = 0
    for f in files:
        if not f.filename:
            continue
        try:
            save_photo_for_quote(quote.id, f)
            saved += 1
        except ValueError as e:
            flash(f"{f.filename}: {e}", "error")
        except Exception as e:
            current_app.logger.exception("Quote photo upload failed: %s", e)
            flash(f"{f.filename}: upload failed", "error")
    if saved:
        flash(f"Uploaded {saved} photo{'s' if saved != 1 else ''}.", "success")
    return redirect(url_for("quotes.view_quote", quote_id=quote.id))


@bp.route("/photos/<int:photo_id>/delete", methods=["POST"])
@login_required
def delete_photo_route(photo_id: int):
    photo = db.session.get(Photo, photo_id) or abort(404)
    parent_quote_id = photo.quote_id
    if not parent_quote_id:
        abort(404)
    delete_photo(photo)
    flash("Photo deleted.", "info")
    return redirect(url_for("quotes.view_quote", quote_id=parent_quote_id))
