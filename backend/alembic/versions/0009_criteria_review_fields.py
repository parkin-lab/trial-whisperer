"""criteria review row-level fields

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("trial_criteria", "expression", existing_type=sa.JSON(), nullable=True)
    op.add_column("trial_criteria", sa.Column("source_order", sa.Integer(), nullable=True))
    op.add_column("trial_criteria", sa.Column("section_label", sa.String(length=64), nullable=True))
    op.add_column(
        "trial_criteria",
        sa.Column(
            "parse_status",
            sa.Enum(
                "parsed",
                "needs_review",
                "approved",
                "manual_only",
                name="criteria_parse_status",
                native_enum=False,
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("trial_criteria", "parse_status")
    op.drop_column("trial_criteria", "section_label")
    op.drop_column("trial_criteria", "source_order")
    op.alter_column("trial_criteria", "expression", existing_type=sa.JSON(), nullable=False)
