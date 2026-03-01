"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-03-01
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("role", sa.Enum("owner", "pi", "coordinator", "collaborator", name="user_role", native_enum=False), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_domain", "users", ["domain"], unique=False)

    op.create_table(
        "domain_allowlist",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("added_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_domain_allowlist_domain", "domain_allowlist", ["domain"], unique=True)

    op.create_table(
        "trials",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("nct_id", sa.String(length=32), nullable=True),
        sa.Column("nickname", sa.String(length=255), nullable=False),
        sa.Column("indication", sa.Enum("aml", "all", "lymphoma", "mm", "transplant", "gvhd", name="indication", native_enum=False), nullable=False),
        sa.Column("phase", sa.String(length=64), nullable=True),
        sa.Column("sponsor", sa.String(length=255), nullable=True),
        sa.Column("status", sa.Enum("draft", "active", "archived", name="trial_status", native_enum=False), nullable=False),
        sa.Column("pi_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("coordinator_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trials_nct_id", "trials", ["nct_id"], unique=False)
    op.create_index("ix_trials_nickname", "trials", ["nickname"], unique=False)

    op.create_table(
        "trial_documents",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("trial_id", sa.Uuid(), sa.ForeignKey("trials.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trial_documents_trial_id", "trial_documents", ["trial_id"], unique=False)

    op.create_table(
        "trial_amendments",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("trial_id", sa.Uuid(), sa.ForeignKey("trials.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_version", sa.Integer(), nullable=False),
        sa.Column("to_version", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trial_amendments_trial_id", "trial_amendments", ["trial_id"], unique=False)

    op.create_table(
        "trial_criteria",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("trial_id", sa.Uuid(), sa.ForeignKey("trials.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("type", sa.Enum("inclusion", "exclusion", name="criteria_type", native_enum=False), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("expression", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Enum("high", "needs_review", name="confidence_level", native_enum=False), nullable=False),
        sa.Column("manual_review_required", sa.Boolean(), nullable=False),
        sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_trial_criteria_trial_id", "trial_criteria", ["trial_id"], unique=False)

    op.create_table(
        "ctg_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("trial_id", sa.Uuid(), sa.ForeignKey("trials.id", ondelete="CASCADE"), nullable=False),
        sa.Column("nct_id", sa.String(length=32), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("pulled_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ctg_snapshots_trial_id", "ctg_snapshots", ["trial_id"], unique=False)
    op.create_index("ix_ctg_snapshots_nct_id", "ctg_snapshots", ["nct_id"], unique=False)

    op.create_table(
        "protocol_embeddings",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("trial_id", sa.Uuid(), sa.ForeignKey("trials.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(dim=1536), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
    )
    op.create_index("ix_protocol_embeddings_trial_id", "protocol_embeddings", ["trial_id"], unique=False)

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("indication", sa.String(length=64), nullable=False),
        sa.Column("criteria_version_hash", sa.String(length=255), nullable=False),
        sa.Column("engine_version", sa.String(length=128), nullable=False),
        sa.Column("screen_results", sa.JSON(), nullable=False),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    op.create_table(
        "background_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.Enum("pending", "running", "completed", "failed", name="job_status", native_enum=False), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_background_jobs_type", "background_jobs", ["type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_background_jobs_type", table_name="background_jobs")
    op.drop_table("background_jobs")
    op.drop_table("audit_log")
    op.drop_index("ix_protocol_embeddings_trial_id", table_name="protocol_embeddings")
    op.drop_table("protocol_embeddings")
    op.drop_index("ix_ctg_snapshots_nct_id", table_name="ctg_snapshots")
    op.drop_index("ix_ctg_snapshots_trial_id", table_name="ctg_snapshots")
    op.drop_table("ctg_snapshots")
    op.drop_index("ix_trial_criteria_trial_id", table_name="trial_criteria")
    op.drop_table("trial_criteria")
    op.drop_index("ix_trial_amendments_trial_id", table_name="trial_amendments")
    op.drop_table("trial_amendments")
    op.drop_index("ix_trial_documents_trial_id", table_name="trial_documents")
    op.drop_table("trial_documents")
    op.drop_index("ix_trials_nickname", table_name="trials")
    op.drop_index("ix_trials_nct_id", table_name="trials")
    op.drop_table("trials")
    op.drop_index("ix_domain_allowlist_domain", table_name="domain_allowlist")
    op.drop_table("domain_allowlist")
    op.drop_index("ix_users_domain", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
