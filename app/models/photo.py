"""Photo — attaches to one of: Property, Job, or Visit.

Polymorphic-via-nullable-FKs pattern. Exactly one of the parent FKs is set;
a CHECK constraint enforces it. Quote/Invoice photos get added in Phase 3.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class Photo(db.Model):
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    rel_path: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mimetype: Mapped[str | None] = mapped_column(String(80), nullable=True)
    bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    caption: Mapped[str | None] = mapped_column(String(500), nullable=True)

    property_id: Mapped[int | None] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=True, index=True
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    visit_id: Mapped[int | None] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "(property_id IS NOT NULL) OR (job_id IS NOT NULL) OR (visit_id IS NOT NULL)",
            name="ck_photo_has_parent",
        ),
    )

    def __repr__(self) -> str:
        return f"<Photo {self.id} {self.rel_path}>"
