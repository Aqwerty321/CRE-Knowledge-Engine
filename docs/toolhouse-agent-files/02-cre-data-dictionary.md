# CRE Data Dictionary For Toolhouse

Use this file as a compact domain and schema guide for the `CRE MCP Look Deeper Analyst` worker.

## Core Principle

Commercial real estate facts must be grounded in backend evidence. Toolhouse can interpret facts, explain tradeoffs, and identify gaps, but it must not create property facts that are not returned by MCP.

## Canonical Entities

### `source_documents`

Represents the original evidence container: Slack message, thread reply, PDF, CSV, XLSX, or text file.

Important fields:

- `id`: internal UUID.
- `source_type`: `slack_message`, `slack_thread_reply`, `pdf`, `csv`, `xlsx`, or `text`.
- `slack_team_id`, `slack_channel_id`, `slack_channel_name`: Slack source location.
- `slack_user_id`, `slack_user_name`: sender or uploader.
- `slack_ts`, `slack_thread_ts`, `slack_file_id`: Slack identity fields.
- `file_name`, `file_mime_type`, `source_url`, `local_path`: file and link metadata.
- `raw_text`: extracted text when available.
- `posted_at`: source creation time.
- `ingested_at`: backend intake time.
- `status`: `pending`, `extracted`, `indexed`, `failed`, or `skipped`.

### `chunks`

Represents retrieval-ready source text.

Important fields:

- `id`: internal UUID.
- `document_id`: source document UUID.
- `chunk_index`: stable document order.
- `chunk_text` or `text_preview`: source text or preview.
- `page_number`: PDF page when available.
- `row_number`: CSV/XLSX row when available.
- `section_name`: page, heading, sheet, or row range label.
- `embedding_id`: Qdrant point ID when semantic indexing exists.

### `property_records`

Represents normalized CRE facts extracted from a source.

Important fields:

- `id`: internal UUID.
- `document_id`: source document UUID.
- `chunk_id`: best supporting chunk UUID.
- `address`: display address as extracted.
- `normalized_address`: canonical comparison address.
- `property_name`, `listing_id`, `source_dataset`: identity and dataset metadata when available.
- `property_type`: `office`, `industrial`, `retail`, `mixed_use`, `land`, `multifamily`, `hospitality`, `medical`, `data_center`, `self_storage`, `parking`, or `unknown`.
- `property_subtype`, `asset_class`, `usage_type`: richer property taxonomy and use labels.
- `status`, `status_date`: listing status such as `available`, `coming_soon`, `under_offer`, `leased`, `sold`, `pipeline`, or `withdrawn`.
- `sq_ft`: whole square feet.
- `building_area_sq_ft`, `leasable_area_sq_ft`, `lot_size_sq_ft`, `lot_size_acres`: additional physical size fields.
- `year_built`, `year_renovated`, `clear_height_ft`, `dock_doors`, `drive_in_doors`, `truck_court_depth_ft`, `trailer_parking_spaces`, `parking_spaces`: physical and industrial attributes.
- `facing`, `furnishing_status`: orientation/frontage and fit-out state.
- `price_per_sq_ft`: numeric rent or price per square foot as a string in JSON.
- `price_basis`: `annual_rent`, `monthly_rent`, `sale_price`, or `unknown`.
- `asking_rent`, `asking_rent_period`, `rent_currency`, `sale_price`, `price_currency`, `lease_type`: commercial terms when available.
- `availability`: display availability label.
- `availability_date`: normalized date when known.
- `available_from`, `vacancy_status`, `occupancy_status`: availability/occupancy fields when available.
- `market`: market or submarket.
- `country_code`, `country`, `region`, `state_province`, `county_district`, `city`, `locality`, `neighborhood`, `submarket`, `postal_code`: geography and locality fields.
- `geo_lat`, `geo_lng`, `geo_point`, `geocode_source`, `geocode_confidence`, `map_url`: coordinates, optional PostGIS geography point, geocode provenance, and map link.
- `loading_access`, `yard_area_sq_ft`, `cold_storage`, `sprinklered`, `hvac_type`, `nearest_highway`, `highway_distance_miles`, `airport_distance_miles`, `port_distance_miles`, `rail_access`, `public_transit_notes`, `transit_score`, `ev_charging`, `fiber_available`: infrastructure and amenity fields.
- `additional_information`: free-form remarks/comments captured during ingestion.
- `amenities_json`, `infrastructure_json`, `financials_json`, `tags_json`, `source_metadata_json`: structured overflow and dataset provenance.
- `source_page`, `source_row`: citation detail.
- `extraction_method`: `deterministic`, `heuristic`, `semantic`, or `manual_seed`.
- `confidence`: extraction confidence.
- `source_authority_score`: source reliability score.
- `freshness_score`: recency score.
- `duplicate_group_key`: normalized address/type grouping key.

### `property_field_values`

Represents field-level provenance when available.

Important fields:

- `field_name`: example `sq_ft` or `price_per_sq_ft`.
- `raw_value`: exact source value.
- `normalized_value`: backend normalized value.
- `confidence`: field-level confidence.
- `method`: extraction method.
- `source_span`: snippet, page span, row cell, or Slack span supporting the value.

### `queries`

Represents a user question and backend route decision.

Important fields:

- `id`: query UUID.
- `query_text`: user question.
- `route_mode`: `instant`, `hybrid`, `agentic`, or `failed`.
- `route_confidence`: backend confidence.
- `reason_codes`: route and query-constructor reasons.

### `evidence_items`

Connects an answer to sources, chunks, and property records.

Important fields:

- `id`: evidence UUID. This is the only value Toolhouse may cite in `cited_evidence_ids`.
- `query_id`: query UUID.
- `document_id`: source document UUID.
- `chunk_id`: chunk UUID.
- `property_record_id`: property record UUID.
- `relevance_score`: retrieval or ranking score.
- `matched_fields`: fields or terms that matched.
- `source_summary`: short citation display string.

### `answer_snapshots`

Stores the replayable answer state.

Important fields:

- `rendered_answer`: exact Slack-visible local answer.
- `route_mode`: route used at answer time.
- `filters_json`: structured filters, query constructor, missing-data explanation, or audit report.
- `evidence_ids`: evidence IDs used by the answer.
- `dependency_state_json`: Qdrant, Toolhouse, LLM, fallback state.
- `model_versions_json`: answer, prompt, query-constructor, or embedding versions.

## Property Type Normalization

Canonical property types:

- `office`
- `industrial`
- `retail`
- `mixed_use`
- `land`
- `multifamily`
- `hospitality`
- `medical`
- `data_center`
- `self_storage`
- `parking`
- `unknown`

Examples:

- `Class A Office`, `creative office`, and `medical office` map to `office`.
- `warehouse`, `flex`, `distribution`, `logistics`, and `yard` map to `industrial`.
- Unknown or ambiguous types stay `unknown`.

## Numeric And Date Rules

- Store square footage as integer `sq_ft`.
- Accept source phrases like `SF`, `sq ft`, `sqft`, `RSF`, and compact values like `4.8k SF` only if the backend returned normalized values.
- Store rent or price in `price_per_sq_ft`.
- Do not compare sale price and annual rent unless `price_basis` makes the comparison valid.
- Treat missing `price_basis` as `unknown`.
- Preserve raw availability text in `availability`.
- Use `availability_date` only when the backend normalized one.
- For demo date math, the reference date is 2026-05-17.

## Query Constructor Filters

Common filters Toolhouse may see or pass to MCP:

```json
{
  "intent": "property_search | exact_lookup | aggregation | tenant_fit | data_completeness",
  "property_types": ["office", "industrial"],
  "address_terms": ["120 main st"],
  "uploader_names": ["John", "Sarah", "Maya", "Priya"],
  "markets": ["Downtown", "Harbor District"],
  "locations": ["Atlanta", "London", "Westside"],
  "statuses": ["available", "coming_soon"],
  "usage_types": ["logistics", "office"],
  "facing": ["corner"],
  "furnishing_statuses": ["turnkey", "shell"],
  "infrastructure_terms": ["loading dock", "highway", "fiber"],
  "keywords": ["loading dock", "yard", "logistics", "tenant"],
  "price_per_sq_ft_lt": "25",
  "price_per_sq_ft_gt": null,
  "sale_price_lt": "5000000",
  "sale_price_gt": null,
  "cap_rate_gte": "0.055",
  "cap_rate_lte": null,
  "sq_ft_gte": 30000,
  "sq_ft_lte": null,
  "clear_height_ft_gte": "28",
  "dock_doors_gte": 4,
  "trailer_parking_spaces_gte": 40,
  "parking_spaces_gte": 100,
  "availability_before": "2026-08-31",
  "require_immediate": false,
  "requires_coordinates": true,
  "aggregate": "count | total | average | null",
  "aggregate_field": "property_records | sq_ft | price_per_sq_ft | null",
  "sort": "price_asc | sale_price_asc | cap_rate_desc | size_desc | availability_asc | tenant_fit | null",
  "limit": 5
}
```

Geospatial notes:

- In PostGIS-capable deployments, Alembic creates `property_records.geo_point` as `geography(Point,4326)`, backfills it from `geo_lng`/`geo_lat`, and keeps it synced with a trigger.
- In SQLite or non-PostGIS Postgres environments, MCP tools keep using `geo_lat` and `geo_lng` numeric fallback. Treat `nearby_properties.spatial_backend.status` as the runtime truth.
- `requires_coordinates` filters out records without both numeric coordinates and lets answers expose `map_url` when available.

## Ranking And Conflict Guidance

Use backend coordinator tools for higher-level database work:

- `summarize_inventory` for broad inventory, type/market counts, and cheapest/largest/soonest slices.
- `rank_properties` for subjective objective scoring such as logistics fit, cheapest, largest, available soon, or balanced review.
- `get_property_timeline` for provenance history across one address, property ID, or duplicate group.
- `find_property_conflicts` for duplicate groups with conflicting size, rent, or availability values.

Pass `query_id` to these tools when their results may need to become citable. Returned `evidence_id` values and evidence expansions are backend-minted for that query; raw property IDs, source IDs, chunk IDs, and Slack IDs are not valid citation IDs.

When sources conflict, prefer backend-ranked evidence. If the backend exposes scores, explain the tradeoff using:

1. higher source authority;
2. higher freshness;
3. deterministic or manual-seed extraction over low-confidence semantic extraction;
4. explicit correction sources over older inventory rows when the correction references the same property;
5. duplicate grouping by `duplicate_group_key`.

Do not perform final numeric aggregation or distance calculations yourself. Use MCP tools for user-facing counts, sums, averages, ranges, and proximity rankings.

## Citation Display Preference

When explaining citations in prose, prefer this order:

1. file name or Slack message source;
2. page or row;
3. poster/uploader;
4. posted date;
5. Slack/source URL when available.

Still, the machine-readable citation must be `evidence_id`.
