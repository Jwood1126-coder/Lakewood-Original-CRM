"""Quote (estimate) — sent to a customer for acceptance.

State machine:
    draft → sent → (accepted | declined | expired)
    accepted may also be (later) → converted (when turned into a Job)
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.job import Job
    from app.models.line_item import LineItem
    from app.models.photo import Photo
    from app.models.property import Property

QUOTE_STATUSES = ("draft", "sent", "accepted", "declined", "expired", "converted")
QUOTE_STATUS_LABELS = {
    "draft":     "Draft",
    "sent":      "Sent",
    "accepted":  "Accepted",
    "declined":  "Declined",
    "expired":   "Expired",
    "converted": "Converted",
}


class Quote(db.Model):
    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )

    number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    message_to_customer: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", index=True
    )
    token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True,
        default=lambda: secrets.token_urlsafe(24),
    )

    # If unset, falls back to property's tax_rate
    tax_rate_override: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Optional scheduled site visit — used for free-estimate appointments
    # before any line items exist. Surfaces on Schedule + Calendar.
    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    scheduled_time: Mapped[time | None] = mapped_column(Time, nullable=True)

    converted_to_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    sent_at:     Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    declined_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    client:   Mapped["Client"]   = relationship("Client")
    prop:     Mapped["Property"] = relationship("Property")
    line_items: Mapped[list["LineItem"]] = relationship(
        "LineItem", primaryjoin="LineItem.quote_id==Quote.id",
        cascade="all, delete-orphan", order_by="LineItem.position",
        back_populates="quote",
    )
    converted_job: Mapped["Job | None"] = relationship(
        "Job", primaryjoin="Quote.converted_to_job_id==Job.id"
    )
    photos: Mapped[list["Photo"]] = relationship(
        "Photo", primaryjoin="Photo.quote_id==Quote.id",
        cascade="all, delete-orphan", order_by="Photo.created_at.desc()",
    )

    @property
    def status_label(self) -> str:
        return QUOTE_STATUS_LABELS.get(self.status, self.status)

    @property
    def effective_tax_rate(self) -> Decimal:
        if self.tax_rate_override is not None:
            return self.tax_rate_override
        return self.prop.tax_rate if self.prop else Decimal("0")

    @property
    def subtotal_cents(self) -> int:
        return sum(li.line_total_cents for li in self.line_items)

    @property
    def taxable_subtotal_cents(self) -> int:
        return sum(li.line_total_cents for li in self.line_items if li.taxable)

    @property
    def tax_cents(self) -> int:
        if self.taxable_subtotal_cents <= 0 or self.effective_tax_rate <= 0:
            return 0
        # Cents arithmetic: (taxable_cents/100) * rate, rounded to cent
        amount = (Decimal(self.taxable_subtotal_cents) * self.effective_tax_rate)
        return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @property
    def total_cents(self) -> int:
        return self.subtotal_cents + self.tax_cents

    @property
    def is_expired(self) -> bool:
        if self.status not in ("sent",):
            return False
        return bool(self.valid_until and self.valid_until < date.today())

    @property
    def time_display(self) -> str:
        """12-hour clock format for the scheduled visit time. Mirrors Job.time_display."""
        t = self.scheduled_time
        if not t:
            return "—"
        h = t.hour
        m = t.minute
        suffix = "AM" if h < 12 else "PM"
        h12 = h if 1 <= h <= 12 else (12 if h == 0 else h - 12)
        return f"{h12}:{m:02d} {suffix}"

    @staticmethod
    def next_number(session) -> int:
        """Sequential human-friendly quote number (Q-1, Q-2, …)."""
        from sqlalchemy import func, select
        max_num = session.scalar(select(func.max(Quote.number))) or 0
        return max_num + 1

    def __repr__(self) -> str:
        return f"<Quote Q-{self.number} [{self.status}]>"
