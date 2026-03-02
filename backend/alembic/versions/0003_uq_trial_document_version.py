"""add unique constraint trial_document_version

Revision ID: 0003
Revises: 0002_pgvector_extension
Create Date: 2026-03-01
"""

from alembic import op

revision = "0003"
down_revision = "0002_pgvector_extension"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_trial_document_version", "trial_documents", ["trial_id", "version"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_trial_document_version", "trial_documents", type_="unique")
