"""AuditLog — every change to durable data, captured automatically.

Populated by a SQLAlchemy `before_flush` event listener (see
app/services/audit.py). Each row records:
  - operation: insert | update | delete
  - entity_type, entity_id: what was touched
  - before_json / after_json: the values
  - actor_email: who did it (from current_user when available)

Read-only from the UI. Never deleted (would defeat the point).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )
    operation: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    # 'user' = via Flask-Login session; 'system' = scheduled job; 'cli' = scripts

    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Free-text summary for the list view (e.g. "Job #42 status: scheduled → complete")
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:
        return f"<AuditLog {self.operation} {self.entity_type}:{self.entity_id}>"
