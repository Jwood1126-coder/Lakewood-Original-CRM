"""InboxMessage — unified inbox for client communications.

Phase 1 stores raw rows from Gmail (which receives both Voice SMS/voicemail
emails and forwarded business mail). Parser fills `kind`, `from_phone`,
and `client_id` in subsequent phases. Until then, rows have kind='email',
client_id=None, and the operator sees a flat list.

Storage: timestamps are UTC-naive per the project convention (see
app/utils/timezone.py).
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.job import Job


# Allowed values
KINDS = ("email", "sms", "voicemail", "unknown")
SOURCES = ("gmail",)  # 'graph', 'twilio' may be added later
DIRECTIONS = ("in", "out")


class InboxMessage(db.Model):
    __tablename__ = "inbox_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    source: Mapped[str] = mapped_column(String(20), nullable=False)
    source_message_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_thread_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="email")
    direction: Mapped[str] = mapped_column(String(4), nullable=False, default="in")

    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )

    from_addr:  Mapped[str | None] = mapped_column(String(320), nullable=True)
    from_name:  Mapped[str | None] = mapped_column(String(200), nullable=True)
    from_phone: Mapped[str | None] = mapped_column(String(20),  nullable=True)

    subject:   Mapped[str | None] = mapped_column(String(500), nullable=True)
    snippet:   Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    read_at:     Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at:  Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    client: Mapped["Client | None"] = relationship("Client", lazy="joined")
    job: Mapped["Job | None"] = relationship("Job", lazy="select")

    __table_args__ = (
        UniqueConstraint(
            "source", "source_message_id",
            name="uq_inbox_messages_source_msgid",
        ),
    )

    @property
    def is_unread(self) -> bool:
        return self.read_at is None

    @property
    def kind_label(self) -> str:
        return {
            "email":     "Email",
            "sms":       "SMS",
            "voicemail": "Voicemail",
            "unknown":   "Message",
        }.get(self.kind, self.kind)

    def __repr__(self) -> str:
        return f"<InboxMessage {self.id} {self.kind} from={self.from_addr!r}>"
