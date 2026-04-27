"""jobs, visits; relax photos CHECK to allow job/visit parents

Revision ID: 0002_jobs_visits_photo_fks
Revises: 0001_initial_schema
Create Date: 2026-04-26 22:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "0002_jobs_visits_photo_fks"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    # --- jobs ---
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="scheduled"),
        sa.Column("scheduled_date", sa.Date(), nullable=True),
        sa.Column("scheduled_time", sa.Time(), nullable=True),
        sa.Column("est_hours", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE",
                                name="fk_jobs_client_id"),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE",
                                name="fk_jobs_property_id"),
    )
    op.create_index("ix_jobs_client_id", "jobs", ["client_id"])
    op.create_index("ix_jobs_property_id", "jobs", ["property_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_scheduled_date", "jobs", ["scheduled_date"])

    # --- visits ---
    op.create_table(
        "visits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=True),
        sa.Column("arrived_at", sa.DateTime(), nullable=True),
        sa.Column("departed_at", sa.DateTime(), nullable=True),
        sa.Column("miles", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE",
                                name="fk_visits_job_id"),
    )
    op.create_index("ix_visits_job_id", "visits", ["job_id"])
    op.create_index("ix_visits_scheduled_date", "visits", ["scheduled_date"])

    # --- photos: add job_id + visit_id, relax CHECK constraint ---
    with op.batch_alter_table("photos", schema=None) as batch:
        batch.add_column(sa.Column("job_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("visit_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_photos_job_id", "jobs", ["job_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_foreign_key(
            "fk_photos_visit_id", "visits", ["visit_id"], ["id"], ondelete="CASCADE"
        )
        batch.drop_constraint("ck_photo_has_parent", type_="check")
        batch.create_check_constraint(
            "ck_photo_has_parent",
            "(property_id IS NOT NULL) OR (job_id IS NOT NULL) OR (visit_id IS NOT NULL)",
        )
    op.create_index("ix_photos_job_id", "photos", ["job_id"])
    op.create_index("ix_photos_visit_id", "photos", ["visit_id"])


def downgrade():
    op.drop_index("ix_photos_visit_id", table_name="photos")
    op.drop_index("ix_photos_job_id", table_name="photos")
    with op.batch_alter_table("photos", schema=None) as batch:
        batch.drop_constraint("ck_photo_has_parent", type_="check")
        batch.create_check_constraint(
            "ck_photo_has_parent", "property_id IS NOT NULL"
        )
        batch.drop_constraint("fk_photos_visit_id", type_="foreignkey")
        batch.drop_constraint("fk_photos_job_id", type_="foreignkey")
        batch.drop_column("visit_id")
        batch.drop_column("job_id")

    op.drop_index("ix_visits_scheduled_date", table_name="visits")
    op.drop_index("ix_visits_job_id", table_name="visits")
    op.drop_table("visits")

    op.drop_index("ix_jobs_scheduled_date", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_property_id", table_name="jobs")
    op.drop_index("ix_jobs_client_id", table_name="jobs")
    op.drop_table("jobs")
