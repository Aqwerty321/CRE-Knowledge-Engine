"""add source provenance and agent runs

Revision ID: 20260518_0002
Revises: 20260516_0001
Create Date: 2026-05-18 00:00:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260518_0002"
down_revision = "20260516_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "slack_source_posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("post_key", sa.String(length=255), nullable=False),
        sa.Column("post_type", sa.String(length=32), nullable=False),
        sa.Column("slack_team_id", sa.String(length=32), nullable=True),
        sa.Column("slack_channel_id", sa.String(length=32), nullable=True),
        sa.Column("slack_channel_name", sa.String(length=255), nullable=True),
        sa.Column("slack_user_id", sa.String(length=32), nullable=True),
        sa.Column("slack_user_name", sa.String(length=255), nullable=True),
        sa.Column("slack_ts", sa.String(length=32), nullable=True),
        sa.Column("slack_thread_ts", sa.String(length=32), nullable=True),
        sa.Column("slack_file_id", sa.String(length=64), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["source_document_id"], ["source_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slack_team_id", "post_key", name="uq_slack_source_posts_team_post_key"),
    )
    op.create_index("ix_slack_source_posts_source_document_id", "slack_source_posts", ["source_document_id"], unique=False)
    op.create_index("ix_slack_source_posts_channel_posted_at", "slack_source_posts", ["slack_channel_id", "posted_at"], unique=False)

    op.execute(
        """
        INSERT INTO slack_source_posts (
            id,
            source_document_id,
            post_key,
            post_type,
            slack_team_id,
            slack_channel_id,
            slack_channel_name,
            slack_user_id,
            slack_user_name,
            slack_ts,
            slack_thread_ts,
            slack_file_id,
            source_url,
            posted_at
        )
        SELECT
            gen_random_uuid(),
            id,
            CASE
                WHEN slack_file_id IS NOT NULL THEN 'file:' || COALESCE(slack_channel_id, 'unknown-channel') || ':' || COALESCE(slack_ts, 'unknown-ts') || ':' || slack_file_id
                ELSE 'message:' || COALESCE(slack_channel_id, 'unknown-channel') || ':' || slack_ts
            END,
            CASE WHEN slack_file_id IS NOT NULL THEN 'file_share' ELSE 'message' END,
            slack_team_id,
            slack_channel_id,
            slack_channel_name,
            slack_user_id,
            slack_user_name,
            slack_ts,
            slack_thread_ts,
            slack_file_id,
            source_url,
            posted_at
        FROM source_documents
        WHERE slack_team_id IS NOT NULL
          AND (slack_ts IS NOT NULL OR slack_file_id IS NOT NULL)
        ON CONFLICT DO NOTHING
        """
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("original_query_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), server_default=sa.text("'unknown'"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'running'"), nullable=False),
        sa.Column("answer_mode", sa.String(length=32), nullable=True),
        sa.Column("toolhouse_agent_id", sa.String(length=128), nullable=True),
        sa.Column("toolhouse_run_id", sa.String(length=128), nullable=True),
        sa.Column("allowed_evidence_ids_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("cited_evidence_ids_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("response_payload_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("validation_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("dependency_state_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("fallback_reason", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("rendered_answer", sa.Text(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["query_id"], ["queries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_query_id_created_at", "agent_runs", ["query_id", "created_at"], unique=False)
    op.create_index("ix_agent_runs_status_created_at", "agent_runs", ["status", "created_at"], unique=False)
    op.create_index("ix_agent_runs_toolhouse_run_id", "agent_runs", ["toolhouse_run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agent_runs_toolhouse_run_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_status_created_at", table_name="agent_runs")
    op.drop_index("ix_agent_runs_query_id_created_at", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_slack_source_posts_channel_posted_at", table_name="slack_source_posts")
    op.drop_index("ix_slack_source_posts_source_document_id", table_name="slack_source_posts")
    op.drop_table("slack_source_posts")