"""audit_log table

Revision ID: 0006_audit_log_and_soft_delete
Revises: 0005_quotes_invoices_payments
Create Date: 2026-04-27 03:00:00

NOTE: We add the audit_log table here. Soft delete (deleted_at columns)
is intentionally NOT added in this revision — the audit log already
captures every delete with full before-snapshot, which is sufficient for
the "no records lost" requirement (you can always reconstruct a row from
the audit_log.before_json). Soft delete adds a lot of query-filtering
surface area; we'll add it later if it proves needed in practice.
"""
from alembic import op
import sqlalchemy as sa


revision = "0006_audit_log_and_soft_delete"
down_revision = "0005_quotes_invoices_payments"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("operation", sa.String(length=10), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("actor_kind", sa.String(length=20), nullable=False, server_default="user"),
        sa.Column("before_json", sa.Text(), nullable=True),
        sa.Column("after_json", sa.Text(), nullable=True),
        sa.Column("summary", sa.String(length=500), nullable=True),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_operation", "audit_log", ["operation"])
    op.create_index("ix_audit_log_entity_type", "audit_log", ["entity_type"])
    op.create_index("ix_audit_log_entity_id", "audit_log", ["entity_id"])


def downgrade():
    op.drop_index("ix_audit_log_entity_id", table_name="audit_log")
    op.drop_index("ix_audit_log_entity_type", table_name="audit_log")
    op.drop_index("ix_audit_log_operation", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_table("audit_log")
