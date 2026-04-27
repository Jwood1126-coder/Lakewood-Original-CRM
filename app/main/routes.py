"""Main blueprint — home dashboard ("Today" view), inbox, health."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, select, update
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.client import Client
from app.models.invoice import Invoice
from app.models.job import Job
from app.models.notification import Notification
from app.models.quote import Quote

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

    # ---------- Pipeline / "needs attention" ----------

    quotes_draft = db.session.scalars(
        select(Quote).options(joinedload(Quote.client))
        .where(Quote.status == "draft").order_by(Quote.updated_at.desc()).limit(8)
    ).all()
    quotes_sent = db.session.scalars(
        select(Quote).options(joinedload(Quote.client))
        .where(Quote.status == "sent").order_by(Quote.sent_at.desc().nulls_last()).limit(8)
    ).all()
    quotes_accepted_unconverted = db.session.scalars(
        select(Quote).options(joinedload(Quote.client))
        .where(Quote.status == "accepted", Quote.converted_to_job_id.is_(None))
        .order_by(Quote.accepted_at.desc().nulls_last()).limit(8)
    ).all()

    jobs_needing_invoice = db.session.scalars(
        select(Job).options(joinedload(Job.client))
        .where(Job.status == "complete")
        .order_by(Job.updated_at.desc())
        .limit(20)
    ).all()
    # Filter in Python (cheap at this scale) for "no open invoice yet"
    jobs_needing_invoice = [j for j in jobs_needing_invoice if j.needs_invoicing][:8]

    invoices_unpaid = db.session.scalars(
        select(Invoice).options(joinedload(Invoice.client))
        .where(Invoice.status.in_(["sent", "partial"]))
        .order_by(Invoice.due_date.nulls_last()).limit(8)
    ).all()
    invoices_overdue = [i for i in invoices_unpaid if i.is_overdue]

    # ---------- Counts ----------

    in_progress_count = db.session.scalar(
        select(func.count(Job.id)).where(Job.status == "in_progress")
    ) or 0
    open_count = db.session.scalar(
        select(func.count(Job.id)).where(Job.status.in_(["scheduled", "in_progress"]))
    ) or 0
    client_count = db.session.scalar(select(func.count(Client.id))) or 0

    # Total open balance across all clients (cents)
    ar_total_cents = sum(i.balance_cents for i in db.session.scalars(
        select(Invoice).where(Invoice.status.in_(["sent", "partial"]))
    ).all())

    return render_template(
        "main/index.html",
        user=current_user,
        today=today,
        today_jobs=today_jobs,
        upcoming_jobs=upcoming_jobs,
        overdue_jobs=overdue_jobs,
        quotes_draft=quotes_draft,
        quotes_sent=quotes_sent,
        quotes_accepted_unconverted=quotes_accepted_unconverted,
        jobs_needing_invoice=jobs_needing_invoice,
        invoices_unpaid=invoices_unpaid,
        invoices_overdue=invoices_overdue,
        in_progress_count=in_progress_count,
        open_count=open_count,
        client_count=client_count,
        ar_total_cents=ar_total_cents,
    )


@bp.route("/inbox")
@login_required
def inbox():
    notifications = db.session.scalars(
        select(Notification).order_by(Notification.created_at.desc()).limit(50)
    ).all()
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
