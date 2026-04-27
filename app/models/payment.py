"""Payment — recorded against an Invoice. Multiple payments per invoice OK."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    from app.models.invoice import Invoice

PAYMENT_METHODS = ("cash", "check", "zelle", "venmo", "card", "other")
PAYMENT_METHOD_LABELS = {
    "cash":  "Cash",
    "check": "Check",
    "zelle": "Zelle",
    "venmo": "Venmo",
    "card":  "Card / Stripe",
    "other": "Other",
}


class Payment(db.Model):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )

    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="check")
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    received_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="payments")

    @property
    def amount_dollars(self) -> Decimal:
        return (Decimal(self.amount_cents) / 100).quantize(Decimal("0.01"))

    @property
    def method_label(self) -> str:
        return PAYMENT_METHOD_LABELS.get(self.method, self.method)
