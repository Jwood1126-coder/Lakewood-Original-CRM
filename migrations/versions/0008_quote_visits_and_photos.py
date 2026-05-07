"""quote scheduled-visit fields + quote_id on photos

Revision ID: 0008_quote_visits_and_photos
Revises: 0007_inbox_messages
Create Date: 2026-05-07 12:00:00

Two coupled changes:

  1. Quote.scheduled_date / scheduled_time
     For "go give a free estimate at 6pm" appointments — the visit is on
     the calendar before any line items exist.

  2. Photo.quote_id
     Lets a photo attach to a Quote (in addition to property/job/visit).
     The CHECK constraint is dropped + re-added to allow the new parent.
"""
from alembic import op
import sqlalchemy as sa


revision = "0008_quote_visits_and_photos"
down_revision = "0007_inbox_messages"
branch_labels = None
depends_on = None


def upgrade():
    # ---------- 1. quotes: scheduled visit fields ----------
    with op.batch_alter_table("quotes") as batch:
        batch.add_column(sa.Column("scheduled_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("scheduled_time", sa.Time(), nullable=True))
    op.create_index(
        "ix_quotes_scheduled_date", "quotes", ["scheduled_date"]
    )

    # ---------- 2. photos: add quote_id, relax CHECK ----------
    # Use batch_alter so SQLite (which doesn't support ALTER for CHECKs)
    # rebuilds the table cleanly. Postgres handles this fine too.
    with op.batch_alter_table("photos") as batch:
        batch.add_column(sa.Column("quote_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_photos_quote_id", "quotes", ["quote_id"], ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_photos_quote_id", ["quote_id"])
        # Drop old single-shape CHECK and replace with one that allows quotes.
        batch.drop_constraint("ck_photo_has_parent", type_="check")
        batch.create_check_constraint(
            "ck_photo_has_parent",
            "(property_id IS NOT NULL) OR (job_id IS NOT NULL) "
            "OR (visit_id IS NOT NULL) OR (quote_id IS NOT NULL)",
        )


def downgrade():
    with op.batch_alter_table("photos") as batch:
        batch.drop_constraint("ck_photo_has_parent", type_="check")
        batch.create_check_constraint(
            "ck_photo_has_parent",
            "(property_id IS NOT NULL) OR (job_id IS NOT NULL) "
            "OR (visit_id IS NOT NULL)",
        )
        batch.drop_index("ix_photos_quote_id")
        batch.drop_constraint("fk_photos_quote_id", type_="foreignkey")
        batch.drop_column("quote_id")

    op.drop_index("ix_quotes_scheduled_date", table_name="quotes")
    with op.batch_alter_table("quotes") as batch:
        batch.drop_column("scheduled_time")
        batch.drop_column("scheduled_date")
