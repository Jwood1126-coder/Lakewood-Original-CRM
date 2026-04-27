"""Daily / weekly / monthly briefings.

Each briefing assembles deterministic data from the DB, optionally adds a
short narrative from Claude on top, persists a Notification, and emails
the operator if the email channel is enabled and Gmail is configured.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape

from flask import current_app
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.client import Client
from app.models.job import Job
from app.models.notification import Notification
from app.models.setting import get_setting


def _today_data():
    today = date.today()
    today_jobs = db.session.scalars(
        select(Job).options(joinedload(Job.client), joinedload(Job.prop))
        .where(Job.scheduled_date == today, Job.status != "canceled")
        .order_by(Job.scheduled_time.nulls_last())
    ).all()
    overdue = db.session.scalars(
        select(Job).options(joinedload(Job.client))
        .where(Job.scheduled_date < today,
               Job.status.in_(["scheduled", "in_progress"]))
        .order_by(Job.scheduled_date)
    ).all()
    in_progress = db.session.scalars(
        select(Job).options(joinedload(Job.client))
        .where(Job.status == "in_progress")
    ).all()
    upcoming = db.session.scalars(
        select(Job).options(joinedload(Job.client), joinedload(Job.prop))
        .where(Job.scheduled_date > today,
               Job.scheduled_date <= today + timedelta(days=7),
               Job.status.in_(["scheduled", "in_progress"]))
        .order_by(Job.scheduled_date, Job.scheduled_time.nulls_last())
        .limit(8)
    ).all()
    return {
        "today": today,
        "today_jobs": today_jobs,
        "overdue": overdue,
        "in_progress": in_progress,
        "upcoming": upcoming,
    }


def _job_line_html(j: Job) -> str:
    bits = []
    if j.scheduled_time:
        bits.append(f"<b>{escape(j.time_display)}</b>")
    bits.append(escape(j.title))
    bits.append(f"— {escape(j.client.name)}")
    if j.prop:
        bits.append(f"<span style='color:#888'>· {escape(j.prop.address_line1)}</span>")
    return " ".join(bits)


def _build_html(data: dict, narrative: str | None) -> str:
    today = data["today"]
    parts = [f"<h2 style='margin:0 0 0.4rem'>Briefing — {today.strftime('%A, %b %d')}</h2>"]
    if narrative:
        parts.append(f"<p style='color:#444'><i>{escape(narrative)}</i></p>")

    parts.append("<h3>On for today</h3>")
    if data["today_jobs"]:
        parts.append("<ul>" + "".join(
            f"<li>{_job_line_html(j)}</li>" for j in data["today_jobs"]
        ) + "</ul>")
    else:
        parts.append("<p>Nothing scheduled.</p>")

    if data["overdue"]:
        parts.append("<h3 style='color:#b91c1c'>⚠ Overdue</h3>")
        parts.append("<ul>" + "".join(
            f"<li>{j.scheduled_date.isoformat()} — {escape(j.title)} ({escape(j.client.name)})</li>"
            for j in data["overdue"]
        ) + "</ul>")

    if data["in_progress"]:
        parts.append("<h3>In progress</h3>")
        parts.append("<ul>" + "".join(
            f"<li>{escape(j.title)} ({escape(j.client.name)})</li>"
            for j in data["in_progress"]
        ) + "</ul>")

    if data["upcoming"]:
        parts.append("<h3>Next 7 days</h3>")
        parts.append("<ul>" + "".join(
            f"<li>{j.scheduled_date.isoformat()} — {_job_line_html(j)}</li>"
            for j in data["upcoming"]
        ) + "</ul>")
    return "\n".join(parts)


def _claude_narrative(data: dict) -> str | None:
    """One-paragraph commentary on today's situation. Returns None if Claude
    is unavailable so the briefing degrades gracefully."""
    try:
        from app.services.assistant import _client, get_active_model, load_system_prompt
        client = _client()
    except Exception:
        return None

    bullet_lines = []
    bullet_lines.append(f"Today: {len(data['today_jobs'])} jobs scheduled.")
    if data["overdue"]:
        bullet_lines.append(
            "Overdue jobs: " +
            "; ".join(f"{j.title} ({j.client.name}, {j.scheduled_date.isoformat()})"
                      for j in data["overdue"])
        )
    if data["in_progress"]:
        bullet_lines.append(
            "In progress: " +
            "; ".join(f"{j.title} ({j.client.name})" for j in data["in_progress"])
        )
    if data["upcoming"]:
        bullet_lines.append(f"Upcoming this week: {len(data['upcoming'])} jobs.")

    user_prompt = (
        "Here's the daily briefing data:\n\n"
        + "\n".join(f"- {b}" for b in bullet_lines)
        + "\n\nWrite ONE short sentence (max 25 words) of plain commentary on today's "
          "situation for Jake. Plain text, no markdown. If there's nothing notable, "
          "say so."
    )

    try:
        resp = client.messages.create(
            model=get_active_model(),
            max_tokens=120,
            system=[{
                "type": "text",
                "text": load_system_prompt(),
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_prompt}],
        )
        text_parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        return "\n".join(text_parts).strip() or None
    except Exception as e:
        current_app.logger.warning("Claude narrative failed: %s", e)
        return None


def build_and_send_daily_briefing(force: bool = False) -> dict:
    """Build today's briefing, save as Notification, optionally email."""
    if not force and get_setting("notify_daily", "1") != "1":
        return {"skipped": True, "reason": "daily disabled"}

    data = _today_data()
    narrative = _claude_narrative(data)
    html = _build_html(data, narrative)
    title = f"Briefing — {data['today'].strftime('%A, %b %d')}"

    notif = Notification(
        kind="daily_briefing",
        title=title,
        body_html=html,
        body_text=None,
    )
    db.session.add(notif)
    db.session.commit()

    emailed = False
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
                emailed = True
            except Exception as e:
                current_app.logger.warning("Briefing email failed: %s", e)

    return {"emailed": emailed, "notification_id": notif.id, "title": title}
