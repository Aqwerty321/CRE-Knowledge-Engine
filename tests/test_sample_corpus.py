import json

import app.routing.query_constructor as query_constructor

from pathlib import Path

from app.ingestion.sample_importer import load_sample_manifest
from app.routing.query_constructor import build_structured_query_spec
from app.slack.demo_files import build_default_file_seed_plan
from app.slack.demo_seed import build_default_persona_seed_plan


def test_expanded_sample_manifest_has_demo_depth() -> None:
    manifest = load_sample_manifest(Path("sample-data"))

    source_ids = {source.source_id for source in manifest.sources}
    file_names = {source.file_name for source in manifest.sources if source.file_name}
    slack_texts = [source.raw_text or "" for source in manifest.sources if source.source_type == "slack_message"]

    assert len(manifest.sources) >= 23
    assert {"F11", "F12", "F13", "F14", "F15", "M5", "M6", "M7", "M8"}.issubset(source_ids)
    assert "last-mile-industrial-watchlist.csv" in file_names
    assert "client-tour-notes.txt" in file_names
    assert any("18 Beacon Freight" in text for text in slack_texts)
    assert any("truck court" in text for text in slack_texts)


def test_large_generated_corpus_is_loaded_with_rich_fields() -> None:
    manifest = load_sample_manifest(Path("sample-data"))

    generated_sources = [source for source in manifest.sources if source.source_id.startswith("LC")]
    generated_properties = [property_model for source in generated_sources for property_model in source.properties]
    sample_property = generated_properties[0]

    assert len(generated_sources) == 4
    assert len(generated_properties) == 2400
    assert all(source.source_url is None for source in generated_sources)
    assert {source.file_name for source in generated_sources} == {
        "global-cre-corpus-us-1.csv",
        "global-cre-corpus-us-2.csv",
        "global-cre-corpus-europe-1.csv",
        "global-cre-corpus-europe-2.csv",
    }
    assert sample_property.locality
    assert sample_property.neighborhood
    assert sample_property.furnishing_status
    assert sample_property.status
    assert sample_property.additional_information
    assert sample_property.geo_lat is not None
    assert sample_property.geo_lng is not None
    assert sample_property.map_url and "maps/search" in sample_property.map_url
    assert sum(1 for property_model in generated_properties if property_model.cap_rate is not None) > 0


def test_large_generated_corpus_contains_coastal_facing_rows() -> None:
    manifest = load_sample_manifest(Path("sample-data"))

    generated_sources = [source for source in manifest.sources if source.source_id.startswith("LC")]
    generated_properties = [property_model for source in generated_sources for property_model in source.properties]
    coastal_properties = [
        property_model
        for property_model in generated_properties
        if property_model.facing in {"waterfront", "sea_facing", "harbor_view", "bay_front"}
    ]

    assert coastal_properties
    assert any(property_model.facing == "waterfront" for property_model in coastal_properties)
    assert any(
        "coastal demo profile" in str(property_model.additional_information or "").lower()
        for property_model in coastal_properties
    )


def test_sample_property_aliases_preserve_comments_and_unknown_columns() -> None:
    property_model = load_sample_manifest(Path("sample-data")).sources[0].properties[0].model_copy(
        update={
            "neighborhood": None,
            "furnishing_status": None,
        }
    )
    aliased = property_model.__class__.model_validate(
        {
            "address": "1 Alias Rd",
            "property_type": "office",
            "neighbourhood": "Alias Quarter",
            "funishing": "turnkey",
            "comments": "Broker says show only after NDA.",
            "custom_signal": "retain me",
        }
    )

    assert aliased.neighborhood == "Alias Quarter"
    assert aliased.furnishing_status == "turnkey"
    assert aliased.additional_information == "Broker says show only after NDA."
    assert aliased.model_extra == {"custom_signal": "retain me"}


def test_structured_query_constructor_detects_rich_field_filters() -> None:
    spec = build_structured_query_spec("Show furnished retail in Shoreditch with EV charging and west facing frontage")

    assert spec is not None
    filters = spec.to_filters()
    assert "retail" in filters["property_types"]
    assert "shoreditch" in filters["locations"]
    assert "furnished" in filters["furnishing_statuses"]
    assert "west" in filters["facing"]
    assert "ev charging" in filters["infrastructure_terms"]


def test_structured_query_constructor_detects_sea_facing_filters() -> None:
    spec = build_structured_query_spec("What are some of the sea facing properties")

    assert spec is not None
    filters = spec.to_filters()
    assert spec.intent == "property_search"
    assert "sea_facing" in filters["facing"]
    assert "waterfront" in filters["facing"]


def test_structured_query_constructor_detects_facing_summary_aggregation() -> None:
    spec = build_structured_query_spec("what are the kinds of facing that we have available")

    assert spec is not None
    filters = spec.to_filters()
    assert spec.intent == "aggregation"
    assert filters["aggregate"] == "facet_counts"
    assert filters["aggregate_field"] == "facing"
    assert filters["statuses"] == ["available"]


def test_structured_query_constructor_detects_expanded_dataset_locations() -> None:
    spec = build_structured_query_spec("Show industrial listings in Atlanta with map links")

    assert spec is not None
    filters = spec.to_filters()
    assert "atlanta" in filters["locations"]
    assert filters["requires_coordinates"] is True
    assert "map" not in filters["keywords"]
    assert "coordinates" not in filters["keywords"]


def test_structured_query_constructor_expands_macro_regions() -> None:
    spec = build_structured_query_spec("Show industrial listings in Europe with map links")

    assert spec is not None
    filters = spec.to_filters()
    assert "france" in filters["locations"]
    assert "germany" in filters["locations"]
    assert "united kingdom" in filters["locations"]


def test_structured_query_constructor_uses_corpus_seed_location_lexicon() -> None:
    toronto = build_structured_query_spec("Show office listings in Toronto with map links")
    barcelona = build_structured_query_spec("Show industrial listings in Barcelona with map links")

    assert toronto is not None
    assert barcelona is not None
    assert "toronto" in toronto.to_filters()["locations"]
    assert "barcelona" in barcelona.to_filters()["locations"]


def test_structured_query_constructor_uses_live_qdrant_location_lexicon(monkeypatch) -> None:
    monkeypatch.setattr(query_constructor, "_load_live_qdrant_location_values", lambda: {"lisbon", "portugal", "alfama"})

    spec = build_structured_query_spec("Show office listings in Lisbon with map links")

    assert spec is not None
    filters = spec.to_filters()
    assert "lisbon" in filters["locations"]
    assert filters["requires_coordinates"] is True


def test_live_qdrant_location_cache_can_be_invalidated(monkeypatch) -> None:
    query_constructor.invalidate_live_location_value_cache()

    monkeypatch.setattr(query_constructor, "_fetch_live_qdrant_location_values", lambda: {"lisbon"})
    first = query_constructor._load_live_qdrant_location_values()

    monkeypatch.setattr(query_constructor, "_fetch_live_qdrant_location_values", lambda: {"porto"})
    cached = query_constructor._load_live_qdrant_location_values()
    query_constructor.invalidate_live_location_value_cache()
    refreshed = query_constructor._load_live_qdrant_location_values()

    assert first == {"lisbon"}
    assert cached == {"lisbon"}
    assert refreshed == {"porto"}


def test_structured_query_constructor_uses_property_record_location_snapshot(monkeypatch, tmp_path: Path) -> None:
    snapshot_path = tmp_path / "property-record-location-lexicon.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "field_values": {
                    "markets": [],
                    "countries": ["Portugal"],
                    "country_codes": [],
                    "regions": [],
                    "state_provinces": [],
                    "cities": ["Lisbon"],
                    "localities": ["Alfama"],
                    "neighborhoods": [],
                    "submarkets": [],
                }
            }
        ),
        encoding="utf-8",
    )
    query_constructor.invalidate_live_location_value_cache()
    monkeypatch.setattr(query_constructor, "_property_record_location_snapshot_path", lambda: snapshot_path)
    monkeypatch.setattr(query_constructor, "_load_live_qdrant_location_values", lambda: set())

    spec = build_structured_query_spec("Show office listings in Lisbon with map links")

    assert spec is not None
    filters = spec.to_filters()
    assert "lisbon" in filters["locations"]
    assert filters["requires_coordinates"] is True


def test_structured_query_constructor_detects_geo_physical_and_financial_filters() -> None:
    spec = build_structured_query_spec(
        "Show industrial for sale under $5m with cap rate over 5%, at least 4 dock doors, "
        "40 trailer parking spaces, 100 parking spaces, clear height 28 ft, and map links"
    )

    assert spec is not None
    filters = spec.to_filters()
    assert "industrial" in filters["property_types"]
    assert filters["sale_price_lt"] == "5000000"
    assert filters["cap_rate_gte"] == "0.05"
    assert filters["dock_doors_gte"] == 4
    assert filters["trailer_parking_spaces_gte"] == 40
    assert filters["parking_spaces_gte"] == 100
    assert filters["clear_height_ft_gte"] == "28"
    assert filters["requires_coordinates"] is True
    assert "loading dock" not in filters["infrastructure_terms"]
    assert "loading dock" not in filters["keywords"]
    assert "trailer" not in filters["infrastructure_terms"]
    assert "trailer" not in filters["keywords"]


def test_structured_query_constructor_keeps_trailer_parking_as_infrastructure_not_property_type() -> None:
    spec = build_structured_query_spec(
        "I need an industrial option under $35/SF for last-mile delivery with dock doors and trailer parking."
    )

    assert spec is not None
    filters = spec.to_filters()
    assert "industrial" in filters["property_types"]
    assert "parking" not in filters["property_types"]
    assert "logistics" in filters["usage_types"]
    assert "loading dock" in filters["infrastructure_terms"]
    assert "trailer" in filters["infrastructure_terms"]
    assert filters["price_per_sq_ft_lt"] == "35"


def test_structured_query_constructor_treats_hudson_yard_as_lookup_subject_location() -> None:
    spec = build_structured_query_spec("what do u know about hudson yard")

    assert spec is not None
    filters = spec.to_filters()
    assert spec.intent == "property_search"
    assert filters["lookup_subject"] == "hudson yard"
    assert "hudson yard" in filters["lookup_terms"]
    assert "hudson yards" in filters["locations"]
    assert filters["property_types"] == []
    assert filters["infrastructure_terms"] == []
    assert filters["keywords"] == []


def test_structured_query_constructor_carries_aurora_campus_lookup_terms() -> None:
    spec = build_structured_query_spec("tell me about aurora campus")

    assert spec is not None
    filters = spec.to_filters()
    assert spec.intent == "property_search"
    assert filters["lookup_subject"] == "aurora campus"
    assert "aurora campus" in filters["lookup_terms"]
    assert "aurora" in filters["locations"]


def test_slack_seed_plan_surfaces_expanded_demo_material() -> None:
    file_plan = build_default_file_seed_plan()
    persona_plan = build_default_persona_seed_plan()

    seeded_files = {seed.file_name for seed in file_plan}
    seeded_messages = {seed.seed_key: seed.text for seed in persona_plan}

    assert "last-mile-industrial-watchlist.csv" in seeded_files
    assert "client-tour-notes.txt" in seeded_files
    assert "tenant-expansion-brief.txt" in seeded_files
    assert "retail-office-followups.csv" in seeded_files
    assert "access-constraints-notes.txt" in seeded_files
    assert "global-cre-corpus-us-1.csv" in seeded_files
    assert "global-cre-corpus-us-2.csv" in seeded_files
    assert "global-cre-corpus-europe-1.csv" in seeded_files
    assert "global-cre-corpus-europe-2.csv" in seeded_files
    assert "listings_beacon_watchlist" in seeded_messages
    assert "market_expansion_brief" in seeded_messages
