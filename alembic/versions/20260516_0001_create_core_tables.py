"""create core tables

Revision ID: 20260516_0001
Revises:
Create Date: 2026-05-16 00:00:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260516_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("slack_team_id", sa.String(length=32), nullable=True),
        sa.Column("slack_channel_id", sa.String(length=32), nullable=True),
        sa.Column("slack_channel_name", sa.String(length=255), nullable=True),
        sa.Column("slack_user_id", sa.String(length=32), nullable=True),
        sa.Column("slack_user_name", sa.String(length=255), nullable=True),
        sa.Column("slack_ts", sa.String(length=32), nullable=True),
        sa.Column("slack_thread_ts", sa.String(length=32), nullable=True),
        sa.Column("slack_file_id", sa.String(length=64), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("file_mime_type", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("local_path", sa.Text(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("raw_payload_hash", sa.String(length=128), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slack_team_id", "slack_channel_id", "slack_ts", name="uq_source_documents_message"),
        sa.UniqueConstraint("slack_team_id", "slack_file_id", name="uq_source_documents_file"),
    )
    op.create_index("ix_source_documents_content_hash", "source_documents", ["content_hash"], unique=False)

    op.create_table(
        "slack_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slack_event_id", sa.String(length=64), nullable=True),
        sa.Column("slack_team_id", sa.String(length=32), nullable=True),
        sa.Column("slack_channel_id", sa.String(length=32), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("retry_num", sa.Integer(), nullable=True),
        sa.Column("retry_reason", sa.String(length=64), nullable=True),
        sa.Column("payload_hash", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'received'"), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slack_team_id", "slack_event_id", name="uq_slack_events_team_event"),
    )

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("section_name", sa.String(length=255), nullable=True),
        sa.Column("embedding_id", sa.String(length=255), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["source_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_chunk_index"),
    )

    op.create_table(
        "property_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("normalized_address", sa.String(length=255), nullable=True),
        sa.Column("property_type", sa.String(length=32), server_default=sa.text("'unknown'"), nullable=False),
        sa.Column("sq_ft", sa.Integer(), nullable=True),
        sa.Column("price_per_sq_ft", sa.Numeric(12, 2), nullable=True),
        sa.Column("price_basis", sa.String(length=32), server_default=sa.text("'unknown'"), nullable=False),
        sa.Column("availability", sa.String(length=255), nullable=True),
        sa.Column("availability_date", sa.Date(), nullable=True),
        sa.Column("market", sa.String(length=255), nullable=True),
        sa.Column("geo_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("geo_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_row", sa.Integer(), nullable=True),
        sa.Column("extraction_method", sa.String(length=32), server_default=sa.text("'deterministic'"), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("source_authority_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("freshness_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("duplicate_group_key", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["source_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "property_field_values",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field_name", sa.String(length=64), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("normalized_value", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("method", sa.String(length=32), server_default=sa.text("'deterministic'"), nullable=False),
        sa.Column("source_span", sa.Text(), nullable=True),
        sa.Column("extractor_version", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(["property_record_id"], ["property_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "queries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slack_channel_id", sa.String(length=32), nullable=True),
        sa.Column("slack_user_id", sa.String(length=32), nullable=True),
        sa.Column("slack_ts", sa.String(length=32), nullable=True),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("route_mode", sa.String(length=32), server_default=sa.text("'failed'"), nullable=False),
        sa.Column("route_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("reason_codes", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "evidence_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("property_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("relevance_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("matched_fields", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
        sa.Column("source_summary", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["source_documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["property_record_id"], ["property_records.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["query_id"], ["queries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "answer_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rendered_answer", sa.Text(), nullable=False),
        sa.Column("route_mode", sa.String(length=32), nullable=False),
        sa.Column("filters_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("evidence_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), server_default=sa.text("'{}'::uuid[]"), nullable=False),
        sa.Column("dependency_state_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("model_versions_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["query_id"], ["queries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("source_document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("checkpoint_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_document_id"], ["source_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_ingestion_jobs_status_job_type_created_at",
        "ingestion_jobs",
        ["status", "job_type", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ingestion_jobs_source_document_id_job_type",
        "ingestion_jobs",
        ["source_document_id", "job_type"],
        unique=False,
    )
    op.create_index(
        "ix_ingestion_jobs_status_updated_at",
        "ingestion_jobs",
        ["status", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_jobs_status_updated_at", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_source_document_id_job_type", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_status_job_type_created_at", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_table("answer_snapshots")
    op.drop_table("evidence_items")
    op.drop_table("queries")
    op.drop_table("property_field_values")
    op.drop_table("property_records")
    op.drop_table("chunks")
    op.drop_table("slack_events")
    op.drop_index("ix_source_documents_content_hash", table_name="source_documents")
    op.drop_table("source_documents")
