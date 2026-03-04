"""add metadata_locked to trials

Revision ID: 0011
Revises: 0010
Create Date: 2026-03-04
"""

from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trials",
        sa.Column("metadata_locked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.alter_column("trials", "metadata_locked", server_default=None)


def downgrade() -> None:
    op.drop_column("trials", "metadata_locked")
