"""Client (customer) model — the root of the CRM."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    from app.models.invoice import Invoice
    from app.models.job import Job
    from app.models.property import Property
    from app.models.quote import Quote


class Client(db.Model):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    properties: Mapped[list["Property"]] = relationship(
        "Property",
        back_populates="client",
        cascade="all, delete-orphan",
        order_by="Property.label",
    )
    jobs: Mapped[list["Job"]] = relationship(
        "Job", back_populates="client",
        cascade="all, delete-orphan",
        order_by="Job.scheduled_date.desc().nulls_last(), Job.created_at.desc()",
    )
    quotes: Mapped[list["Quote"]] = relationship(
        "Quote", back_populates="client",
        cascade="all, delete-orphan",
        order_by="Quote.created_at.desc()",
    )
    invoices: Mapped[list["Invoice"]] = relationship(
        "Invoice", back_populates="client",
        cascade="all, delete-orphan",
        order_by="Invoice.created_at.desc()",
    )

    @property
    def balance_owed_cents(self) -> int:
        """Total open balance across all this customer's invoices."""
        return sum(
            inv.balance_cents
            for inv in (self.invoices or [])
            if inv.status not in ("draft", "void", "paid")
        )

    @property
    def balance_owed_dollars(self) -> Decimal:
        return (Decimal(self.balance_owed_cents) / 100).quantize(Decimal("0.01"))

    @property
    def primary_property(self) -> "Property | None":
        return self.properties[0] if self.properties else None

    @property
    def display_phone(self) -> str:
        """Format a 10-digit US phone as (xxx) xxx-xxxx."""
        if not self.phone:
            return ""
        digits = "".join(c for c in self.phone if c.isdigit())
        if len(digits) == 10:
            return f"({digits[0:3]}) {digits[3:6]}-{digits[6:]}"
        if len(digits) == 11 and digits.startswith("1"):
            return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        return self.phone

    def __repr__(self) -> str:
        return f"<Client {self.id} {self.name!r}>"
