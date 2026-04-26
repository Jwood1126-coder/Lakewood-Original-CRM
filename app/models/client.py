"""Client (customer) model — the root of the CRM."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    from app.models.property import Property


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
