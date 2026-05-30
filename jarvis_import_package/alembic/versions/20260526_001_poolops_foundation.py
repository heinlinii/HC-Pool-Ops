"""PoolOps property-card foundation

Revision ID: 20260526_001
Revises:
Create Date: 2026-05-26
"""

from alembic import op
import sqlalchemy as sa


revision = "20260526_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(length=32), unique=True),
        sa.Column("client_name", sa.Text(), nullable=False),
        sa.Column("contact_name", sa.Text()),
        sa.Column("phone", sa.Text()),
        sa.Column("email", sa.Text()),
        sa.Column("source", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("portal_username", sa.Text(), unique=True),
        sa.Column("portal_password", sa.Text()),
        sa.Column("card_image", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "properties",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(length=32), unique=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="SET NULL")),
        sa.Column("client_external_id", sa.String(length=32)),
        sa.Column("client_name", sa.Text()),
        sa.Column("property_name", sa.Text(), nullable=False),
        sa.Column("street", sa.Text()),
        sa.Column("city", sa.Text()),
        sa.Column("state", sa.Text()),
        sa.Column("zip_code", sa.Text()),
        sa.Column("full_address", sa.Text()),
        sa.Column("google_maps_url", sa.Text()),
        sa.Column("raw_address", sa.Text()),
        sa.Column("card_image", sa.Text()),
        sa.Column("needs_review", sa.Boolean(), server_default=sa.text("FALSE")),
        sa.Column("source", sa.Text()),
        sa.Column("latitude", sa.Numeric(10, 7)),
        sa.Column("longitude", sa.Numeric(10, 7)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(length=32), unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text()),
        sa.Column("role", sa.Text()),
        sa.Column("username", sa.Text(), unique=True),
        sa.Column("password", sa.Text()),
        sa.Column("card_image", sa.Text()),
        sa.Column("active", sa.Boolean(), server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(length=32), unique=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="SET NULL")),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id", ondelete="SET NULL")),
        sa.Column("client_external_id", sa.String(length=32)),
        sa.Column("client_name", sa.Text()),
        sa.Column("property_name", sa.Text()),
        sa.Column("address", sa.Text()),
        sa.Column("job_type", sa.Text()),
        sa.Column("status", sa.Text(), server_default="Requested"),
        sa.Column("crew", sa.Text()),
        sa.Column("scheduled_date", sa.Date()),
        sa.Column("raw_date", sa.Text()),
        sa.Column("priority", sa.Text(), server_default="Normal"),
        sa.Column("notes", sa.Text()),
        sa.Column("card_image", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(length=32), unique=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="SET NULL")),
        sa.Column("client_name", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("amount", sa.Numeric(12, 2)),
        sa.Column("status", sa.Text(), server_default="Draft"),
        sa.Column("invoice_date", sa.Date()),
        sa.Column("raw_date", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "photo_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(length=32), unique=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id", ondelete="SET NULL")),
        sa.Column("client_name", sa.Text()),
        sa.Column("photo_type", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("photo_url", sa.Text()),
        sa.Column("photo_date", sa.Date()),
        sa.Column("raw_date", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("latitude", sa.Numeric(10, 7)),
        sa.Column("longitude", sa.Numeric(10, 7)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "property_card_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filename", sa.Text(), unique=True),
        sa.Column("app_path", sa.Text()),
        sa.Column("recommended_use", sa.Text()),
        sa.Column("assigned_client", sa.Text()),
        sa.Column("assigned_property", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_index("idx_properties_client_id", "properties", ["client_id"])
    op.create_index("idx_jobs_property_id", "jobs", ["property_id"])
    op.create_index("idx_jobs_scheduled_date", "jobs", ["scheduled_date"])
    op.create_index("idx_photo_logs_property_id", "photo_logs", ["property_id"])


def downgrade():
    op.drop_index("idx_photo_logs_property_id", table_name="photo_logs")
    op.drop_index("idx_jobs_scheduled_date", table_name="jobs")
    op.drop_index("idx_jobs_property_id", table_name="jobs")
    op.drop_index("idx_properties_client_id", table_name="properties")
    op.drop_table("property_card_images")
    op.drop_table("photo_logs")
    op.drop_table("invoices")
    op.drop_table("jobs")
    op.drop_table("employees")
    op.drop_table("properties")
    op.drop_table("clients")
