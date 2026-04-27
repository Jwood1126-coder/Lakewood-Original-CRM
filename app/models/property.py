"""Property — a service location tied to a Client.

A Client can own/manage multiple Properties (e.g., landlord with rentals).
Tax rate lives on the Property because Ohio is destination-based — the
rate depends on where the work happens, not who's paying.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.invoice import Invoice
    from app.models.job import Job
    from app.models.quote import Quote


class Property(db.Model):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # "Home", "Rental #1", "Mom's House", etc. Free-text label for the operator.
    label: Mapped[str] = mapped_column(String(100), nullable=False, default="Home")

    address_line1: Mapped[str] = mapped_column(String(200), nullable=False)
    address_line2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False, default="OH")
    zip_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    county: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # Tax rate as a decimal fraction, e.g. 0.0800 for 8.00%.
    # Per-property default; overridable per-Invoice in Phase 3.
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, default=Decimal("0.0575")
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    client: Mapped["Client"] = relationship("Client", back_populates="properties")
    jobs: Mapped[list["Job"]] = relationship(
        "Job", back_populates="prop",
        cascade="all, delete-orphan",
        order_by="Job.scheduled_date.desc().nulls_last()",
    )
    quotes: Mapped[list["Quote"]] = relationship(
        "Quote", back_populates="prop",
        cascade="all, delete-orphan",
        order_by="Quote.created_at.desc()",
    )
    invoices: Mapped[list["Invoice"]] = relationship(
        "Invoice", back_populates="prop",
        cascade="all, delete-orphan",
        order_by="Invoice.created_at.desc()",
    )

    @property
    def address_one_line(self) -> str:
        parts = [self.address_line1]
        if self.address_line2:
            parts.append(self.address_line2)
        parts.append(f"{self.city}, {self.state} {self.zip_code}")
        return ", ".join(parts)

    @property
    def maps_url(self) -> str:
        """A universal maps deep-link. Works in Apple Maps, Google Maps, etc."""
        from urllib.parse import quote_plus

        return f"https://www.google.com/maps/search/?api=1&query={quote_plus(self.address_one_line)}"

    @property
    def tax_rate_percent(self) -> str:
        """Render as e.g. '8.00%' for display."""
        return f"{(self.tax_rate * 100):.2f}%"

    def __repr__(self) -> str:
        return f"<Property {self.id} {self.label!r} {self.address_line1!r}>"
