# Large Corpus And Rich Property Schema Plan

## Goal

Expand the demo corpus from 25 structured property rows to a 2,000-3,000 row reviewer-ready corpus with broad USA and Europe coverage, richer property attributes, coordinates, map links, Slack-seeded source provenance, and source citations that prefer real Slack conversation permalinks instead of non-opening `demo.local` links.

This should stay truthful: public datasets can supply geography, addresses, coordinates, building footprints, postal/locality context, and some building metadata. Broker/listing fields such as asking rent, furnishing, status, facing, usage, availability, and detailed infrastructure are usually not available from permissive public CRE datasets at scale, so those fields should be generated as deterministic synthetic demo enrichment unless a verified downloadable source explicitly contains them.

## Implementation Status - 2026-05-19

The first implementation slice is complete and checked into the working tree:

- Added nullable rich `property_records` columns and Alembic revision `20260519_0004_expand_property_records.py`.
- Expanded the sample importer with rich fields, alias handling, `additional_information`, unknown-column preservation, generated manifest merging, and a test-only `include_generated` switch for fast DB fixtures.
- Added deterministic large-corpus generation through `uv run cre-cli build-large-corpus --rows 2400 --seed 20260519`.
- Generated four Slack-seedable CSV shards and `sample-data/generated/import-manifest-large-corpus.json`, covering 2,400 rich property records.
- Added Slack seed-plan entries for the generated shards.
- Updated live Slack ingestion and demo sync so shared-file citations prefer Slack message permalinks when available.
- Suppressed fake `demo.local` links in Show Sources and local sample import.
- Extended routing, structured retrieval, answer serialization, Toolhouse serialization, and schema context for the new fields.
- Updated README, sample-data docs, data dictionaries, Slack runbook, and Toolhouse-facing docs.
- Added focused tests for generated corpus loading, rich aliases, Slack permalink preference, no `demo.local` source display, rich structured filters, generated DB persistence, and fast compact DB fixtures.

Validated locally:

```bash
uv run pytest tests/test_instant_answers.py tests/test_demo_battery.py tests/test_toolhouse_tools.py tests/test_slack_loop.py tests/test_slack_demo_sync.py -q
# 74 passed in 31.13s

uv run pytest -q --durations=20
# 126 passed in 27.25s

git diff --check
# no output
```

## Research Notes

The available deferred MCP loader did not expose a separate web search endpoint during this pass, so the research used the available page-fetch and SearXNG deep-read tools against known public data sources.

| Source | Useful for | Notes |
| --- | --- | --- |
| [OpenAddresses](https://openaddresses.io/) and [batch data](https://batch.openaddresses.io/data) | Global addresses, coordinates, buildings, parcels, centerlines | OpenAddresses says it is open data, mostly attribution-only, with whole-world coverage. Batch collections include US regional downloads and global collections plus individual US and Europe sources. Best default address/coordinate backbone. |
| [Microsoft Global ML Building Footprints](https://github.com/microsoft/GlobalMLBuildingFootprints) | Building footprint polygons, some height estimates, global USA/Europe coverage | Dataset is described as open, worldwide, line-delimited GeoJSON, EPSG:4326, CDLA Permissive 2.0. Strong candidate for centroid, footprint area, height, geometry metadata. |
| [Microsoft US Building Footprints](https://github.com/microsoft/USBuildingFootprints) | US-only building polygons | 129M+ US footprints, EPSG:4326, but ODbL. Prefer Global ML footprints if license simplicity matters. |
| [GeoNames data export](https://www.geonames.org/export/) and [postal downloads](https://download.geonames.org/export/zip/) | Postal code, locality, admin division, latitude/longitude enrichment | GeoNames publishes daily country files and postal downloads. Terms are CC BY style attribution. Useful for locality, neighborhood-ish place names, admin levels, and geocode fallback. |
| [Get energy performance of buildings data](https://get-energy-performance-data.communities.gov.uk/) | England/Wales domestic, non-domestic, public-building EPC/DEC data | Bulk CSV and API exist, but require GOV.UK One Login and have licensing/privacy restrictions. Use only as optional user-provided source, not an automatic default download. |
| [data.europa.eu](https://data.europa.eu/en) | Discovery portal for country datasets | Useful as future discovery surface. Do not treat portal search results as direct normalized input without source-specific licence checks. |

## Target Corpus Shape

Use a deterministic generation target of 2,400 rows by default, with CLI knobs for 2,000-3,000.

Recommended default distribution:

| Dimension | Target |
| --- | --- |
| Geography | 60% USA, 35% Europe, 5% other global control rows. |
| USA markets | New York, Boston, Washington DC, Atlanta, Miami, Chicago, Dallas-Fort Worth, Houston, Austin, Denver, Los Angeles/Inland Empire, San Francisco Bay Area, Seattle. |
| Europe markets | London, Manchester, Dublin, Paris, Lyon, Berlin, Hamburg, Munich, Amsterdam/Rotterdam, Madrid, Barcelona, Milan, Stockholm, Copenhagen. |
| Property types | industrial/logistics 22%, office 18%, retail 14%, multifamily 12%, mixed_use 10%, land/development 8%, hospitality 5%, medical/life_science 4%, data_center 3%, self_storage 2%, parking 2%. |
| Status | available 35%, coming_soon 18%, under_offer 12%, leased 12%, sold 7%, withdrawn 5%, pipeline 6%, unknown 5%. |
| Transaction mode | lease 65%, sale 20%, lease_or_sale 10%, research_only 5%. |
| Source mix | 70% generated CSV/XLSX source rows, 20% Slack broker-note text rows, 10% public data backbone rows or enrichment manifests. |

## Schema Strategy

Keep query-critical fields as first-class columns on `property_records`. Keep long-tail, sparse, or source-specific values in JSONB and `property_field_values` so the schema does not become brittle.

### Add First-Class Columns

Geography and location:

- `country_code`, `country`, `region`, `state_province`, `county_district`, `city`, `locality`, `neighborhood`, `submarket`, `postal_code`
- `timezone`, `geocode_source`, `geocode_confidence`, `map_url`
- Existing `geo_lat` and `geo_lng` remain; consider optional `geo_point` only if PostGIS is adopted later.

Property identity:

- `property_name`, `unit_suite`, `listing_id`, `external_source_id`, `source_dataset`
- `property_subtype`, `asset_class`, `usage_type`, `zoning`, `tenure`
- `status`, `status_date`, `listing_url`

Physical attributes:

- `building_area_sq_ft`, `leasable_area_sq_ft`, `lot_size_sq_ft`, `lot_size_acres`
- `floor_number`, `floor_count`, `year_built`, `year_renovated`
- `ceiling_height_ft`, `clear_height_ft`, `dock_doors`, `drive_in_doors`, `truck_court_depth_ft`, `trailer_parking_spaces`
- `parking_spaces`, `parking_ratio`, `elevators`, `frontage_ft`, `facing`
- `furnishing_status` with importer aliases for `furnishing`, `furnished`, and the user typo `funishing`
- `condition_grade`, `energy_rating`, `green_certification`, `accessibility_features`

Commercial attributes:

- `asking_rent`, `asking_rent_period`, `rent_currency`, `service_charge`, `operating_expenses`, `taxes`
- `sale_price`, `price_currency`, `cap_rate`, `occupancy_pct`
- `lease_type`, `min_lease_months`, `max_lease_months`, `incentives`, `deposit_amount`, `fit_out_allowance`

Availability and operations:

- `available_from`, `vacancy_status`, `occupancy_status`
- `loading_access`, `yard_area_sq_ft`, `cold_storage`, `sprinklered`, `hvac_type`, `power_capacity`, `floor_load_psf`
- `nearest_highway`, `highway_distance_miles`, `airport_distance_miles`, `port_distance_miles`, `rail_access`, `transit_score`, `public_transit_notes`, `bike_parking`, `ev_charging`, `fiber_available`

Remarks and flexible metadata:

- `additional_information` as `Text`, for remarks, broker comments, caveats, tour notes, or source-specific freeform observations.
- `amenities_json`, `infrastructure_json`, `financials_json`, `tags_json`, `source_metadata_json` as JSONB for sparse values.

### Keep Existing Field-Level Provenance

For every new field that came from a source cell, generated enrichment rule, or parser, write a `property_field_values` row with:

- `field_name`
- raw and normalized values
- confidence
- method such as `openaddresses_seed`, `ml_building_footprint`, `geonames_enrichment`, `synthetic_cre_profile`, `manual_seed`, or `heuristic_live_text`
- source span like `row 148 column furnishing_status`

This gives Toolhouse and Show Sources an audit trail without requiring every new field to be shown in normal answers.

## Migration And Model Work

1. Add Alembic revision `20260519_0004_expand_property_records.py`.
2. Add nullable columns first to avoid breaking existing tests and local sample imports.
3. Add indexes for high-use filters:
   - `property_type`, `property_subtype`, `usage_type`, `status`
   - `country_code`, `city`, `market`, `submarket`, `neighborhood`
   - `price_per_sq_ft`, `asking_rent`, `sale_price`, `sq_ft`, `availability_date`, `available_from`
   - `geo_lat`, `geo_lng` together for current distance code
4. Update `PropertyRecord` in [app/models/core.py](../app/models/core.py).
5. Update serializers in [app/answering/query_service.py](../app/answering/query_service.py), [app/toolhouse/tools.py](../app/toolhouse/tools.py), [app/toolhouse/evidence_context.py](../app/toolhouse/evidence_context.py), and thread follow-up context.
6. Update [docs/cre-data-dictionary.md](cre-data-dictionary.md) and Toolhouse data dictionary files.

## Corpus Builder Design

Add a deterministic builder instead of hand-authoring a 2,400-row JSON manifest.

Suggested files:

- `app/ingestion/large_corpus_builder.py`
- `app/ingestion/public_datasets.py`
- `scripts/build-large-corpus.py`
- `sample-data/generated/` for generated CSV/XLSX files
- `sample-data/generated/manifest-fragments/` if the final manifest is assembled from shards

Pipeline:

1. Download or read cached public source extracts into `downloads/open-data/`.
2. Normalize rows into a small internal `AddressSeed` model with address, country, admin divisions, city/locality, postal code, lat/lng, dataset source, licence attribution, and optional geometry/height.
3. Sample deterministic rows across the target geography and property-type distribution.
4. Generate synthetic CRE profile fields from seeded random distributions, market bands, and property-type rules.
5. Generate map links from coordinates, preferably without API keys:
   - `https://www.google.com/maps/search/?api=1&query={lat},{lng}`
   - or OpenStreetMap fallback: `https://www.openstreetmap.org/?mlat={lat}&mlon={lng}#map=17/{lat}/{lng}`
6. Emit source files split by channel and region, for example:
   - `global-cre-corpus-us-1.csv`
   - `global-cre-corpus-us-2.csv`
   - `global-cre-corpus-europe-1.csv`
   - `global-cre-corpus-europe-2.csv`
   - `global-cre-corpus-market-notes.txt`
7. Generate a manifest that references these files as Slack-shaped sources and includes row-level property records.

Important: commit only the 2,000-3,000 row generated demo corpus and compact attribution metadata. Do not commit multi-GB raw public downloads.

## Importer Changes

1. Expand `SamplePropertyModel` in [app/ingestion/sample_importer.py](../app/ingestion/sample_importer.py) with the new fields.
2. Add a column alias map for common spellings:
   - `neighbourhood` and `neighborhood`
   - `locality`, `city`, `submarket`
   - `furnishing`, `furnished`, `funishing`
   - `lat`, `latitude`, `geo_lat`
   - `lng`, `lon`, `longitude`, `geo_lng`
   - `remarks`, `comments`, `notes`, `additional_information`
3. Store unknown but non-empty columns into `source_metadata_json` or `amenities_json` instead of dropping them.
4. Ensure `additional_information` is appended from explicit remarks/comments plus extracted tour-note snippets.
5. Continue writing default `PropertyFieldValue` rows for every query-relevant field.
6. Keep import idempotent by source ID and content hash.

## Slack Seeding And Citation Links

Do not upload 2,400 individual Slack messages. Upload the generated corpus as a small number of CSV/XLSX files plus a handful of broker-note messages.

Required changes:

1. Extend [app/slack/demo_files.py](../app/slack/demo_files.py) to include generated corpus files in the default seed plan.
2. Keep channel distribution clean:
   - `cre-listings`: listing corpus files and broker-note sources
   - `cre-market-research`: market context, enrichment, source-attribution files
   - `cre-private-demo`: sensitive or internal-only sample subset
   - `cre-agent-qa`: a few prompt examples only
3. In [app/slack/demo_sync.py](../app/slack/demo_sync.py), prefer the Slack message permalink for uploaded file shares:
   - currently file sources use `file_payload.permalink`
   - change file matching to also use the share message `ts` and `chat_getPermalink(channel, message_ts)`
   - store that message permalink as the primary citation URL
   - keep file permalink separately in metadata if needed
4. Add explicit source fields if needed:
   - `source_documents.source_url`: primary citation URL, preferably Slack message permalink
   - `source_documents.metadata_json.slack_file_permalink`: file URL if different
   - or use `slack_source_posts.source_url` as the source-of-truth post permalink and resolve citations through that table
5. Update `build_show_sources_text` in [app/slack/service.py](../app/slack/service.py) so it formats Slack links as `<url|Open source in Slack>`.
6. Remove `https://demo.local/...` from generated manifest source URLs. For local-only sources, leave `source_url` empty and rely on file name, page, row, and source summary. This avoids fake links that look clickable but fail.

Answer rendering should still cite source labels inline, while Show Sources should expose the Slack permalink and row/page details.

## Retrieval And Routing Updates

1. Expand `PROPERTY_TYPE_ALIASES` in [app/routing/query_constructor.py](../app/routing/query_constructor.py) for:
   - `medical`, `life_science`, `hospitality`, `data_center`, `self_storage`, `parking`, `student_housing`, `senior_housing`, `cold_storage`
2. Add field-intent detection for:
   - locality/neighborhood/submarket
   - status and availability
   - facing/orientation
   - furnishing/furnished
   - usage/use case
   - infrastructure/logistics features
   - map/location/coordinates
3. Extend structured filters in [app/retrieval/structured_service.py](../app/retrieval/structured_service.py):
   - region/country/city/neighborhood/submarket filters
   - status and transaction mode filters
   - amenity/infrastructure filters backed by first-class fields and JSONB tags
   - map-link and coordinate queries
4. Keep the current numeric `geo_lat`/`geo_lng` distance logic for 2-3k rows. PostGIS can wait unless the corpus grows past this scale or needs polygon intersection.
5. Update Toolhouse MCP tools to expose the new filter vocabulary without allowing raw SQL.

## Data Quality And Trust Rules

1. Every generated property must have at least one source document, chunk, and source row.
2. Every coordinate row must include `geocode_source` and `geocode_confidence`.
3. Every synthetic commercial field must have `extraction_method=synthetic_cre_profile` or field-level method metadata.
4. Generated synthetic rents/prices/statuses must be marked as demo benchmark facts, not real market claims.
5. Public source attribution should be preserved in `source_metadata_json` and docs.
6. Quality report should track:
   - row count
   - geography distribution
   - property-type distribution
   - status distribution
   - coordinate coverage
   - map-link coverage
   - Slack permalink coverage
   - missing remarks/additional-information coverage

## Tests

Add focused tests rather than only expanding golden snapshots.

Suggested tests:

1. Manifest/model validation accepts every new field and alias.
2. Large corpus builder is deterministic for the same seed.
3. Generated corpus has 2,000-3,000 property records and meets distribution tolerances.
4. Import writes `additional_information`, `furnishing_status`, `facing`, locality/neighborhood, status, infrastructure fields, coordinates, and map URL.
5. Unknown source columns are preserved in metadata instead of dropped.
6. Show Sources never prints `demo.local` for generated sources.
7. Live Slack demo sync prefers message permalinks over file permalinks for file-upload sources.
8. Structured queries can filter by neighborhood, status, furnishing, facing, usage, and infrastructure.
9. Coordinate queries return map URLs and distance-ranked results.
10. Toolhouse MCP serialization includes new fields and does not expose raw SQL.

## Rollout Phases

### Phase 1 - Schema And Importer

- Add migration and ORM fields.
- Update Pydantic sample models and serializers.
- Update docs and Toolhouse schema descriptions.
- Add alias handling for remarks/comments/additional info.

Acceptance: existing sample manifest imports unchanged, full test suite still passes.

### Phase 2 - Corpus Builder

- Build deterministic generator with no network requirement when cached seed files exist.
- Add optional downloader/cache for OpenAddresses, GeoNames, and Microsoft Global ML footprints.
- Generate 2,400-row default CSV/XLSX shards.
- Add distribution report JSON.

Acceptance: generated corpus imports in local Postgres and quality report shows target distributions.

### Phase 3 - Slack Seeding And Permalinks

- Add generated corpus files to Slack seed plan.
- Update live sync to resolve file-share message permalinks with `chat_getPermalink`.
- Make citation URL resolver prefer Slack post/message permalink.
- Remove `demo.local` from generated source URLs.

Acceptance: after `seed-slack-files` and `sync-live-demo-sources`, Show Sources opens Slack conversation links for cited rows.

### Phase 4 - Query And Toolhouse Coverage

- Add filters and aliases for new fields.
- Update answer rendering for richer rows and map links.
- Update Toolhouse prompt/schema/tools to expose the new safe field vocabulary.

Acceptance: golden queries cover neighborhood, status, furnished/furnishing, facing, logistics infrastructure, and map/coordinate lookup.

### Phase 5 - Performance And Demo Readiness

- Validate import time, answer latency, source view readability, and Slack rate-limit behavior.
- Update README diagrams and runbook once implementation lands.
- Keep a `--small` corpus mode for quick tests if full corpus slows local feedback.

Acceptance: full suite passes, demo doctor passes, and generated Slack citations are clickable.

## Open Decisions

1. Whether to use only permissive sources by default. Recommendation: yes. Use OpenAddresses, GeoNames, and Microsoft Global ML Building Footprints by default; make UK EPC optional because it requires sign-in and licence review.
2. Whether to store map URLs or compute them at render time. Recommendation: store `map_url` for source transparency, but also expose a helper that can recompute it from coordinates.
3. Whether to add PostGIS. Recommendation: not for 2-3k rows. Current numeric coordinates and distance functions are enough; revisit when polygon/geofence queries become important.
4. Whether generated commercial fields should be cited as synthetic. Recommendation: yes. Keep the demo honest by tagging synthetic profile fields clearly while still making the Slack source row the citation.
5. Whether source URL should be file permalink or message permalink. Recommendation: message permalink for citations, file permalink in metadata. The user experience should open the Slack conversation where the evidence was shared.

## Completed First Slice

The first slice landed at full 2,400-row scale rather than a temporary 100-row shard:

1. Migration and ORM/importer fields now cover geography, status, usage, facing, furnishing, infrastructure, map URL, and `additional_information`.
2. The generated corpus builder emits four 600-row shards plus a generated manifest and quality report.
3. Slack live demo sync and live Slack file ingestion prefer message permalinks for shared-file citations.
4. Show Sources omits non-opening `demo.local` URLs and formats real Slack links as `Open source in Slack`.
5. README, data dictionary, sample-data docs, Slack runbook, Toolhouse docs, and tests are updated.

Remaining optional follow-ups:

1. Add real downloader/cache adapters for OpenAddresses, GeoNames, or Microsoft Global ML Building Footprints when the demo needs externally refreshed seed data.
2. Add PostGIS only if polygon/geofence queries or larger-than-demo geospatial performance become requirements.
3. Add a CLI flag for importing only the compact hand-authored corpus if operators want a tiny local smoke-test dataset outside pytest.
