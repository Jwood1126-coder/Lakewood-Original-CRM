"""custom_fields JSON + jobs.ended_at — Jobber data we weren't capturing

Revision ID: 0010_jobber_custom_fields
Revises: 0009_user_accent
Create Date: 2026-05-08 14:00:00

Adds a custom_fields JSON column to clients/properties/jobs/quotes/invoices
so Jobber's per-entity custom fields (gate codes, sq ft, lead source,
etc.) can be pulled and preserved before the user cancels Jobber.

Also adds jobs.ended_at — Jobber's GraphQL exposes endAt for every job
but the existing sync queried it then dropped it on the floor.

JSON type: SQLAlchemy's portable JSON maps to JSONB on Postgres and
TEXT-with-JSON-coercion on SQLite. server_default='{}' makes the
migration safe against existing rows on both backends.
"""
from alembic import op
import sqlalchemy as sa


revision = "0010_jobber_custom_fields"
down_revision = "0009_user_accent"
branch_labels = None
depends_on = None


# We store custom_fields as a JSON object: {label: {"type": ..., "value": ...}}.
# Default empty dict so the app never has to None-check.
_CF_DEFAULT = sa.text("'{}'")


def upgrade():
    for table in ("clients", "properties", "jobs", "quotes", "invoices"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column(
                    "custom_fields",
                    sa.JSON(),
                    nullable=False,
                    server_default=_CF_DEFAULT,
                )
            )

    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("ended_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("ended_at")
    for table in ("invoices", "quotes", "jobs", "properties", "clients"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("custom_fields")
