"""add thread sessions

Revision ID: 20260519_0003
Revises: 20260518_0002
Create Date: 2026-05-19 00:00:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260519_0003"
down_revision = "20260518_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "thread_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slack_channel_id", sa.String(length=32), nullable=False),
        sa.Column("slack_thread_ts", sa.String(length=32), nullable=False),
        sa.Column("accumulated_evidence_ids_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("query_history_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("session_context_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slack_channel_id", "slack_thread_ts", name="uq_thread_sessions_channel_thread"),
    )
    op.create_index("ix_thread_sessions_channel_updated_at", "thread_sessions", ["slack_channel_id", "updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_thread_sessions_channel_updated_at", table_name="thread_sessions")
    op.drop_table("thread_sessions")