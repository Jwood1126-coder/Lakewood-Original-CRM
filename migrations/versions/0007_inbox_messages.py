"""inbox_messages — unified inbox for client communications

Revision ID: 0007_inbox_messages
Revises: 0006_audit_log_and_soft_delete
Create Date: 2026-05-07 00:00:00

Phase 1 schema: just enough to store raw Gmail messages with optional
client linkage. Parser/matching come in a later migration if needed
(those are pure derived fields and don't change the schema).
"""
from alembic import op
import sqlalchemy as sa


revision = "0007_inbox_messages"
down_revision = "0006_audit_log_and_soft_delete"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "inbox_messages",
        sa.Column("id", sa.Integer(), primary_key=True),

        # Source provenance — which mailbox + which provider's id
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("source_message_id", sa.String(length=200), nullable=False),
        sa.Column("source_thread_id", sa.String(length=200), nullable=True),

        # Classification ('email' | 'sms' | 'voicemail' | 'unknown')
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="email"),
        sa.Column("direction", sa.String(length=4), nullable=False, server_default="in"),

        # Optional client/job linkage (set by parser; null until matched)
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),

        # Sender info — kept as raw strings; parser fills phone if SMS
        sa.Column("from_addr", sa.String(length=320), nullable=True),
        sa.Column("from_name", sa.String(length=200), nullable=True),
        sa.Column("from_phone", sa.String(length=20), nullable=True),

        # Body
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),

        # Timestamps
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),

        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], ondelete="SET NULL",
            name="fk_inbox_messages_client_id",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], ondelete="SET NULL",
            name="fk_inbox_messages_job_id",
        ),
        sa.UniqueConstraint(
            "source", "source_message_id",
            name="uq_inbox_messages_source_msgid",
        ),
    )
    op.create_index(
        "ix_inbox_messages_received_at", "inbox_messages", ["received_at"]
    )
    op.create_index(
        "ix_inbox_messages_client_id", "inbox_messages", ["client_id"]
    )


def downgrade():
    op.drop_index("ix_inbox_messages_client_id", table_name="inbox_messages")
    op.drop_index("ix_inbox_messages_received_at", table_name="inbox_messages")
    op.drop_table("inbox_messages")
