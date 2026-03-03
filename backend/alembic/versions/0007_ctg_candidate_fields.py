"""add ctg candidate review fields to trials

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trials", sa.Column("ctg_candidate_nct_id", sa.String(length=32), nullable=True))
    op.add_column("trials", sa.Column("ctg_candidate_url", sa.String(length=500), nullable=True))
    op.add_column("trials", sa.Column("ctg_candidate_title", sa.String(length=500), nullable=True))
    op.add_column("trials", sa.Column("ctg_candidate_source", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("trials", "ctg_candidate_source")
    op.drop_column("trials", "ctg_candidate_title")
    op.drop_column("trials", "ctg_candidate_url")
    op.drop_column("trials", "ctg_candidate_nct_id")
