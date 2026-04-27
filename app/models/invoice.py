"""Invoice — billed to a customer for completed work.

State machine:
    draft → sent → (partial | paid | void)
    overdue is computed from due_date, not stored.

Invoices can come from a Job (the normal path) OR be standalone.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.job import Job
    from app.models.line_item import LineItem
    from app.models.payment import Payment
    from app.models.property import Property

INVOICE_STATUSES = ("draft", "sent", "partial", "paid", "void")
INVOICE_STATUS_LABELS = {
    "draft":   "Draft",
    "sent":    "Sent",
    "partial": "Partial payment",
    "paid":    "Paid",
    "void":    "Void",
}


class Invoice(db.Model):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", index=True
    )
    token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True,
        default=lambda: secrets.token_urlsafe(24),
    )
    tax_rate_override: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    client:   Mapped["Client"]   = relationship("Client")
    prop:     Mapped["Property"] = relationship("Property")
    job:      Mapped["Job | None"] = relationship("Job")
    line_items: Mapped[list["LineItem"]] = relationship(
        "LineItem", primaryjoin="LineItem.invoice_id==Invoice.id",
        cascade="all, delete-orphan", order_by="LineItem.position",
        back_populates="invoice",
    )
    payments: Mapped[list["Payment"]] = relationship(
        "Payment", back_populates="invoice",
        cascade="all, delete-orphan", order_by="Payment.received_at.desc()",
    )

    @property
    def status_label(self) -> str:
        return INVOICE_STATUS_LABELS.get(self.status, self.status)

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
        amount = (Decimal(self.taxable_subtotal_cents) * self.effective_tax_rate)
        return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @property
    def total_cents(self) -> int:
        return self.subtotal_cents + self.tax_cents

    @property
    def paid_cents(self) -> int:
        return sum(p.amount_cents for p in self.payments)

    @property
    def balance_cents(self) -> int:
        return max(0, self.total_cents - self.paid_cents)

    @property
    def is_overdue(self) -> bool:
        if self.status in ("paid", "void", "draft"):
            return False
        return bool(self.due_date and self.due_date < date.today() and self.balance_cents > 0)

    @property
    def days_overdue(self) -> int:
        if not self.is_overdue:
            return 0
        return (date.today() - self.due_date).days

    def recompute_status(self) -> None:
        """Update status based on payment progress. Call after recording a payment."""
        if self.status in ("draft", "void"):
            return
        if self.paid_cents <= 0:
            self.status = "sent"
        elif self.paid_cents >= self.total_cents:
            self.status = "paid"
            if not self.paid_at:
                self.paid_at = datetime.utcnow()
        else:
            self.status = "partial"

    @staticmethod
    def next_number(session) -> int:
        from sqlalchemy import func, select
        max_num = session.scalar(select(func.max(Invoice.number))) or 1000
        return max_num + 1  # start invoices at 1001 for vibes

    def __repr__(self) -> str:
        return f"<Invoice #{self.number} [{self.status}]>"
