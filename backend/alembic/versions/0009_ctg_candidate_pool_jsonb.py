"""convert ctg candidate pool to jsonb on postgres

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.alter_column(
        "trials",
        "ctg_candidate_pool",
        existing_type=sa.JSON(),
        type_=postgresql.JSONB(),
        existing_nullable=True,
        postgresql_using="ctg_candidate_pool::jsonb",
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.alter_column(
        "trials",
        "ctg_candidate_pool",
        existing_type=postgresql.JSONB(),
        type_=sa.JSON(),
        existing_nullable=True,
        postgresql_using="ctg_candidate_pool::json",
    )
