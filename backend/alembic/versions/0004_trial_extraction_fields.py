"""add ingestion-first trial extraction fields

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-02
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trials", sa.Column("ctg_url", sa.String(length=500), nullable=True))
    op.add_column(
        "trials",
        sa.Column(
            "extraction_status",
            sa.Enum("processing", "ready", "needs_review", name="trial_extraction_status", native_enum=False),
            nullable=False,
            server_default="needs_review",
        ),
    )
    op.add_column("trials", sa.Column("extraction_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("trials", sa.Column("extraction_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column(
        "trials",
        "indication",
        existing_type=sa.Enum("aml", "all", "lymphoma", "mm", "transplant", "gvhd", name="indication", native_enum=False),
        nullable=True,
    )
    op.alter_column("trials", "extraction_status", server_default=None)


def downgrade() -> None:
    op.execute("UPDATE trials SET indication = 'aml' WHERE indication IS NULL")
    op.alter_column(
        "trials",
        "indication",
        existing_type=sa.Enum("aml", "all", "lymphoma", "mm", "transplant", "gvhd", name="indication", native_enum=False),
        nullable=False,
    )
    op.drop_column("trials", "extraction_completed_at")
    op.drop_column("trials", "extraction_started_at")
    op.drop_column("trials", "extraction_status")
    op.drop_column("trials", "ctg_url")
