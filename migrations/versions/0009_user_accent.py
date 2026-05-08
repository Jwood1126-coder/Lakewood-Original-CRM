"""user.accent — themeable accent color

Revision ID: 0009_user_accent
Revises: 0008_quote_visits_and_photos
Create Date: 2026-05-08 13:00:00

Adds a per-user accent color preference (amber, cyan, violet, etc.) that
drives the new design system's neon glow palette. server_default ensures
existing rows get the default without a backfill step.
"""
from alembic import op
import sqlalchemy as sa


revision = "0009_user_accent"
down_revision = "0008_quote_visits_and_photos"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "accent",
                sa.String(length=20),
                nullable=False,
                server_default="amber",
            )
        )


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.drop_column("accent")
