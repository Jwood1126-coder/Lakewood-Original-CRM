"""Reminder rules engine.

Runs hourly. For each rule that's enabled, checks DB state and emits
Notifications (and emails) for any conditions that match — using a small
"already-sent" guard to prevent duplicates.

v1 implements:
- job_day_reminder: at 06:00 local each day, send a heads-up about today's jobs
  IF the daily briefing isn't already covering it.

Phase 3+ will add:
- quote_followup at 3 days
- invoice_followup at 7/14/30 days past due
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape

from flask import current_app
from sqlalchemy import and_, select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.job import Job
from app.models.notification import Notification
from app.models.setting import get_setting


def _already_sent_today(kind: str) -> bool:
    """M1 fix: was using `date.today()` (server-local, which is UTC on Railway).
    That disagreed with the scheduler's APP_TIMEZONE 'today' for ~4-5 hours
    around midnight Eastern. Now: convert operator-local midnight back to
    naive UTC for the comparison against Notification.created_at (utcnow)."""
    from datetime import timezone
    from app.utils.timezone import app_tz, today_local
    local_midnight = datetime.combine(today_local(),
                                       datetime.min.time(),
                                       tzinfo=app_tz())
    utc_midnight_naive = local_midnight.astimezone(timezone.utc).replace(tzinfo=None)
    return db.session.scalar(
        select(Notification.id).where(
            Notification.kind == kind,
            Notification.created_at >= utc_midnight_naive,
        )
    ) is not None


def tick_reminders() -> dict:
    fired = []

    # Job-day reminder: only between 5:30am and 7:30am local, and only if not
    # already sent today, and only if there's something to remind about, and
    # only if the daily briefing isn't already enabled at a similar time.
    # H3 fix: was `not get_setting(...) == "1"` which parses as
    # `(not "1") == "1"` → `False == "1"` → always False → reminder never
    # fired. Use explicit `!=`.
    daily_briefing_on = get_setting("notify_daily", "1") == "1"
    if get_setting("notify_job_day", "1") == "1" and not daily_briefing_on:
        from app.utils.timezone import now_local, today_local
        now = now_local()
        if 5 <= now.hour <= 7 and not _already_sent_today("job_day_reminder"):
            today = today_local()
            jobs_today = db.session.scalars(
                select(Job).options(joinedload(Job.client), joinedload(Job.prop))
                .where(Job.scheduled_date == today, Job.status != "canceled")
                .order_by(Job.scheduled_time.nulls_last())
            ).all()
            if jobs_today:
                _emit_job_day_reminder(today, jobs_today)
                fired.append("job_day_reminder")

    return {"fired": fired}


def _emit_job_day_reminder(today: date, jobs):
    title = f"Today's jobs ({len(jobs)})"
    items = []
    for j in jobs:
        time_str = j.time_display if j.scheduled_time else "anytime"
        addr = j.prop.address_line1 if j.prop else ""
        items.append(
            f"<li><b>{escape(time_str)}</b> — {escape(j.title)} "
            f"({escape(j.client.name)}){' · ' + escape(addr) if addr else ''}</li>"
        )
    html = (f"<h3>{escape(title)} — {today.strftime('%A, %b %d')}</h3>"
            f"<ul>{''.join(items)}</ul>")

    notif = Notification(kind="job_day_reminder", title=title, body_html=html)
    db.session.add(notif)
    db.session.commit()

    if get_setting("notify_email", "1") == "1":
        to = (get_setting("notify_email_to")
              or current_app.config.get("NOTIFY_EMAIL")
              or "").strip()
        if to and current_app.config.get("SMTP_USER"):
            try:
                from app.services.email import send_email
                send_email(to=to, subject=title, html=html)
                notif.sent_email_at = datetime.utcnow()
                db.session.commit()
            except Exception as e:
                current_app.logger.warning("Reminder email failed: %s", e)
