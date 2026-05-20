from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionFactory
from app.extraction import ParsedChunk, parse_source_file
from app.extraction.property_extractor import extract_property_facts
from app.ingestion.large_corpus_builder import build_large_corpus
from app.indexing import index_chunks_by_ids
from app.models import AgentRun, AnswerSnapshot, Chunk, EvidenceItem, IngestionJob, PropertyFieldValue, PropertyRecord, Query, SlackSourcePost, SourceDocument


PROPERTY_ALIAS_MAP = {
    "neighbourhood": "neighborhood",
    "furnishing": "furnishing_status",
    "furnished": "furnishing_status",
    "funishing": "furnishing_status",
    "usage": "usage_type",
    "use": "usage_type",
    "use_case": "usage_type",
    "lat": "geo_lat",
    "latitude": "geo_lat",
    "lng": "geo_lng",
    "lon": "geo_lng",
    "longitude": "geo_lng",
    "remarks": "additional_information",
    "comments": "additional_information",
    "notes": "additional_information",
}

RICH_PROPERTY_VALUE_FIELDS = [
    "property_name",
    "unit_suite",
    "listing_id",
    "external_source_id",
    "source_dataset",
    "property_subtype",
    "asset_class",
    "usage_type",
    "zoning",
    "tenure",
    "status",
    "status_date",
    "listing_url",
    "building_area_sq_ft",
    "leasable_area_sq_ft",
    "lot_size_sq_ft",
    "lot_size_acres",
    "floor_number",
    "floor_count",
    "year_built",
    "year_renovated",
    "ceiling_height_ft",
    "clear_height_ft",
    "dock_doors",
    "drive_in_doors",
    "truck_court_depth_ft",
    "trailer_parking_spaces",
    "parking_spaces",
    "parking_ratio",
    "elevators",
    "frontage_ft",
    "facing",
    "furnishing_status",
    "condition_grade",
    "energy_rating",
    "green_certification",
    "accessibility_features",
    "asking_rent",
    "asking_rent_period",
    "rent_currency",
    "service_charge",
    "operating_expenses",
    "taxes",
    "sale_price",
    "price_currency",
    "cap_rate",
    "occupancy_pct",
    "lease_type",
    "min_lease_months",
    "max_lease_months",
    "incentives",
    "deposit_amount",
    "fit_out_allowance",
    "available_from",
    "vacancy_status",
    "occupancy_status",
    "country_code",
    "country",
    "region",
    "state_province",
    "county_district",
    "city",
    "locality",
    "neighborhood",
    "submarket",
    "postal_code",
    "timezone",
    "geocode_source",
    "geocode_confidence",
    "map_url",
    "loading_access",
    "yard_area_sq_ft",
    "cold_storage",
    "sprinklered",
    "hvac_type",
    "power_capacity",
    "floor_load_psf",
    "nearest_highway",
    "highway_distance_miles",
    "airport_distance_miles",
    "port_distance_miles",
    "rail_access",
    "transit_score",
    "public_transit_notes",
    "bike_parking",
    "ev_charging",
    "fiber_available",
    "additional_information",
]

DEFAULT_RICH_FIELD_VALUES = [
    "property_name",
    "listing_id",
    "source_dataset",
    "property_subtype",
    "usage_type",
    "status",
    "available_from",
    "country_code",
    "country",
    "city",
    "locality",
    "neighborhood",
    "submarket",
    "postal_code",
    "map_url",
    "facing",
    "furnishing_status",
    "loading_access",
    "nearest_highway",
    "additional_information",
]


class SampleFieldValueModel(BaseModel):
    field_name: str
    raw_value: str | None = None
    normalized_value: str | None = None
    confidence: Decimal | None = None
    method: str = "manual_seed"
    source_span: str | None = None
    extractor_version: str = "sample-import-v1"


class SamplePropertyModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    address: str
    property_type: str
    property_name: str | None = None
    unit_suite: str | None = None
    listing_id: str | None = None
    external_source_id: str | None = None
    source_dataset: str | None = None
    property_subtype: str | None = None
    asset_class: str | None = None
    usage_type: str | None = None
    zoning: str | None = None
    tenure: str | None = None
    status: str | None = None
    status_date: date | None = None
    listing_url: str | None = None
    sq_ft: int | None = None
    building_area_sq_ft: int | None = None
    leasable_area_sq_ft: int | None = None
    lot_size_sq_ft: int | None = None
    lot_size_acres: Decimal | None = None
    floor_number: int | None = None
    floor_count: int | None = None
    year_built: int | None = None
    year_renovated: int | None = None
    ceiling_height_ft: Decimal | None = None
    clear_height_ft: Decimal | None = None
    dock_doors: int | None = None
    drive_in_doors: int | None = None
    truck_court_depth_ft: int | None = None
    trailer_parking_spaces: int | None = None
    parking_spaces: int | None = None
    parking_ratio: Decimal | None = None
    elevators: int | None = None
    frontage_ft: int | None = None
    facing: str | None = None
    furnishing_status: str | None = None
    condition_grade: str | None = None
    energy_rating: str | None = None
    green_certification: str | None = None
    accessibility_features: str | None = None
    price_per_sq_ft: Decimal | None = None
    price_basis: str = "annual_rent"
    asking_rent: Decimal | None = None
    asking_rent_period: str | None = None
    rent_currency: str | None = None
    service_charge: Decimal | None = None
    operating_expenses: Decimal | None = None
    taxes: Decimal | None = None
    sale_price: Decimal | None = None
    price_currency: str | None = None
    cap_rate: Decimal | None = None
    occupancy_pct: Decimal | None = None
    lease_type: str | None = None
    min_lease_months: int | None = None
    max_lease_months: int | None = None
    incentives: str | None = None
    deposit_amount: Decimal | None = None
    fit_out_allowance: Decimal | None = None
    availability: str | None = None
    availability_date: date | None = None
    available_from: date | None = None
    vacancy_status: str | None = None
    occupancy_status: str | None = None
    market: str | None = None
    country_code: str | None = None
    country: str | None = None
    region: str | None = None
    state_province: str | None = None
    county_district: str | None = None
    city: str | None = None
    locality: str | None = None
    neighborhood: str | None = None
    submarket: str | None = None
    postal_code: str | None = None
    timezone: str | None = None
    geo_lat: Decimal | None = None
    geo_lng: Decimal | None = None
    geocode_source: str | None = None
    geocode_confidence: Decimal | None = None
    map_url: str | None = None
    loading_access: str | None = None
    yard_area_sq_ft: int | None = None
    cold_storage: bool | None = None
    sprinklered: bool | None = None
    hvac_type: str | None = None
    power_capacity: str | None = None
    floor_load_psf: int | None = None
    nearest_highway: str | None = None
    highway_distance_miles: Decimal | None = None
    airport_distance_miles: Decimal | None = None
    port_distance_miles: Decimal | None = None
    rail_access: str | None = None
    transit_score: int | None = None
    public_transit_notes: str | None = None
    bike_parking: bool | None = None
    ev_charging: bool | None = None
    fiber_available: bool | None = None
    additional_information: str | None = None
    amenities_json: dict[str, object] = Field(default_factory=dict)
    infrastructure_json: dict[str, object] = Field(default_factory=dict)
    financials_json: dict[str, object] = Field(default_factory=dict)
    tags_json: dict[str, object] = Field(default_factory=dict)
    source_metadata_json: dict[str, object] = Field(default_factory=dict)
    source_page: int | None = None
    source_row: int | None = None
    extraction_method: str = "manual_seed"
    confidence: Decimal = Decimal("1.0000")
    source_authority_score: Decimal | None = None
    freshness_score: Decimal | None = None
    duplicate_group_key: str | None = None
    chunk_index: int | None = None
    field_values: list[SampleFieldValueModel] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, payload: object) -> object:
        if not isinstance(payload, dict):
            return payload

        normalized = dict(payload)
        remarks: list[str] = []
        for alias, target in PROPERTY_ALIAS_MAP.items():
            if alias not in normalized:
                continue
            value = normalized.pop(alias)
            if target == "additional_information" and value not in {None, ""}:
                remarks.append(str(value).strip())
                continue
            if target not in normalized or normalized.get(target) in {None, ""}:
                normalized[target] = value

        existing_info = str(normalized.get("additional_information") or "").strip()
        if remarks:
            normalized["additional_information"] = "\n".join([value for value in [existing_info, *remarks] if value])
        return normalized


class SampleChunkModel(BaseModel):
    chunk_index: int | None = None
    text: str | None = None
    section_name: str | None = None
    page_number: int | None = None
    row_number: int | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class SampleSourceModel(BaseModel):
    source_id: str
    source_type: str
    posted_at: datetime
    slack_user_id: str | None = None
    slack_user_name: str | None = None
    slack_ts: str | None = None
    slack_thread_ts: str | None = None
    slack_file_id: str | None = None
    file_name: str | None = None
    file_mime_type: str | None = None
    source_url: str | None = None
    local_path: str | None = None
    raw_text: str | None = None
    chunks: list[SampleChunkModel] = Field(default_factory=list)
    properties: list[SamplePropertyModel] = Field(default_factory=list)


class SampleDatasetModel(BaseModel):
    team_id: str
    channel_id: str
    channel_name: str
    sources: list[SampleSourceModel]


def _generated_manifest_paths(sample_data_dir: Path) -> list[Path]:
    generated_dir = sample_data_dir / "generated"
    if not generated_dir.exists():
        return []
    return sorted(generated_dir.glob("import-manifest-*.json"))


def _ensure_generated_large_corpus(sample_data_dir: Path) -> None:
    report_path = sample_data_dir / "generated" / "large-corpus-quality-report.json"
    if report_path.exists():
        try:
            report_payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            report_payload = None
        if isinstance(report_payload, dict) and int(report_payload.get("cap_rate_coverage") or 0) > 0:
            return
    build_large_corpus(sample_data_dir)


def load_sample_manifest(sample_data_dir: Path, *, include_generated: bool = True) -> SampleDatasetModel:
    manifest_path = sample_data_dir / "import-manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing sample manifest at {manifest_path}")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset = SampleDatasetModel.model_validate(payload)
    if not include_generated:
        return dataset

    _ensure_generated_large_corpus(sample_data_dir)

    generated_sources: list[SampleSourceModel] = []
    for generated_path in _generated_manifest_paths(sample_data_dir):
        generated_payload = json.loads(generated_path.read_text(encoding="utf-8"))
        generated_dataset = SampleDatasetModel.model_validate(generated_payload)
        generated_sources.extend(generated_dataset.sources)

    if not generated_sources:
        return dataset
    return dataset.model_copy(update={"sources": [*dataset.sources, *generated_sources]})


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_address(address: str) -> str:
    return " ".join(address.lower().replace(",", " ").split())


def _normalize_source_url(source_url: str | None) -> str | None:
    normalized = str(source_url or "").strip()
    if not normalized:
        return None
    if "demo.local" in normalized.lower():
        return None
    return normalized


def _resolve_document(source: SampleSourceModel, sample_data_dir: Path) -> tuple[str, str | None, list[SampleChunkModel]]:
    if source.raw_text is not None:
        return source.raw_text, None, []

    if source.local_path is None:
        raise ValueError(f"Sample source {source.source_id} is missing both raw_text and local_path")

    resolved_path = sample_data_dir / source.local_path
    parsed_document = parse_source_file(resolved_path, source_type=source.source_type, mime_type=source.file_mime_type)
    parsed_chunks = [
        SampleChunkModel(
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            section_name=chunk.section_name,
            page_number=chunk.page_number,
            row_number=chunk.row_number,
            metadata=chunk.metadata,
        )
        for chunk in parsed_document.chunks
    ]
    return parsed_document.raw_text, str(resolved_path), parsed_chunks


def _build_chunks(source: SampleSourceModel, raw_text: str, parsed_chunks: list[SampleChunkModel]) -> list[SampleChunkModel]:
    if not source.chunks:
        return parsed_chunks or [SampleChunkModel(chunk_index=0, text=raw_text)]

    built_chunks: list[SampleChunkModel] = []
    parsed_by_index = {chunk.chunk_index: chunk for chunk in parsed_chunks if chunk.chunk_index is not None}
    for index, chunk in enumerate(source.chunks):
        chunk_text = chunk.text
        parsed_match = parsed_by_index.get(chunk.chunk_index if chunk.chunk_index is not None else index)
        if chunk_text is None and len(source.chunks) == 1:
            chunk_text = raw_text
        if chunk_text is None and parsed_match is not None:
            chunk_text = parsed_match.text
        if chunk_text is None:
            raise ValueError(f"Chunk {index} for sample source {source.source_id} is missing text")

        built_chunks.append(
            SampleChunkModel(
                chunk_index=chunk.chunk_index if chunk.chunk_index is not None else index,
                text=chunk_text,
                section_name=chunk.section_name or (parsed_match.section_name if parsed_match else None),
                page_number=chunk.page_number if chunk.page_number is not None else (parsed_match.page_number if parsed_match else None),
                row_number=chunk.row_number if chunk.row_number is not None else (parsed_match.row_number if parsed_match else None),
                metadata={**(parsed_match.metadata if parsed_match else {}), **chunk.metadata},
            )
        )
    return built_chunks


def _extracted_property_models(source: SampleSourceModel, chunk_models: list[SampleChunkModel]) -> list[SamplePropertyModel]:
    parsed_chunks = [
        ParsedChunk(
            chunk_index=chunk.chunk_index if chunk.chunk_index is not None else index,
            text=chunk.text or "",
            section_name=chunk.section_name,
            page_number=chunk.page_number,
            row_number=chunk.row_number,
            metadata=chunk.metadata,
        )
        for index, chunk in enumerate(chunk_models)
    ]
    extracted = extract_property_facts(parsed_chunks, source_type=source.source_type)
    return [
        SamplePropertyModel(
            address=fact.address,
            property_type=fact.property_type,
            sq_ft=fact.sq_ft,
            price_per_sq_ft=fact.price_per_sq_ft,
            availability=fact.availability,
            availability_date=fact.availability_date,
            market=fact.market,
            source_page=fact.source_page,
            source_row=fact.source_row,
            extraction_method="heuristic_live_text",
            confidence=fact.confidence,
            source_authority_score=fact.source_authority_score,
            freshness_score=fact.freshness_score,
            duplicate_group_key=f"{' '.join(fact.address.lower().replace(',', ' ').split())}|{fact.property_type}",
            chunk_index=fact.chunk_index,
        )
        for fact in extracted
    ]


def _source_warning_codes(
    validation_warnings: list[dict[str, object]],
    *,
    source: SampleSourceModel,
    property_models: list[SamplePropertyModel],
) -> list[str]:
    codes: list[str] = []
    for warning in validation_warnings:
        if warning.get("source_id") != source.source_id:
            continue
        if property_models and warning.get("code") == "source_without_property_records":
            continue
        codes.append(str(warning["code"]))
    return codes


def _value_is_present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _field_value_string(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


def _property_extra_metadata(property_model: SamplePropertyModel) -> dict[str, object]:
    extra = dict(property_model.model_extra or {})
    return {key: value for key, value in extra.items() if _value_is_present(value)}


def _derived_property_status(property_model: SamplePropertyModel) -> str | None:
    if property_model.status:
        return property_model.status

    availability = str(property_model.availability or "").lower()
    if any(term in availability for term in ("immediate", "available now", "vacant", "now")):
        return "available"
    if any(term in availability for term in ("soon", "q2", "q3", "june", "july", "august")):
        return "coming_soon"
    if property_model.availability_date is not None:
        return "coming_soon"
    return None


def _property_record_kwargs(property_model: SamplePropertyModel) -> dict[str, object]:
    source_metadata = dict(property_model.source_metadata_json or {})
    extra_metadata = _property_extra_metadata(property_model)
    if extra_metadata:
        source_metadata["unknown_columns"] = extra_metadata

    return {
        **{field_name: getattr(property_model, field_name) for field_name in RICH_PROPERTY_VALUE_FIELDS},
        "status": _derived_property_status(property_model),
        "available_from": property_model.available_from or property_model.availability_date,
        "amenities_json": dict(property_model.amenities_json or {}),
        "infrastructure_json": dict(property_model.infrastructure_json or {}),
        "financials_json": dict(property_model.financials_json or {}),
        "tags_json": dict(property_model.tags_json or {}),
        "source_metadata_json": source_metadata,
    }


def _default_field_values(property_model: SamplePropertyModel, chunk_text: str) -> list[SampleFieldValueModel]:
    snippet = chunk_text[:180]
    field_values: list[SampleFieldValueModel] = [
        SampleFieldValueModel(
            field_name="address",
            raw_value=property_model.address,
            normalized_value=property_model.address,
            confidence=property_model.confidence,
            source_span=snippet,
        )
    ]
    field_values.append(
        SampleFieldValueModel(
            field_name="normalized_address",
            raw_value=property_model.address,
            normalized_value=_normalize_address(property_model.address),
            confidence=property_model.confidence,
            source_span=snippet,
        )
    )
    field_values.append(
        SampleFieldValueModel(
            field_name="property_type",
            raw_value=property_model.property_type,
            normalized_value=property_model.property_type,
            confidence=property_model.confidence,
            source_span=snippet,
        )
    )

    if property_model.sq_ft is not None:
        field_values.append(
            SampleFieldValueModel(
                field_name="sq_ft",
                raw_value=f"{property_model.sq_ft:,} SF",
                normalized_value=str(property_model.sq_ft),
                confidence=property_model.confidence,
                source_span=snippet,
            )
        )

    if property_model.price_per_sq_ft is not None:
        field_values.append(
            SampleFieldValueModel(
                field_name="price_per_sq_ft",
                raw_value=f"${property_model.price_per_sq_ft}/SF",
                normalized_value=str(property_model.price_per_sq_ft),
                confidence=property_model.confidence,
                source_span=snippet,
            )
        )

    if property_model.availability is not None:
        field_values.append(
            SampleFieldValueModel(
                field_name="availability",
                raw_value=property_model.availability,
                normalized_value=property_model.availability,
                confidence=property_model.confidence,
                source_span=snippet,
            )
        )

    if property_model.availability_date is not None:
        field_values.append(
            SampleFieldValueModel(
                field_name="availability_date",
                raw_value=property_model.availability or property_model.availability_date.isoformat(),
                normalized_value=property_model.availability_date.isoformat(),
                confidence=property_model.confidence,
                source_span=snippet,
            )
        )

    derived_status = _derived_property_status(property_model)
    if derived_status is not None:
        field_values.append(
            SampleFieldValueModel(
                field_name="status",
                raw_value=property_model.status or property_model.availability or derived_status,
                normalized_value=derived_status,
                confidence=property_model.confidence,
                source_span=snippet,
            )
        )

    if property_model.market is not None:
        field_values.append(
            SampleFieldValueModel(
                field_name="market",
                raw_value=property_model.market,
                normalized_value=property_model.market,
                confidence=property_model.confidence,
                source_span=snippet,
            )
        )

    if property_model.geo_lat is not None and property_model.geo_lng is not None:
        field_values.append(
            SampleFieldValueModel(
                field_name="geo",
                raw_value=f"{property_model.geo_lat},{property_model.geo_lng}",
                normalized_value=f"{property_model.geo_lat},{property_model.geo_lng}",
                confidence=property_model.confidence,
                source_span=snippet,
            )
        )

    existing_field_names = {field_value.field_name for field_value in field_values}
    for field_name in DEFAULT_RICH_FIELD_VALUES:
        if field_name in existing_field_names:
            continue
        value = getattr(property_model, field_name)
        if not _value_is_present(value):
            continue
        serialized_value = _field_value_string(value)
        field_values.append(
            SampleFieldValueModel(
                field_name=field_name,
                raw_value=serialized_value,
                normalized_value=serialized_value,
                confidence=property_model.confidence,
                method=property_model.extraction_method,
                source_span=snippet,
            )
        )

    return field_values


def _missing_property_fields(property_model: SamplePropertyModel) -> list[str]:
    missing: list[str] = []
    if not property_model.address:
        missing.append("address")
    if not property_model.property_type or property_model.property_type == "unknown":
        missing.append("property_type")
    if property_model.sq_ft is None:
        missing.append("sq_ft")
    if property_model.price_per_sq_ft is None:
        missing.append("price_per_sq_ft")
    if property_model.availability is None:
        missing.append("availability")
    if property_model.market is None:
        missing.append("market")
    if property_model.geo_lat is None or property_model.geo_lng is None:
        missing.append("geo")
    return missing


def _validate_dataset(dataset: SampleDatasetModel) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    source_ids: set[str] = set()
    for source in dataset.sources:
        if source.source_id in source_ids:
            warnings.append({"code": "duplicate_source_id", "source_id": source.source_id})
        source_ids.add(source.source_id)

        if source.raw_text is None and source.local_path is None:
            warnings.append({"code": "missing_source_text", "source_id": source.source_id})

        chunk_indexes: set[int] = set()
        for index, chunk in enumerate(source.chunks):
            chunk_index = chunk.chunk_index if chunk.chunk_index is not None else index
            if chunk_index in chunk_indexes:
                warnings.append({"code": "duplicate_chunk_index", "source_id": source.source_id, "chunk_index": chunk_index})
            chunk_indexes.add(chunk_index)

        valid_chunk_indexes = chunk_indexes or {0}
        if not source.properties:
            warnings.append({"code": "source_without_property_records", "source_id": source.source_id, "source_type": source.source_type})
        for property_model in source.properties:
            chunk_index = property_model.chunk_index if property_model.chunk_index is not None else 0
            if chunk_index not in valid_chunk_indexes:
                warnings.append(
                    {
                        "code": "property_references_missing_chunk",
                        "source_id": source.source_id,
                        "address": property_model.address,
                        "chunk_index": chunk_index,
                    }
                )
            missing_fields = _missing_property_fields(property_model)
            if missing_fields:
                warnings.append(
                    {
                        "code": "property_missing_structured_fields",
                        "source_id": source.source_id,
                        "address": property_model.address,
                        "missing_fields": missing_fields,
                    }
                )

    return warnings


async def _find_existing_source(
    session: AsyncSession,
    dataset: SampleDatasetModel,
    source: SampleSourceModel,
    *,
    resolved_local_path: str | None,
    content_hash: str,
) -> SourceDocument | None:
    if source.slack_file_id:
        statement = select(SourceDocument).where(
            SourceDocument.slack_team_id == dataset.team_id,
            SourceDocument.slack_file_id == source.slack_file_id,
        )
        existing = await session.scalar(statement)
        if existing is not None:
            return existing

    if source.slack_ts:
        statement = select(SourceDocument).where(
            SourceDocument.slack_team_id == dataset.team_id,
            SourceDocument.slack_channel_id == dataset.channel_id,
            SourceDocument.slack_ts == source.slack_ts,
        )
        existing = await session.scalar(statement)
        if existing is not None:
            return existing

    if resolved_local_path is not None:
        statement = (
            select(SourceDocument)
            .where(
                SourceDocument.source_type == source.source_type,
                SourceDocument.local_path == resolved_local_path,
            )
            .order_by(SourceDocument.ingested_at.desc())
        )
        existing = await session.scalar(statement)
        if existing is not None:
            return existing

    if source.slack_file_id or source.slack_ts:
        return None

    statement = (
        select(SourceDocument)
        .where(
            SourceDocument.source_type == source.source_type,
            SourceDocument.content_hash == content_hash,
        )
        .order_by(SourceDocument.ingested_at.desc())
    )
    return await session.scalar(statement)


def _slack_post_identity(dataset: SampleDatasetModel, source: SampleSourceModel) -> tuple[str, str] | None:
    if source.slack_file_id:
        ts_part = source.slack_ts or "unknown-ts"
        return f"file:{dataset.channel_id}:{ts_part}:{source.slack_file_id}", "file_share"
    if source.slack_ts:
        return f"message:{dataset.channel_id}:{source.slack_ts}", "message"
    return None


async def _upsert_slack_source_post(
    session: AsyncSession,
    *,
    source_record: SourceDocument,
    dataset: SampleDatasetModel,
    source: SampleSourceModel,
) -> bool:
    identity = _slack_post_identity(dataset, source)
    if identity is None:
        return False

    post_key, post_type = identity
    statement = select(SlackSourcePost).where(
        SlackSourcePost.slack_team_id == dataset.team_id,
        SlackSourcePost.post_key == post_key,
    )
    source_post = await session.scalar(statement)
    created = source_post is None
    if source_post is None:
        source_post = SlackSourcePost(
            source_document_id=source_record.id,
            post_key=post_key,
            post_type=post_type,
        )

    source_post.source_document_id = source_record.id
    source_post.post_key = post_key
    source_post.post_type = post_type
    source_post.slack_team_id = dataset.team_id
    source_post.slack_channel_id = dataset.channel_id
    source_post.slack_channel_name = dataset.channel_name
    source_post.slack_user_id = source.slack_user_id
    source_post.slack_user_name = source.slack_user_name
    source_post.slack_ts = source.slack_ts
    source_post.slack_thread_ts = source.slack_thread_ts
    source_post.slack_file_id = source.slack_file_id
    source_post.source_url = _normalize_source_url(source.source_url)
    source_post.posted_at = source.posted_at
    session.add(source_post)
    return created


async def import_sample_dataset(dataset: SampleDatasetModel, sample_data_dir: Path) -> dict[str, object]:
    from app.routing.query_constructor import refresh_property_record_location_snapshot

    imported_sources = 0
    imported_chunks = 0
    imported_property_records = 0
    imported_jobs = 0
    imported_slack_source_posts = 0
    validation_warnings = _validate_dataset(dataset)
    chunk_ids_to_index = []

    async with SessionFactory() as session:
        async with session.begin():
            for source in dataset.sources:
                raw_text, resolved_local_path, parsed_chunks = _resolve_document(source, sample_data_dir)
                content_hash = _sha256(raw_text)
                payload_hash = _sha256(json.dumps(source.model_dump(mode="json"), sort_keys=True))
                source_record = await _find_existing_source(
                    session,
                    dataset,
                    source,
                    resolved_local_path=resolved_local_path,
                    content_hash=content_hash,
                )

                if source_record is None:
                    source_record = SourceDocument(source_type=source.source_type)

                source_record.source_type = source.source_type
                source_record.slack_team_id = dataset.team_id
                source_record.slack_channel_id = dataset.channel_id
                source_record.slack_channel_name = dataset.channel_name
                source_record.slack_user_id = source.slack_user_id
                source_record.slack_user_name = source.slack_user_name
                source_record.slack_ts = source.slack_ts
                source_record.slack_thread_ts = source.slack_thread_ts
                source_record.slack_file_id = source.slack_file_id
                source_record.file_name = source.file_name
                source_record.file_mime_type = source.file_mime_type
                source_record.source_url = _normalize_source_url(source.source_url)
                source_record.local_path = resolved_local_path
                source_record.raw_text = raw_text
                source_record.raw_payload_hash = payload_hash
                source_record.content_hash = content_hash
                source_record.posted_at = source.posted_at
                source_record.status = "indexed"
                source_record.error_message = None

                session.add(source_record)
                await session.flush()
                if await _upsert_slack_source_post(
                    session,
                    source_record=source_record,
                    dataset=dataset,
                    source=source,
                ):
                    imported_slack_source_posts += 1
                await _clear_existing_children(session, source_record.id)

                chunk_models = _build_chunks(source, raw_text, parsed_chunks)
                property_models = source.properties or _extracted_property_models(source, chunk_models)
                chunk_records: dict[int, Chunk] = {}
                for chunk_model in chunk_models:
                    chunk_record = Chunk(
                        document_id=source_record.id,
                        chunk_index=chunk_model.chunk_index or 0,
                        chunk_text=chunk_model.text or raw_text,
                        page_number=chunk_model.page_number,
                        row_number=chunk_model.row_number,
                        section_name=chunk_model.section_name,
                        token_count=len((chunk_model.text or raw_text).split()),
                        metadata_json={
                            "sample_source_id": source.source_id,
                            "source_type": source.source_type,
                            "source_property_count": len(property_models),
                            "source_validation_warning_codes": _source_warning_codes(
                                validation_warnings,
                                source=source,
                                property_models=property_models,
                            ),
                            "structured_extraction_mode": "manifest" if source.properties else "heuristic_live_text",
                            **chunk_model.metadata,
                        },
                    )
                    session.add(chunk_record)
                    await session.flush()
                    chunk_records[chunk_record.chunk_index] = chunk_record
                    chunk_ids_to_index.append(chunk_record.id)
                    imported_chunks += 1

                for property_model in property_models:
                    chunk_index = property_model.chunk_index if property_model.chunk_index is not None else 0
                    supporting_chunk = chunk_records.get(chunk_index)
                    property_record = PropertyRecord(
                        document_id=source_record.id,
                        chunk_id=supporting_chunk.id if supporting_chunk else None,
                        address=property_model.address,
                        normalized_address=_normalize_address(property_model.address),
                        property_type=property_model.property_type,
                        sq_ft=property_model.sq_ft,
                        price_per_sq_ft=property_model.price_per_sq_ft,
                        price_basis=property_model.price_basis,
                        availability=property_model.availability,
                        availability_date=property_model.availability_date,
                        market=property_model.market,
                        geo_lat=property_model.geo_lat,
                        geo_lng=property_model.geo_lng,
                        **_property_record_kwargs(property_model),
                        source_page=property_model.source_page,
                        source_row=property_model.source_row,
                        extraction_method=property_model.extraction_method,
                        confidence=property_model.confidence,
                        source_authority_score=property_model.source_authority_score,
                        freshness_score=property_model.freshness_score,
                        duplicate_group_key=property_model.duplicate_group_key,
                    )
                    session.add(property_record)
                    await session.flush()

                    field_values = property_model.field_values or _default_field_values(
                        property_model,
                        supporting_chunk.chunk_text if supporting_chunk else raw_text,
                    )
                    for field_value in field_values:
                        session.add(
                            PropertyFieldValue(
                                property_record_id=property_record.id,
                                field_name=field_value.field_name,
                                raw_value=field_value.raw_value,
                                normalized_value=field_value.normalized_value,
                                confidence=field_value.confidence,
                                method=field_value.method,
                                source_span=field_value.source_span,
                                extractor_version=field_value.extractor_version,
                            )
                        )

                    imported_property_records += 1

                for job_type in ("extract", "index"):
                    session.add(
                        IngestionJob(
                            job_type=job_type,
                            source_document_id=source_record.id,
                            status="succeeded",
                            attempt_count=1,
                            checkpoint_json={
                                "sample_source_id": source.source_id,
                                "job_type": job_type,
                            },
                            started_at=source.posted_at,
                            finished_at=source.posted_at,
                        )
                    )
                    imported_jobs += 1

                imported_sources += 1

    location_lexicon_snapshot = await refresh_property_record_location_snapshot()
    vector_index_result = await index_chunks_by_ids(chunk_ids_to_index)

    return {
        "status": "imported",
        "sample_data_dir": str(sample_data_dir),
        "imported_source_count": imported_sources,
        "imported_chunk_count": imported_chunks,
        "imported_property_record_count": imported_property_records,
        "imported_job_count": imported_jobs,
        "imported_slack_source_post_count": imported_slack_source_posts,
        "location_lexicon_snapshot": {
            "value_count": location_lexicon_snapshot.get("value_count", 0),
        },
        "vector_index": vector_index_result,
        "validation_warning_count": len(validation_warnings),
        "validation_warnings": validation_warnings,
        "database_counts": await collect_database_counts(),
    }


async def _clear_existing_children(session: AsyncSession, document_id: object) -> None:
    await session.execute(delete(IngestionJob).where(IngestionJob.source_document_id == document_id))
    await session.execute(delete(PropertyRecord).where(PropertyRecord.document_id == document_id))
    await session.execute(delete(Chunk).where(Chunk.document_id == document_id))


async def collect_database_counts() -> dict[str, int]:
    async with SessionFactory() as session:
        counts: dict[str, int] = {}
        models = {
            "source_documents": SourceDocument,
            "slack_source_posts": SlackSourcePost,
            "chunks": Chunk,
            "property_records": PropertyRecord,
            "property_field_values": PropertyFieldValue,
            "ingestion_jobs": IngestionJob,
            "queries": Query,
            "evidence_items": EvidenceItem,
            "answer_snapshots": AnswerSnapshot,
            "agent_runs": AgentRun,
        }

        for label, model in models.items():
            counts[label] = int(await session.scalar(select(func.count()).select_from(model)) or 0)

        return counts


async def import_sample_data(sample_data_dir: Path, *, include_generated: bool = True) -> dict[str, object]:
    dataset = load_sample_manifest(sample_data_dir, include_generated=include_generated)
    return await import_sample_dataset(dataset, sample_data_dir)