"""Main blueprint — home dashboard, health endpoint."""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template
from flask_login import current_user, login_required
from sqlalchemy import func, select

from app.extensions import db
from app.models.client import Client
from app.models.property import Property

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def index():
    client_count = db.session.scalar(select(func.count(Client.id))) or 0
    property_count = db.session.scalar(select(func.count(Property.id))) or 0
    return render_template(
        "main/index.html",
        client_count=client_count,
        property_count=property_count,
        user=current_user,
    )


@bp.route("/health")
def health():
    """Liveness check. No auth — used by Railway and uptime pings."""
    return jsonify(status="ok"), 200
