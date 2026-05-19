from pathlib import Path

from app.ingestion.sample_importer import load_sample_manifest
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
    assert "listings_beacon_watchlist" in seeded_messages
    assert "market_expansion_brief" in seeded_messages
