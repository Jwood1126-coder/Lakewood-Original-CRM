"""Photo — attaches to multiple parents (Property/Quote/Visit/Invoice).

We use the "polymorphic association via nullable FKs" pattern rather than
SQLAlchemy's polymorphic_identity machinery. Reason: it's a third of the
code, indexes are obvious, and it scales fine to <100k photos.

Exactly one of (property_id, visit_id, quote_id, invoice_id) is set.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class Photo(db.Model):
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Relative path under PHOTO_DIR. Stored as forward-slash even on Windows.
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
    # The other parent FKs (visit/quote/invoice) get added in their respective
    # phases via Alembic migrations — leaving them out now keeps the table tight.

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        # At least one parent must be set. (Currently only property_id, but the
        # check is written as a guard so adding more FKs later doesn't break it.)
        CheckConstraint(
            "property_id IS NOT NULL",
            name="ck_photo_has_parent",
        ),
    )

    def __repr__(self) -> str:
        return f"<Photo {self.id} {self.rel_path}>"
