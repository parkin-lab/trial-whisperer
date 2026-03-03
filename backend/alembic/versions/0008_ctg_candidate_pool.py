"""add ctg candidate pool field to trials

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trials", sa.Column("ctg_candidate_pool", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("trials", "ctg_candidate_pool")
