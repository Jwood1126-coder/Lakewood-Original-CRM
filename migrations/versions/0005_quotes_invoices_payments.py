"""quotes, invoices, line_items, payments + photo FKs to quotes/invoices

Revision ID: 0005_quotes_invoices_payments
Revises: 0004_assistant_and_notifications
Create Date: 2026-04-27 02:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "0005_quotes_invoices_payments"
down_revision = "0004_assistant_and_notifications"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "quotes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("message_to_customer", sa.Text(), nullable=True),
        sa.Column("internal_notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("tax_rate_override", sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("converted_to_job_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("declined_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE",
                                name="fk_quotes_client_id"),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE",
                                name="fk_quotes_property_id"),
        sa.ForeignKeyConstraint(["converted_to_job_id"], ["jobs.id"], ondelete="SET NULL",
                                name="fk_quotes_converted_to_job_id"),
        sa.UniqueConstraint("number", name="uq_quotes_number"),
        sa.UniqueConstraint("token",  name="uq_quotes_token"),
    )
    op.create_index("ix_quotes_client_id", "quotes", ["client_id"])
    op.create_index("ix_quotes_property_id", "quotes", ["property_id"])
    op.create_index("ix_quotes_status", "quotes", ["status"])

    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("tax_rate_override", sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE",
                                name="fk_invoices_client_id"),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE",
                                name="fk_invoices_property_id"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL",
                                name="fk_invoices_job_id"),
        sa.UniqueConstraint("number", name="uq_invoices_number"),
        sa.UniqueConstraint("token",  name="uq_invoices_token"),
    )
    op.create_index("ix_invoices_client_id", "invoices", ["client_id"])
    op.create_index("ix_invoices_property_id", "invoices", ["property_id"])
    op.create_index("ix_invoices_job_id", "invoices", ["job_id"])
    op.create_index("ix_invoices_status", "invoices", ["status"])

    op.create_table(
        "line_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("quote_id", sa.Integer(), nullable=True),
        sa.Column("invoice_id", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=10, scale=2), nullable=False, server_default="1"),
        sa.Column("unit_price_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("taxable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"], ondelete="CASCADE",
                                name="fk_line_items_quote_id"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE",
                                name="fk_line_items_invoice_id"),
        sa.CheckConstraint("(quote_id IS NOT NULL) OR (invoice_id IS NOT NULL)",
                            name="ck_line_item_has_parent"),
    )
    op.create_index("ix_line_items_quote_id", "line_items", ["quote_id"])
    op.create_index("ix_line_items_invoice_id", "line_items", ["invoice_id"])

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False, server_default="check"),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE",
                                name="fk_payments_invoice_id"),
    )
    op.create_index("ix_payments_invoice_id", "payments", ["invoice_id"])


def downgrade():
    op.drop_index("ix_payments_invoice_id", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_line_items_invoice_id", table_name="line_items")
    op.drop_index("ix_line_items_quote_id", table_name="line_items")
    op.drop_table("line_items")
    op.drop_index("ix_invoices_status", table_name="invoices")
    op.drop_index("ix_invoices_job_id", table_name="invoices")
    op.drop_index("ix_invoices_property_id", table_name="invoices")
    op.drop_index("ix_invoices_client_id", table_name="invoices")
    op.drop_table("invoices")
    op.drop_index("ix_quotes_status", table_name="quotes")
    op.drop_index("ix_quotes_property_id", table_name="quotes")
    op.drop_index("ix_quotes_client_id", table_name="quotes")
    op.drop_table("quotes")
