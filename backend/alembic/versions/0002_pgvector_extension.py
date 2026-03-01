"""ensure pgvector extension exists

Revision ID: 0002_pgvector_extension
Revises: 0001_initial
Create Date: 2026-03-01
"""

from alembic import op


revision = "0002_pgvector_extension"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    pass
