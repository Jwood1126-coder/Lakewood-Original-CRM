"""Main blueprint — home dashboard ("Today" view), inbox, health."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, select, update
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.client import Client
from app.models.job import Job
from app.models.notification import Notification
from app.models.property import Property

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def index():
    today = date.today()
    week_end = today + timedelta(days=7)

    today_jobs = db.session.scalars(
        select(Job)
        .options(joinedload(Job.client), joinedload(Job.prop))
        .where(Job.scheduled_date == today, Job.status != "canceled")
        .order_by(Job.scheduled_time.nulls_last())
    ).all()

    upcoming_jobs = db.session.scalars(
        select(Job)
        .options(joinedload(Job.client), joinedload(Job.prop))
        .where(
            Job.scheduled_date > today,
            Job.scheduled_date <= week_end,
            Job.status.in_(["scheduled", "in_progress"]),
        )
        .order_by(Job.scheduled_date, Job.scheduled_time.nulls_last())
        .limit(8)
    ).all()

    overdue_jobs = db.session.scalars(
        select(Job)
        .options(joinedload(Job.client), joinedload(Job.prop))
        .where(
            Job.scheduled_date < today,
            Job.status.in_(["scheduled", "in_progress"]),
        )
        .order_by(Job.scheduled_date)
        .limit(8)
    ).all()

    in_progress_count = db.session.scalar(
        select(func.count(Job.id)).where(Job.status == "in_progress")
    ) or 0
    open_count = db.session.scalar(
        select(func.count(Job.id)).where(Job.status.in_(["scheduled", "in_progress"]))
    ) or 0

    client_count = db.session.scalar(select(func.count(Client.id))) or 0

    return render_template(
        "main/index.html",
        user=current_user,
        today=today,
        today_jobs=today_jobs,
        upcoming_jobs=upcoming_jobs,
        overdue_jobs=overdue_jobs,
        in_progress_count=in_progress_count,
        open_count=open_count,
        client_count=client_count,
    )


@bp.route("/inbox")
@login_required
def inbox():
    notifications = db.session.scalars(
        select(Notification).order_by(Notification.created_at.desc()).limit(50)
    ).all()
    # Mark as read on view (a single-user app — viewing == reading)
    for n in notifications:
        if n.read_at is None:
            n.read_at = datetime.utcnow()
    db.session.commit()
    return render_template("main/inbox.html", notifications=notifications)


@bp.route("/inbox/mark-all-read", methods=["POST"])
@login_required
def inbox_mark_all_read():
    db.session.execute(
        update(Notification)
        .where(Notification.read_at.is_(None))
        .values(read_at=datetime.utcnow())
    )
    db.session.commit()
    flash("Inbox cleared.", "success")
    return redirect(url_for("main.inbox"))


@bp.route("/health")
def health():
    return jsonify(status="ok"), 200
