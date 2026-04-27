"""user.theme + settings table

Revision ID: 0003_user_theme_and_settings
Revises: 0002_jobs_visits_photo_fks
Create Date: 2026-04-26 23:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "0003_user_theme_and_settings"
down_revision = "0002_jobs_visits_photo_fks"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch:
        batch.add_column(
            sa.Column("theme", sa.String(length=20), nullable=False, server_default="dark")
        )

    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=80), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("settings")
    with op.batch_alter_table("users", schema=None) as batch:
        batch.drop_column("theme")
