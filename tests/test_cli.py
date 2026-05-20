from pathlib import Path
from types import SimpleNamespace

import pytest

import app.cli as cli_module
from app.cli import build_parser, build_status_payload
from app.ingestion.sample_importer import load_sample_manifest
from app.slack.demo_files import build_default_file_seed_plan
from app.slack.demo_seed import (
    build_default_persona_profiles,
    build_default_persona_seed_plan,
    candidate_message_texts,
)


def test_status_payload_contains_scaffold_surface() -> None:
    payload = build_status_payload()

    assert payload["app_name"] == "CRE Knowledge Engine"
    assert payload["sample_data_dir_exists"] is True
    assert payload["sample_manifest_present"] is True
    assert payload["sample_source_count"] >= 10
    assert "database_url" in payload
    assert "slack_ingest_channel_policies" in payload
    assert "slack_context_retention_days" in payload
    assert "slack_download_retention_days" in payload
    assert "slack_storage_prune_interval_seconds" in payload


def test_sample_manifest_loads_seeded_sources() -> None:
    manifest = load_sample_manifest(Path("sample-data"))

    assert manifest.channel_name == "cre-listings-demo"
    assert len(manifest.sources) == 27
    assert any(source.source_id == "F1" for source in manifest.sources)
    assert sum(len(source.properties) for source in manifest.sources if source.source_id.startswith("LC")) == 2400


def test_cli_parser_includes_slack_persona_seed_command() -> None:
    parser = build_parser()

    args = parser.parse_args(["seed-slack-personas", "--dry-run", "--replace-legacy-prefix"])

    assert args.command == "seed-slack-personas"
    assert args.dry_run is True
    assert args.replace_legacy_prefix is True
    assert args.recent_limit == 100


def test_cli_parser_includes_slack_file_seed_command() -> None:
    parser = build_parser()

    args = parser.parse_args(["seed-slack-files", "--dry-run"])

    assert args.command == "seed-slack-files"
    assert args.dry_run is True
    assert args.recent_limit == 100


def test_cli_parser_includes_slack_demo_sync_command() -> None:
    parser = build_parser()

    args = parser.parse_args(["sync-slack-demo-sources", "--recent-limit", "25"])

    assert args.command == "sync-slack-demo-sources"
    assert args.recent_limit == 25


def test_cli_parser_includes_data_audit_command() -> None:
    parser = build_parser()

    args = parser.parse_args(["audit-data"])

    assert args.command == "audit-data"


def test_cli_parser_includes_large_corpus_builder_command() -> None:
    parser = build_parser()

    args = parser.parse_args(["build-large-corpus", "--rows", "2400", "--seed", "20260519"])

    assert args.command == "build-large-corpus"
    assert args.rows == 2400
    assert args.seed == 20260519


def test_cli_parser_includes_eval_golden_command() -> None:
    parser = build_parser()

    args = parser.parse_args(["eval-golden", "--case", "office_threshold", "--case", "harbor_conflict"])

    assert args.command == "eval-golden"
    assert args.cases == ["office_threshold", "harbor_conflict"]


def test_cli_parser_includes_replay_query_command() -> None:
    parser = build_parser()

    args = parser.parse_args(["replay-query", "00000000-0000-0000-0000-000000000000"])

    assert args.command == "replay-query"
    assert args.query_id == "00000000-0000-0000-0000-000000000000"


def test_cli_parser_includes_demo_doctor_command() -> None:
    parser = build_parser()

    args = parser.parse_args(["demo-doctor", "--skip-public-callback", "--live-toolhouse"])

    assert args.command == "demo-doctor"
    assert args.skip_public_callback is True
    assert args.live_toolhouse is True


def test_cli_parser_includes_demo_dry_run_command() -> None:
    parser = build_parser()

    args = parser.parse_args(["demo-dry-run", "--skip-public-callback", "--live-toolhouse"])

    assert args.command == "demo-dry-run"
    assert args.skip_public_callback is True
    assert args.live_toolhouse is True


def test_cli_parser_includes_secret_scan_command() -> None:
    parser = build_parser()

    args = parser.parse_args(["secret-scan", "--root", "app"])

    assert args.command == "secret-scan"
    assert args.root == "app"


def test_cli_parser_includes_submission_report_command() -> None:
    parser = build_parser()

    args = parser.parse_args([
        "submission-report",
        "--skip-public-callback",
        "--live-toolhouse",
        "--format",
        "markdown",
        "--output",
        ".runtime/submission-report.md",
    ])

    assert args.command == "submission-report"
    assert args.skip_public_callback is True
    assert args.live_toolhouse is True
    assert args.format == "markdown"
    assert args.output == ".runtime/submission-report.md"


@pytest.mark.parametrize(
    ("status", "expected_exit_code"),
    [
        ("answered", 0),
        ("needs_more_evidence", 0),
        ("external_context_only", 0),
        ("validation_risk", 0),
        ("mcp_unavailable", 1),
        ("tool_error", 1),
    ],
)
def test_cmd_toolhouse_smoke_treats_safe_hosted_statuses_as_success(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    expected_exit_code: int,
) -> None:
    async def fake_toolhouse_smoke(_query_text: str) -> dict[str, object]:
        return {
            "status": status,
            "toolhouse_fallback": False,
            "dependency_state": {"toolhouse": True, "local_deeper_review": False, "llm": True},
            "validation": {"valid": True},
            "cited_evidence_ids": [],
            "rendered_answer": "Synthetic smoke result.",
        }

    monkeypatch.setattr(
        cli_module,
        "get_settings",
        lambda: SimpleNamespace(
            toolhouse_api_key="toolhouse-key",
            toolhouse_agent_id="toolhouse-agent",
            toolhouse_mcp_bearer_token="toolhouse-mcp-token",
        ),
    )
    monkeypatch.setattr(cli_module, "_run_toolhouse_smoke", fake_toolhouse_smoke)

    assert cli_module.cmd_toolhouse_smoke("synthetic query") == expected_exit_code


def test_cmd_toolhouse_smoke_still_fails_for_local_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_toolhouse_smoke(_query_text: str) -> dict[str, object]:
        return {
            "status": "answered",
            "toolhouse_fallback": True,
            "dependency_state": {
                "toolhouse": False,
                "local_deeper_review": True,
                "llm": False,
                "toolhouse_error": "parse_error: empty_response",
            },
            "validation": {"valid": True},
            "cited_evidence_ids": ["evidence-1"],
            "rendered_answer": "Fallback answer.",
        }

    monkeypatch.setattr(
        cli_module,
        "get_settings",
        lambda: SimpleNamespace(
            toolhouse_api_key="toolhouse-key",
            toolhouse_agent_id="toolhouse-agent",
            toolhouse_mcp_bearer_token="toolhouse-mcp-token",
        ),
    )
    monkeypatch.setattr(cli_module, "_run_toolhouse_smoke", fake_toolhouse_smoke)

    assert cli_module.cmd_toolhouse_smoke("synthetic query") == 1


def test_cli_parser_includes_resettable_chunk_index_command() -> None:
    parser = build_parser()

    args = parser.parse_args(["index-chunks", "--reset"])

    assert args.command == "index-chunks"
    assert args.reset is True


def test_cli_parser_includes_ocr_smoke_command() -> None:
    parser = build_parser()

    args = parser.parse_args(["ocr-smoke", "sample-data/files/main-street-office-flyer.pdf", "--source-type", "pdf"])

    assert args.command == "ocr-smoke"
    assert args.path == "sample-data/files/main-street-office-flyer.pdf"
    assert args.source_type == "pdf"


def test_cli_parser_includes_all_channel_slack_history_sync_command() -> None:
    parser = build_parser()

    args = parser.parse_args(["sync-slack-history", "--recent-limit", "250", "--reindex"])

    assert args.command == "sync-slack-history"
    assert args.recent_limit == 250
    assert args.reindex is True


def test_cli_parser_includes_slack_storage_prune_command() -> None:
    parser = build_parser()

    args = parser.parse_args([
        "prune-slack-storage",
        "--context-retention-days",
        "45",
        "--download-retention-days",
        "10",
        "--reindex",
    ])

    assert args.command == "prune-slack-storage"
    assert args.context_retention_days == 45
    assert args.download_retention_days == 10
    assert args.reindex is True


def test_persona_seed_plan_contains_threaded_harbor_reply() -> None:
    plan = build_default_persona_seed_plan()
    seed_keys = {seed.seed_key for seed in plan}
    harbor_reply = next(seed for seed in plan if seed.seed_key == "listings_harbor_reply")

    assert len(plan) == 15
    assert "listings_harbor_correction" in seed_keys
    assert "listings_beacon_watchlist" in seed_keys
    assert "market_expansion_brief" in seed_keys
    assert harbor_reply.reply_to_seed_key == "listings_harbor_correction"


def test_candidate_message_texts_match_legacy_prefixed_seed() -> None:
    plan = build_default_persona_seed_plan()
    profiles = build_default_persona_profiles()
    harbor_correction = next(seed for seed in plan if seed.seed_key == "listings_harbor_correction")
    candidates = candidate_message_texts(
        harbor_correction,
        profile=profiles["priya"],
    )

    assert harbor_correction.text in candidates
    assert (
        "Priya: Harbor Rd got updated yesterday. 240 Harbor is now 62k SF, not 58k. Use the industrial inventory as source of truth."
        in candidates
    )


def test_file_seed_plan_matches_runbook_mapping() -> None:
    plan = build_default_file_seed_plan()

    assert len(plan) == 22
    assert sum(1 for seed in plan if seed.channel_name == "cre-listings") == 13
    assert sum(1 for seed in plan if seed.channel_name == "cre-market-research") == 6
    assert sum(1 for seed in plan if seed.channel_name == "cre-private-demo") == 3
    assert any(seed.file_name == "main-street-office-flyer.pdf" for seed in plan)
    assert any(seed.file_name == "last-mile-industrial-watchlist.csv" for seed in plan)
    assert any(seed.file_name == "global-cre-corpus-us-1.csv" for seed in plan)
    assert any(seed.file_name == "broker-availability-tracker.xlsx" and seed.channel_name == "cre-private-demo" for seed in plan)
