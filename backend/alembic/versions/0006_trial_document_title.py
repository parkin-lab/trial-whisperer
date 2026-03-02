"""add document title field to trials

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-02
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trials", sa.Column("document_title", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("trials", "document_title")
