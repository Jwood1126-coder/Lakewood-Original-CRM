"""LineItem — used by both Quote and Invoice via two nullable FKs.

Money stored as integer cents. Quantity is Decimal(10,2) — covers fractional
hours and percentage-of-job work without float surprises.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    from app.models.invoice import Invoice
    from app.models.quote import Quote


class LineItem(db.Model):
    __tablename__ = "line_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    quote_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=True, index=True
    )

    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("1")
    )
    unit_price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    taxable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    quote:   Mapped["Quote | None"]   = relationship("Quote",   back_populates="line_items",
                                                     foreign_keys=[quote_id])
    invoice: Mapped["Invoice | None"] = relationship("Invoice", back_populates="line_items",
                                                     foreign_keys=[invoice_id])

    __table_args__ = (
        CheckConstraint(
            "(quote_id IS NOT NULL) OR (invoice_id IS NOT NULL)",
            name="ck_line_item_has_parent",
        ),
    )

    @property
    def line_total_cents(self) -> int:
        # qty (Decimal) * unit_price_cents (int) → cents, rounded to integer
        amt = Decimal(self.unit_price_cents) * self.quantity
        return int(amt.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @property
    def unit_price_dollars(self) -> Decimal:
        return (Decimal(self.unit_price_cents) / 100).quantize(Decimal("0.01"))

    @property
    def line_total_dollars(self) -> Decimal:
        return (Decimal(self.line_total_cents) / 100).quantize(Decimal("0.01"))
