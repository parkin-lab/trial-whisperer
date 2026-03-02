"""add trial title and CTG match transparency fields

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-02
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trials", sa.Column("trial_title", sa.String(length=500), nullable=True))
    op.add_column("trials", sa.Column("ctg_match_confidence", sa.Float(), nullable=True))
    op.add_column("trials", sa.Column("ctg_match_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("trials", "ctg_match_note")
    op.drop_column("trials", "ctg_match_confidence")
    op.drop_column("trials", "trial_title")
