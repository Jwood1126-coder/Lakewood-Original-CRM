"""conversations, messages, notifications

Revision ID: 0004_assistant_and_notifications
Revises: 0003_user_theme_and_settings
Create Date: 2026-04-26 23:30:00

"""
from alembic import op
import sqlalchemy as sa


revision = "0004_assistant_and_notifications"
down_revision = "0003_user_theme_and_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("tool_calls_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE",
            name="fk_messages_conversation_id",
        ),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_email_at", sa.DateTime(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_notifications_kind", "notifications", ["kind"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])


def downgrade():
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_kind", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_table("conversations")
