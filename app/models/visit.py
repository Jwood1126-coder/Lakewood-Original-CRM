"""Visit — one trip to the job site.

Track arrived_at / departed_at separately from scheduled_date so the
"how much time did I actually spend" question is answerable.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    from app.models.job import Job


class Visit(db.Model):
    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    arrived_at:  Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    departed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    miles: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    job: Mapped["Job"] = relationship("Job", back_populates="visits")

    @property
    def is_active(self) -> bool:
        """A visit is 'active' (in progress) when arrived but not departed."""
        return self.arrived_at is not None and self.departed_at is None

    @property
    def duration(self) -> timedelta | None:
        if self.arrived_at and self.departed_at:
            return self.departed_at - self.arrived_at
        return None

    @property
    def duration_display(self) -> str:
        d = self.duration
        if d is None:
            return "—"
        total_min = int(d.total_seconds() // 60)
        if total_min < 60:
            return f"{total_min} min"
        h, m = divmod(total_min, 60)
        return f"{h}h {m}m" if m else f"{h}h"

    def __repr__(self) -> str:
        return f"<Visit {self.id} job={self.job_id} {self.scheduled_date}>"
