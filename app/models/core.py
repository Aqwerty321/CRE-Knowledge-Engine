from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, Uuid, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        UniqueConstraint("slack_team_id", "slack_channel_id", "slack_ts", name="uq_source_documents_message"),
        UniqueConstraint("slack_team_id", "slack_file_id", name="uq_source_documents_file"),
        Index("ix_source_documents_content_hash", "content_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(String(50))
    slack_team_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slack_channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slack_channel_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    slack_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slack_user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    slack_ts: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slack_thread_ts: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slack_file_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(32), server_default=text("'pending'"))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class SlackSourcePost(Base):
    __tablename__ = "slack_source_posts"
    __table_args__ = (
        UniqueConstraint("slack_team_id", "post_key", name="uq_slack_source_posts_team_post_key"),
        Index("ix_slack_source_posts_source_document_id", "source_document_id"),
        Index("ix_slack_source_posts_channel_posted_at", "slack_channel_id", "posted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_documents.id", ondelete="CASCADE"))
    post_key: Mapped[str] = mapped_column(String(255))
    post_type: Mapped[str] = mapped_column(String(32))
    slack_team_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slack_channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slack_channel_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    slack_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slack_user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    slack_ts: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slack_thread_ts: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slack_file_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SlackEvent(Base):
    __tablename__ = "slack_events"
    __table_args__ = (
        UniqueConstraint("slack_team_id", "slack_event_id", name="uq_slack_events_team_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slack_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    slack_team_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slack_channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    event_type: Mapped[str] = mapped_column(String(128))
    retry_num: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), server_default=text("'received'"))
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_chunk_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_documents.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunk_text: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))


class PropertyRecord(Base):
    __tablename__ = "property_records"
    __table_args__ = (
        Index("ix_property_records_type_subtype_usage_status", "property_type", "property_subtype", "usage_type", "status"),
        Index("ix_property_records_geo_market", "country_code", "city", "market", "submarket", "neighborhood"),
        Index("ix_property_records_geo_lat_lng", "geo_lat", "geo_lng"),
        Index("ix_property_records_available_from", "available_from"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_documents.id", ondelete="CASCADE"))
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True)
    property_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit_suite: Mapped[str | None] = mapped_column(String(64), nullable=True)
    listing_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_source_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_dataset: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalized_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    property_type: Mapped[str] = mapped_column(String(32), server_default=text("'unknown'"))
    property_subtype: Mapped[str | None] = mapped_column(String(64), nullable=True)
    asset_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    usage_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    zoning: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tenure: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    listing_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    sq_ft: Mapped[int | None] = mapped_column(Integer, nullable=True)
    building_area_sq_ft: Mapped[int | None] = mapped_column(Integer, nullable=True)
    leasable_area_sq_ft: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lot_size_sq_ft: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lot_size_acres: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    floor_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    floor_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year_built: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year_renovated: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ceiling_height_ft: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    clear_height_ft: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    dock_doors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    drive_in_doors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    truck_court_depth_ft: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trailer_parking_spaces: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parking_spaces: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parking_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    elevators: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frontage_ft: Mapped[int | None] = mapped_column(Integer, nullable=True)
    facing: Mapped[str | None] = mapped_column(String(64), nullable=True)
    furnishing_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    condition_grade: Mapped[str | None] = mapped_column(String(64), nullable=True)
    energy_rating: Mapped[str | None] = mapped_column(String(64), nullable=True)
    green_certification: Mapped[str | None] = mapped_column(String(128), nullable=True)
    accessibility_features: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_per_sq_ft: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_basis: Mapped[str] = mapped_column(String(32), server_default=text("'unknown'"))
    asking_rent: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    asking_rent_period: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rent_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    service_charge: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    operating_expenses: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    taxes: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    price_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    cap_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    occupancy_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    lease_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    min_lease_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_lease_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    incentives: Mapped[str | None] = mapped_column(Text, nullable=True)
    deposit_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    fit_out_allowance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    availability: Mapped[str | None] = mapped_column(String(255), nullable=True)
    availability_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    available_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    vacancy_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occupancy_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    market: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    country: Mapped[str | None] = mapped_column(String(128), nullable=True)
    region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state_province: Mapped[str | None] = mapped_column(String(128), nullable=True)
    county_district: Mapped[str | None] = mapped_column(String(128), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locality: Mapped[str | None] = mapped_column(String(128), nullable=True)
    neighborhood: Mapped[str | None] = mapped_column(String(128), nullable=True)
    submarket: Mapped[str | None] = mapped_column(String(128), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    geo_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    geo_lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    geocode_source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    geocode_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    map_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    loading_access: Mapped[str | None] = mapped_column(String(128), nullable=True)
    yard_area_sq_ft: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cold_storage: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    sprinklered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    hvac_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    power_capacity: Mapped[str | None] = mapped_column(String(128), nullable=True)
    floor_load_psf: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nearest_highway: Mapped[str | None] = mapped_column(String(128), nullable=True)
    highway_distance_miles: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    airport_distance_miles: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    port_distance_miles: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    rail_access: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transit_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    public_transit_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    bike_parking: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ev_charging: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fiber_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    additional_information: Mapped[str | None] = mapped_column(Text, nullable=True)
    amenities_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    infrastructure_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    financials_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    tags_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    source_metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(32), server_default=text("'deterministic'"))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    source_authority_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    freshness_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    duplicate_group_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PropertyFieldValue(Base):
    __tablename__ = "property_field_values"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    property_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("property_records.id", ondelete="CASCADE"))
    field_name: Mapped[str] = mapped_column(String(64))
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    method: Mapped[str] = mapped_column(String(32), server_default=text("'deterministic'"))
    source_span: Mapped[str | None] = mapped_column(Text, nullable=True)
    extractor_version: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Query(Base):
    __tablename__ = "queries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slack_channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slack_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slack_ts: Mapped[str | None] = mapped_column(String(32), nullable=True)
    query_text: Mapped[str] = mapped_column(Text)
    route_mode: Mapped[str] = mapped_column(String(32), server_default=text("'failed'"))
    route_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    reason_codes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, server_default=text("'{}'::text[]"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ThreadSession(Base):
    __tablename__ = "thread_sessions"
    __table_args__ = (
        UniqueConstraint("slack_channel_id", "slack_thread_ts", name="uq_thread_sessions_channel_thread"),
        Index("ix_thread_sessions_channel_updated_at", "slack_channel_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slack_channel_id: Mapped[str] = mapped_column(String(32))
    slack_thread_ts: Mapped[str] = mapped_column(String(32))
    accumulated_evidence_ids_json: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    query_history_json: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    session_context_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    query_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("queries.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True)
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True)
    property_record_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("property_records.id", ondelete="SET NULL"), nullable=True)
    relevance_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    matched_fields: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, server_default=text("'{}'::text[]"))
    source_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class AnswerSnapshot(Base):
    __tablename__ = "answer_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    query_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("queries.id", ondelete="CASCADE"))
    rendered_answer: Mapped[str] = mapped_column(Text)
    route_mode: Mapped[str] = mapped_column(String(32))
    filters_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    evidence_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)),
        default=list,
        server_default=text("'{}'::uuid[]"),
    )
    dependency_state_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    model_versions_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_query_id_created_at", "query_id", "created_at"),
        Index("ix_agent_runs_status_created_at", "status", "created_at"),
        Index("ix_agent_runs_toolhouse_run_id", "toolhouse_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    query_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("queries.id", ondelete="CASCADE"), nullable=True)
    original_query_id: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32), server_default=text("'unknown'"))
    status: Mapped[str] = mapped_column(String(32), server_default=text("'running'"))
    answer_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    toolhouse_agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    toolhouse_run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    allowed_evidence_ids_json: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    cited_evidence_ids_json: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    response_payload_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    validation_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    dependency_state_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    fallback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        Index("ix_ingestion_jobs_status_job_type_created_at", "status", "job_type", "created_at"),
        Index("ix_ingestion_jobs_source_document_id_job_type", "source_document_id", "job_type"),
        Index("ix_ingestion_jobs_status_updated_at", "status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_type: Mapped[str] = mapped_column(String(32))
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), server_default=text("'queued'"))
    attempt_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    checkpoint_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
