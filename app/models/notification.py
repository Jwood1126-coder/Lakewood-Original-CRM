"""Notification — briefings, reminders, reports.

Stored in the DB so the in-app inbox shows them and the email worker can
mark them as sent.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class Notification(db.Model):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 'daily_briefing' | 'weekly_briefing' | 'monthly_report' | 'job_day_reminder'
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )
    sent_email_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def is_unread(self) -> bool:
        return self.read_at is None
