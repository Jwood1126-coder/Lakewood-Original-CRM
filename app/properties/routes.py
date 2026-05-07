"""Property routes — nested under client; also a flat photo serve route."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import login_required

from app.extensions import db
from app.models.client import Client
from app.models.photo import Photo
from app.models.property import Property
from app.properties.forms import PropertyForm
from app.services.photos import delete_photo, save_photo_for_property
from app.utils.ohio_tax import lookup_county, lookup_rate

bp = Blueprint("properties", __name__, template_folder="../templates/properties")


def _autofill(form: PropertyForm) -> None:
    """If county/tax_rate left blank, fill from ZIP."""
    if not form.county.data and form.zip_code.data:
        county = lookup_county(form.zip_code.data)
        if county:
            form.county.data = county
    if form.tax_rate.data is None:
        form.tax_rate.data = lookup_rate(form.county.data)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_property():
    client_id = request.args.get("client_id", type=int)
    client = db.session.get(Client, client_id) if client_id else None
    if not client:
        abort(400, "client_id required")

    next_target = request.args.get("next") or request.form.get("next")
    form = PropertyForm()
    if form.validate_on_submit():
        _autofill(form)
        prop = Property(
            client_id=client.id,
            label=form.label.data.strip(),
            address_line1=form.address_line1.data.strip(),
            address_line2=(form.address_line2.data or "").strip() or None,
            city=form.city.data.strip(),
            state=form.state.data.strip().upper(),
            zip_code=form.zip_code.data.strip(),
            county=(form.county.data or "").strip() or None,
            tax_rate=form.tax_rate.data or Decimal("0.0575"),
            notes=(form.notes.data or "").strip() or None,
        )
        db.session.add(prop)
        db.session.commit()
        flash("Property added.", "success")
        # Bounce-back to the form the operator was filling out
        if next_target == "quote":
            return redirect(url_for(
                "quotes.new_quote", client_id=client.id, property_id=prop.id))
        if next_target == "job":
            return redirect(url_for(
                "jobs.new_job", client_id=client.id, property_id=prop.id))
        if next_target == "invoice":
            return redirect(url_for(
                "invoices.new_invoice", client_id=client.id, property_id=prop.id))
        return redirect(url_for("properties.view_property", property_id=prop.id))

    return render_template("properties/edit.html", form=form, client=client, prop=None,
                           next_target=next_target)


@bp.route("/<int:property_id>")
@login_required
def view_property(property_id: int):
    from sqlalchemy import select as _select
    prop = db.session.get(Property, property_id) or abort(404)
    photos = db.session.scalars(
        _select(Photo)
        .where(Photo.property_id == prop.id)
        .order_by(Photo.created_at.desc())
    ).all()
    return render_template("properties/view.html", prop=prop, prop_photos=photos)


@bp.route("/<int:property_id>/edit", methods=["GET", "POST"])
@login_required
def edit_property(property_id: int):
    prop = db.session.get(Property, property_id) or abort(404)
    form = PropertyForm(obj=prop)
    if form.validate_on_submit():
        _autofill(form)
        prop.label = form.label.data.strip()
        prop.address_line1 = form.address_line1.data.strip()
        prop.address_line2 = (form.address_line2.data or "").strip() or None
        prop.city = form.city.data.strip()
        prop.state = form.state.data.strip().upper()
        prop.zip_code = form.zip_code.data.strip()
        prop.county = (form.county.data or "").strip() or None
        prop.tax_rate = form.tax_rate.data or Decimal("0.0575")
        prop.notes = (form.notes.data or "").strip() or None
        db.session.commit()
        flash("Updated.", "success")
        return redirect(url_for("properties.view_property", property_id=prop.id))
    return render_template("properties/edit.html", form=form, client=prop.client, prop=prop)


@bp.route("/<int:property_id>/delete", methods=["POST"])
@login_required
def delete_property(property_id: int):
    prop = db.session.get(Property, property_id) or abort(404)
    client_id = prop.client_id
    db.session.delete(prop)
    db.session.commit()
    flash("Property deleted.", "info")
    return redirect(url_for("clients.view_client", client_id=client_id))


# --- Photos ---

@bp.route("/<int:property_id>/photos", methods=["POST"])
@login_required
def upload_photo(property_id: int):
    prop = db.session.get(Property, property_id) or abort(404)
    files = request.files.getlist("photos")
    if not files:
        flash("No photos selected.", "error")
        return redirect(url_for("properties.view_property", property_id=prop.id))

    saved = 0
    for f in files:
        if not f.filename:
            continue
        try:
            save_photo_for_property(prop.id, f)
            saved += 1
        except ValueError as e:
            flash(f"{f.filename}: {e}", "error")
        except Exception as e:
            current_app.logger.exception("Photo upload failed: %s", e)
            flash(f"{f.filename}: upload failed", "error")
    if saved:
        flash(f"Uploaded {saved} photo{'s' if saved != 1 else ''}.", "success")
    return redirect(url_for("properties.view_property", property_id=prop.id))


@bp.route("/photos/<int:photo_id>/delete", methods=["POST"])
@login_required
def delete_photo_route(photo_id: int):
    photo = db.session.get(Photo, photo_id) or abort(404)
    parent_property_id = photo.property_id
    delete_photo(photo)
    flash("Photo deleted.", "info")
    return redirect(url_for("properties.view_property", property_id=parent_property_id))


@bp.route("/photos/file/<path:rel_path>")
@login_required
def serve_photo(rel_path: str):
    """Serve a photo file. Auth-gated so files aren't world-readable.

    The path is sanitized by send_from_directory; it raises 404 on traversal.
    """
    photo_root: Path = current_app.config["PHOTO_DIR"]
    return send_from_directory(photo_root, rel_path, as_attachment=False)
