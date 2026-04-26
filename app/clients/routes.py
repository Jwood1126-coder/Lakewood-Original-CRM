"""Client routes — list, view, create, edit, delete."""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import or_, select

from app.clients.forms import ClientForm
from app.extensions import db
from app.models.client import Client
from app.utils.phone import normalize_phone

bp = Blueprint("clients", __name__, template_folder="../templates/clients")


@bp.route("/")
@login_required
def list_clients():
    q = (request.args.get("q") or "").strip()
    stmt = select(Client).order_by(Client.name)
    if q:
        like = f"%{q}%"
        digits = "".join(c for c in q if c.isdigit())
        conditions = [Client.name.ilike(like), Client.email.ilike(like)]
        if digits:
            conditions.append(Client.phone.ilike(f"%{digits}%"))
        stmt = stmt.where(or_(*conditions))
    clients = db.session.scalars(stmt).all()

    # HTMX requests get just the rows fragment for live search
    if request.headers.get("HX-Request"):
        return render_template("clients/_rows.html", clients=clients)
    return render_template("clients/list.html", clients=clients, q=q)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_client():
    form = ClientForm()
    if form.validate_on_submit():
        client = Client(
            name=form.name.data.strip(),
            phone=normalize_phone(form.phone.data),
            email=(form.email.data or "").strip().lower() or None,
            notes=(form.notes.data or "").strip() or None,
        )
        db.session.add(client)
        db.session.commit()
        flash(f"Created client: {client.name}", "success")
        return redirect(url_for("clients.view_client", client_id=client.id))
    return render_template("clients/edit.html", form=form, client=None)


@bp.route("/<int:client_id>")
@login_required
def view_client(client_id: int):
    client = db.session.get(Client, client_id) or abort(404)
    return render_template("clients/view.html", client=client)


@bp.route("/<int:client_id>/edit", methods=["GET", "POST"])
@login_required
def edit_client(client_id: int):
    client = db.session.get(Client, client_id) or abort(404)
    form = ClientForm(obj=client)
    if form.validate_on_submit():
        client.name = form.name.data.strip()
        client.phone = normalize_phone(form.phone.data)
        client.email = (form.email.data or "").strip().lower() or None
        client.notes = (form.notes.data or "").strip() or None
        db.session.commit()
        flash("Updated.", "success")
        return redirect(url_for("clients.view_client", client_id=client.id))
    return render_template("clients/edit.html", form=form, client=client)


@bp.route("/<int:client_id>/delete", methods=["POST"])
@login_required
def delete_client(client_id: int):
    client = db.session.get(Client, client_id) or abort(404)
    name = client.name
    db.session.delete(client)
    db.session.commit()
    flash(f"Deleted {name}.", "info")
    return redirect(url_for("clients.list_clients"))
