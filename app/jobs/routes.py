"""Job + Visit routes."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.jobs.forms import JobForm, VisitForm
from app.models.client import Client
from app.models.job import JOB_STATUS_LABELS, JOB_STATUSES, Job
from app.models.property import Property
from app.models.visit import Visit

bp = Blueprint("jobs", __name__, template_folder="../templates/jobs")


# ---------- helpers ----------

def _populate_form_choices(form: JobForm, preselect_client_id: int | None = None) -> None:
    """Fill client/property selects with current rows."""
    clients = db.session.scalars(select(Client).order_by(Client.name)).all()
    form.client_id.choices = [(c.id, c.name) for c in clients]
    if not form.client_id.choices:
        form.client_id.choices = [(0, "— add a client first —")]

    chosen_client_id = preselect_client_id or form.client_id.data
    if chosen_client_id:
        props = db.session.scalars(
            select(Property)
            .where(Property.client_id == chosen_client_id)
            .order_by(Property.label)
        ).all()
        form.property_id.choices = [
            (p.id, f"{p.label} — {p.address_line1}") for p in props
        ]
        if not form.property_id.choices:
            form.property_id.choices = [(0, "— add a property to this client first —")]
    else:
        form.property_id.choices = []


# ---------- routes ----------

@bp.route("/")
@login_required
def list_jobs():
    status = request.args.get("status")
    stmt = (
        select(Job)
        .options(joinedload(Job.client), joinedload(Job.prop))
        .order_by(Job.scheduled_date.desc().nulls_last(), Job.scheduled_time.desc().nulls_last())
    )
    if status and status in JOB_STATUSES:
        stmt = stmt.where(Job.status == status)
    jobs = db.session.scalars(stmt).all()
    return render_template(
        "jobs/list.html",
        jobs=jobs,
        status=status,
        statuses=JOB_STATUSES,
        status_labels=JOB_STATUS_LABELS,
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_job():
    preselect_client = request.args.get("client_id", type=int)
    preselect_property = request.args.get("property_id", type=int)
    repeat_from = request.args.get("repeat_from", type=int)

    form = JobForm()

    # Pre-fill from a previous job (the "Repeat last job" path)
    if request.method == "GET" and repeat_from:
        src = db.session.get(Job, repeat_from)
        if src:
            form.title.data = src.title
            form.client_id.data = src.client_id
            form.property_id.data = src.property_id
            form.scope.data = src.scope
            form.est_hours.data = src.est_hours
            preselect_client = preselect_client or src.client_id

    # Default empty preselects from query string
    if request.method == "GET" and preselect_client and not form.client_id.data:
        form.client_id.data = preselect_client
    if request.method == "GET" and preselect_property and not form.property_id.data:
        form.property_id.data = preselect_property

    _populate_form_choices(form, preselect_client_id=form.client_id.data)

    if form.validate_on_submit():
        job = Job(
            client_id=form.client_id.data,
            property_id=form.property_id.data,
            title=form.title.data.strip(),
            scope=(form.scope.data or "").strip() or None,
            scheduled_date=form.scheduled_date.data,
            scheduled_time=form.scheduled_time.data,
            est_hours=float(form.est_hours.data) if form.est_hours.data is not None else None,
            notes=(form.notes.data or "").strip() or None,
            status="scheduled",
        )
        db.session.add(job)
        db.session.commit()
        flash(f"Created job: {job.title}", "success")
        return redirect(url_for("jobs.view_job", job_id=job.id))

    return render_template("jobs/edit.html", form=form, job=None)


@bp.route("/<int:job_id>")
@login_required
def view_job(job_id: int):
    job = db.session.get(Job, job_id) or abort(404)
    visit_form = VisitForm(scheduled_date=date.today())
    return render_template("jobs/view.html", job=job, visit_form=visit_form)


@bp.route("/<int:job_id>/edit", methods=["GET", "POST"])
@login_required
def edit_job(job_id: int):
    job = db.session.get(Job, job_id) or abort(404)
    form = JobForm(obj=job)
    if request.method == "GET":
        # WTForms doesn't pull these properly via obj — set by hand
        form.client_id.data = job.client_id
        form.property_id.data = job.property_id

    _populate_form_choices(form, preselect_client_id=form.client_id.data)

    if form.validate_on_submit():
        job.client_id = form.client_id.data
        job.property_id = form.property_id.data
        job.title = form.title.data.strip()
        job.scope = (form.scope.data or "").strip() or None
        job.scheduled_date = form.scheduled_date.data
        job.scheduled_time = form.scheduled_time.data
        job.est_hours = float(form.est_hours.data) if form.est_hours.data is not None else None
        job.notes = (form.notes.data or "").strip() or None
        db.session.commit()
        flash("Saved.", "success")
        return redirect(url_for("jobs.view_job", job_id=job.id))

    return render_template("jobs/edit.html", form=form, job=job)


@bp.route("/<int:job_id>/delete", methods=["POST"])
@login_required
def delete_job(job_id: int):
    job = db.session.get(Job, job_id) or abort(404)
    db.session.delete(job)
    db.session.commit()
    flash("Job deleted.", "info")
    return redirect(url_for("jobs.list_jobs"))


@bp.route("/<int:job_id>/status/<new_status>", methods=["POST"])
@login_required
def change_status(job_id: int, new_status: str):
    job = db.session.get(Job, job_id) or abort(404)
    if not job.can_transition_to(new_status):
        flash(f"Can't go from {job.status_label} to {JOB_STATUS_LABELS.get(new_status, new_status)}.", "error")
    else:
        job.transition_to(new_status)
        db.session.commit()
        flash(f"Job marked {job.status_label}.", "success")
    return redirect(url_for("jobs.view_job", job_id=job.id))


# ---------- Visits ----------

@bp.route("/<int:job_id>/visits/start", methods=["POST"])
@login_required
def start_visit(job_id: int):
    """One-tap field action: record arrival, mark job in_progress."""
    job = db.session.get(Job, job_id) or abort(404)

    # Block double-start: if there's an active visit, just go back
    active = next((v for v in job.visits if v.is_active), None)
    if active:
        flash("Visit already in progress — end it first.", "warning")
        return redirect(url_for("jobs.view_job", job_id=job.id))

    now = datetime.utcnow()
    visit = Visit(
        job_id=job.id,
        scheduled_date=date.today(),
        arrived_at=now,
    )
    db.session.add(visit)
    if job.status == "scheduled":
        job.status = "in_progress"
    db.session.commit()
    flash("Visit started — clock running.", "success")
    return redirect(url_for("jobs.view_job", job_id=job.id))


@bp.route("/<int:job_id>/visits/end", methods=["POST"])
@login_required
def end_visit(job_id: int):
    job = db.session.get(Job, job_id) or abort(404)
    active = next((v for v in job.visits if v.is_active), None)
    if not active:
        flash("No active visit to end.", "warning")
    else:
        active.departed_at = datetime.utcnow()
        db.session.commit()
        flash(f"Visit ended ({active.duration_display}).", "success")
    return redirect(url_for("jobs.view_job", job_id=job.id))


@bp.route("/<int:job_id>/visits/log", methods=["POST"])
@login_required
def log_visit(job_id: int):
    """Log a past visit manually (didn't tap start/end in real time)."""
    job = db.session.get(Job, job_id) or abort(404)
    form = VisitForm()
    if not form.validate_on_submit():
        for field, errs in form.errors.items():
            for e in errs:
                flash(f"{field}: {e}", "error")
        return redirect(url_for("jobs.view_job", job_id=job.id))

    arrived_dt = None
    departed_dt = None
    if form.arrived_at_time.data:
        arrived_dt = datetime.combine(form.scheduled_date.data, form.arrived_at_time.data)
    if form.departed_at_time.data:
        departed_dt = datetime.combine(form.scheduled_date.data, form.departed_at_time.data)

    visit = Visit(
        job_id=job.id,
        scheduled_date=form.scheduled_date.data,
        arrived_at=arrived_dt,
        departed_at=departed_dt,
        miles=form.miles.data,
        notes=(form.notes.data or "").strip() or None,
    )
    db.session.add(visit)
    db.session.commit()
    flash("Visit logged.", "success")
    return redirect(url_for("jobs.view_job", job_id=job.id))


@bp.route("/visits/<int:visit_id>/delete", methods=["POST"])
@login_required
def delete_visit(visit_id: int):
    visit = db.session.get(Visit, visit_id) or abort(404)
    job_id = visit.job_id
    db.session.delete(visit)
    db.session.commit()
    flash("Visit deleted.", "info")
    return redirect(url_for("jobs.view_job", job_id=job_id))


# ---------- Calendar ----------

@bp.route("/calendar")
@login_required
def calendar():
    """Week view. ?week=YYYY-MM-DD picks any day in the desired week (defaults to today)."""
    anchor_str = request.args.get("week")
    try:
        anchor = date.fromisoformat(anchor_str) if anchor_str else date.today()
    except ValueError:
        anchor = date.today()

    monday = anchor - timedelta(days=anchor.weekday())
    sunday = monday + timedelta(days=6)
    days = [monday + timedelta(days=i) for i in range(7)]

    jobs = db.session.scalars(
        select(Job)
        .options(joinedload(Job.client), joinedload(Job.prop))
        .where(Job.scheduled_date >= monday, Job.scheduled_date <= sunday)
        .order_by(Job.scheduled_date, Job.scheduled_time.nulls_last())
    ).all()

    by_day: dict[date, list[Job]] = {d: [] for d in days}
    for j in jobs:
        if j.scheduled_date in by_day:
            by_day[j.scheduled_date].append(j)

    return render_template(
        "jobs/calendar.html",
        days=days,
        by_day=by_day,
        today=date.today(),
        prev_week=(monday - timedelta(days=7)).isoformat(),
        next_week=(monday + timedelta(days=7)).isoformat(),
        this_week=date.today().isoformat(),
        week_label=_fmt_week_label(monday, sunday),
    )


_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _fmt_week_label(monday: date, sunday: date) -> str:
    if monday.month == sunday.month:
        return (f"{_MONTH_ABBR[monday.month - 1]} {monday.day}–{sunday.day}, "
                f"{sunday.year}")
    return (f"{_MONTH_ABBR[monday.month - 1]} {monday.day} – "
            f"{_MONTH_ABBR[sunday.month - 1]} {sunday.day}, {sunday.year}")


# ---------- Property → properties dropdown helper for HTMX (Job form) ----------

@bp.route("/_property_options")
@login_required
def property_options():
    """HTMX endpoint: return <option> tags for a chosen client."""
    client_id = request.args.get("client_id", type=int)
    if not client_id:
        return ""
    props = db.session.scalars(
        select(Property)
        .where(Property.client_id == client_id)
        .order_by(Property.label)
    ).all()
    if not props:
        return '<option value="">— add a property to this client —</option>'
    parts = []
    for p in props:
        parts.append(f'<option value="{p.id}">{p.label} — {p.address_line1}</option>')
    return "\n".join(parts)
