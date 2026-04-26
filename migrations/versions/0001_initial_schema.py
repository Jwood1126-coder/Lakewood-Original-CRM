"""initial schema: users, clients, properties, photos

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-04-26 00:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_clients_name", "clients", ["name"])
    op.create_index("ix_clients_phone", "clients", ["phone"])
    op.create_index("ix_clients_email", "clients", ["email"])

    op.create_table(
        "properties",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False, server_default="Home"),
        sa.Column("address_line1", sa.String(length=200), nullable=False),
        sa.Column("address_line2", sa.String(length=200), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=2), nullable=False, server_default="OH"),
        sa.Column("zip_code", sa.String(length=10), nullable=False),
        sa.Column("county", sa.String(length=60), nullable=True),
        sa.Column("tax_rate", sa.Numeric(precision=6, scale=4), nullable=False,
                  server_default="0.0575"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE",
                                name="fk_properties_client_id"),
    )
    op.create_index("ix_properties_client_id", "properties", ["client_id"])
    op.create_index("ix_properties_zip_code", "properties", ["zip_code"])

    op.create_table(
        "photos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rel_path", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("mimetype", sa.String(length=80), nullable=True),
        sa.Column("bytes", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("caption", sa.String(length=500), nullable=True),
        sa.Column("property_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE",
                                name="fk_photos_property_id"),
        sa.CheckConstraint("property_id IS NOT NULL", name="ck_photo_has_parent"),
    )
    op.create_index("ix_photos_property_id", "photos", ["property_id"])


def downgrade():
    op.drop_index("ix_photos_property_id", table_name="photos")
    op.drop_table("photos")
    op.drop_index("ix_properties_zip_code", table_name="properties")
    op.drop_index("ix_properties_client_id", table_name="properties")
    op.drop_table("properties")
    op.drop_index("ix_clients_email", table_name="clients")
    op.drop_index("ix_clients_phone", table_name="clients")
    op.drop_index("ix_clients_name", table_name="clients")
    op.drop_table("clients")
    op.drop_table("users")
