"""Job (work order) — what was promised + when it's happening.

Visits live under Job and capture the actual on-site time.
Status is a simple state machine: scheduled -> in_progress -> complete
(or canceled at any point).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.property import Property
    from app.models.visit import Visit

JOB_STATUSES = ("scheduled", "in_progress", "complete", "canceled")
JOB_STATUS_LABELS = {
    "scheduled":   "Scheduled",
    "in_progress": "In progress",
    "complete":    "Complete",
    "canceled":    "Canceled",
}

# Allowed transitions (scheduled <-> in_progress, in_progress -> complete, etc.)
_ALLOWED_TRANSITIONS = {
    "scheduled":   {"in_progress", "complete", "canceled"},
    "in_progress": {"scheduled", "complete", "canceled"},
    "complete":    {"in_progress"},     # reopen if mistakenly closed
    "canceled":    {"scheduled"},       # uncancel
}


class Job(db.Model):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="scheduled", index=True
    )

    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    scheduled_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    est_hours: Mapped[float | None] = mapped_column(nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    client: Mapped["Client"] = relationship("Client")
    prop: Mapped["Property"] = relationship("Property")
    visits: Mapped[list["Visit"]] = relationship(
        "Visit",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="Visit.scheduled_date.desc(), Visit.arrived_at.desc()",
    )

    # ---------- Computed helpers ----------

    @property
    def status_label(self) -> str:
        return JOB_STATUS_LABELS.get(self.status, self.status)

    @property
    def time_display(self) -> str:
        if not self.scheduled_time:
            return "—"
        h = self.scheduled_time.hour
        m = self.scheduled_time.minute
        suffix = "AM" if h < 12 else "PM"
        h12 = h if 1 <= h <= 12 else (12 if h == 0 else h - 12)
        return f"{h12}:{m:02d} {suffix}"

    @property
    def total_visit_hours(self) -> float:
        total = timedelta()
        for v in self.visits:
            d = v.duration
            if d:
                total += d
        return round(total.total_seconds() / 3600, 2)

    @property
    def total_miles(self) -> int:
        return sum((v.miles or 0) for v in self.visits)

    def can_transition_to(self, new_status: str) -> bool:
        if new_status not in JOB_STATUSES:
            return False
        return new_status in _ALLOWED_TRANSITIONS.get(self.status, set())

    def transition_to(self, new_status: str) -> None:
        if not self.can_transition_to(new_status):
            raise ValueError(
                f"Cannot transition job {self.id} from {self.status!r} to {new_status!r}"
            )
        self.status = new_status

    def __repr__(self) -> str:
        return f"<Job {self.id} {self.title!r} [{self.status}]>"
