from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Sequence

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import make_url

from app.answering.query_service import answer_query, explain_query
from app.config import get_settings
from app.evaluation import (
    build_submission_report,
    demo_doctor,
    demo_dry_run,
    render_submission_report_markdown,
    replay_query,
    run_golden_evals,
    scan_workspace_for_secrets,
)
from app.extraction.parsers import parse_source_file
from app.indexing import check_vector_dependencies, index_all_chunks
from app.ingestion.large_corpus_builder import DEFAULT_ROW_COUNT, DEFAULT_SEED, build_large_corpus
from app.ingestion.quality import collect_ingestion_quality_report
from app.ingestion.sample_importer import collect_database_counts, import_sample_data, load_sample_manifest
from app.ingestion.slack_ingestor import backfill_slack_channel_history, prune_slack_storage
from app.slack.demo_files import SlackFileSeeder
from app.slack.demo_seed import SlackPersonaSeeder
from app.slack.demo_sync import sync_live_demo_sources
from app.toolhouse import is_acceptable_live_toolhouse_outcome, run_toolhouse_deeper_review


def sanitize_database_url(database_url: str) -> str:
    url = make_url(database_url)
    username = url.username or "user"
    host = url.host or "localhost"
    port = url.port or 5432
    database = url.database or ""
    return f"{url.drivername}://{username}:***@{host}:{port}/{database}"


def iter_sample_files(sample_data_dir: Path) -> list[Path]:
    if not sample_data_dir.exists():
        return []

    return sorted(
        path
        for path in sample_data_dir.rglob("*")
        if path.is_file() and path.name != "README.md" and not any(part.startswith(".") for part in path.parts)
    )


def build_status_payload() -> dict[str, object]:
    settings = get_settings()
    sample_files = iter_sample_files(settings.sample_data_dir)
    manifest_path = settings.sample_data_dir / "import-manifest.json"

    try:
        manifest = load_sample_manifest(settings.sample_data_dir)
        sample_source_count = len(manifest.sources)
        sample_manifest_present = True
    except FileNotFoundError:
        sample_source_count = 0
        sample_manifest_present = False

    return {
        "app_name": settings.app_name,
        "app_env": settings.app_env,
        "database_url": sanitize_database_url(settings.database_url),
        "qdrant_url": settings.qdrant_url,
        "qdrant_collection": settings.qdrant_collection,
        "vector_search_enabled": settings.vector_search_enabled,
        "vector_index_on_import": settings.vector_index_on_import,
        "embedding_url": settings.embedding_url,
        "embedding_model": settings.embedding_model,
        "rerank_url": settings.rerank_url,
        "rerank_model": settings.rerank_model,
        "ocr_enabled": settings.ocr_enabled,
        "ocr_backend_url": settings.ocr_backend_url,
        "configured_channels": settings.configured_channels,
        "slack_ingest_channels": settings.slack_ingest_channels,
        "slack_ingest_channel_policies": settings.slack_ingest_channel_policies,
        "slack_context_retention_days": settings.slack_context_retention_days,
        "slack_download_retention_days": settings.slack_download_retention_days,
        "slack_storage_prune_interval_seconds": settings.slack_storage_prune_interval_seconds,
        "sample_data_dir": str(settings.sample_data_dir),
        "sample_data_dir_exists": settings.sample_data_dir.exists(),
        "sample_manifest_path": str(manifest_path),
        "sample_manifest_present": sample_manifest_present,
        "sample_file_count": len(sample_files),
        "sample_source_count": sample_source_count,
    }


def cmd_import_samples() -> int:
    settings = get_settings()
    settings.sample_data_dir.mkdir(parents=True, exist_ok=True)
    payload = asyncio.run(import_sample_data(settings.sample_data_dir))
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") == "imported" else 1


def cmd_build_large_corpus(*, rows: int, seed: int) -> int:
    settings = get_settings()
    payload = build_large_corpus(settings.sample_data_dir, row_count=rows, seed=seed)
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") == "generated" else 1


def cmd_status() -> int:
    payload = build_status_payload()

    try:
        payload["database_reachable"] = True
        payload["database_counts"] = asyncio.run(collect_database_counts())
        payload["dependency_checks"] = asyncio.run(check_vector_dependencies())
    except (OSError, SQLAlchemyError):
        payload["database_reachable"] = False
        payload["database_counts"] = {}

    print(json.dumps(payload, indent=2))
    return 0


def cmd_ask(query_text: str) -> int:
    payload = asyncio.run(answer_query(query_text))
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") in {"answered", "no_results"} else 1


def cmd_explain_query(query_id: str) -> int:
    payload = asyncio.run(explain_query(query_id))
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") == "explained" else 1


def cmd_replay_query(query_id: str) -> int:
    payload = asyncio.run(replay_query(query_id))
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") == "replayed" else 1


def cmd_eval_golden(case_names: list[str] | None = None) -> int:
    payload = asyncio.run(run_golden_evals(case_names=case_names))
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") == "passed" else 1


def cmd_demo_doctor(*, skip_public_callback: bool, live_toolhouse: bool) -> int:
    payload = asyncio.run(
        demo_doctor(
            include_public_callback=not skip_public_callback,
            include_toolhouse_smoke=live_toolhouse,
        )
    )
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") == "ready" else 1


def cmd_demo_dry_run(*, skip_public_callback: bool, live_toolhouse: bool) -> int:
    payload = asyncio.run(
        demo_dry_run(
            include_public_callback=not skip_public_callback,
            live_toolhouse=live_toolhouse,
        )
    )
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") == "passed" else 1


def cmd_secret_scan(root: str) -> int:
    payload = scan_workspace_for_secrets(Path(root))
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") == "passed" else 1


def cmd_submission_report(
    *,
    skip_public_callback: bool,
    live_toolhouse: bool,
    output_format: str,
    output_path: str | None,
) -> int:
    payload = asyncio.run(
        build_submission_report(
            include_public_callback=not skip_public_callback,
            include_toolhouse_smoke=live_toolhouse,
        )
    )
    if output_format == "markdown":
        rendered = render_submission_report_markdown(payload)
    else:
        rendered = json.dumps(payload, indent=2)
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0 if payload.get("status") == "ready" else 1


async def _run_toolhouse_smoke(query_text: str) -> dict[str, object]:
    answer_payload = await answer_query(query_text)
    deeper_payload = await run_toolhouse_deeper_review(str(answer_payload["query_id"]))
    return {
        "status": deeper_payload.get("status"),
        "query_id": deeper_payload.get("query_id"),
        "agent_run_id": deeper_payload.get("agent_run_id"),
        "instant_answer_status": answer_payload.get("status"),
        "toolhouse_agent_id": deeper_payload.get("toolhouse_agent_id"),
        "toolhouse_run_id": deeper_payload.get("toolhouse_run_id"),
        "toolhouse_fallback": deeper_payload.get("toolhouse_fallback", False),
        "dependency_state": deeper_payload.get("dependency_state"),
        "validation": deeper_payload.get("validation"),
        "toolhouse_validation": deeper_payload.get("toolhouse_validation"),
        "cited_evidence_ids": deeper_payload.get("cited_evidence_ids", []),
        "rendered_answer": deeper_payload.get("rendered_answer"),
    }


def cmd_toolhouse_smoke(query_text: str) -> int:
    settings = get_settings()
    missing_config = [
        name
        for name, value in {
            "CRE_TOOLHOUSE_API_KEY": settings.toolhouse_api_key,
            "CRE_TOOLHOUSE_AGENT_ID": settings.toolhouse_agent_id,
            "CRE_TOOLHOUSE_MCP_BEARER_TOKEN": settings.toolhouse_mcp_bearer_token,
        }.items()
        if not value
    ]
    if missing_config:
        print(json.dumps({"status": "missing_config", "missing_config": missing_config}, indent=2))
        return 1

    payload = asyncio.run(_run_toolhouse_smoke(query_text))
    print(json.dumps(payload, indent=2))

    return 0 if is_acceptable_live_toolhouse_outcome(payload) else 1


def cmd_audit_data() -> int:
    payload = asyncio.run(collect_ingestion_quality_report())
    print(json.dumps(payload, indent=2))
    readiness = dict(payload.get("toolhouse_readiness") or {})
    return 0 if readiness.get("status") in {"ready_for_bounded_agent", "needs_ingestion_attention"} else 1


def cmd_index_chunks(*, reset: bool) -> int:
    payload = asyncio.run(index_all_chunks(reset_collection=reset))
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") in {"indexed", "empty", "disabled"} else 1


def cmd_ocr_smoke(path: str, *, source_type: str | None, mime_type: str | None) -> int:
    file_path = Path(path)
    if not file_path.exists():
        print(json.dumps({"status": "error", "error": "file_not_found", "path": str(file_path)}, indent=2))
        return 1

    parsed = parse_source_file(file_path, source_type=source_type, mime_type=mime_type)
    non_empty_chunks = [chunk for chunk in parsed.chunks if chunk.text.strip()]
    parser_names = sorted({str(chunk.metadata.get("parser") or "unknown") for chunk in parsed.chunks})
    payload = {
        "status": "parsed" if non_empty_chunks else "empty",
        "path": str(file_path),
        "parser_names": parser_names,
        "raw_text_length": len(parsed.raw_text.strip()),
        "chunk_count": len(parsed.chunks),
        "non_empty_chunk_count": len(non_empty_chunks),
        "preview": parsed.raw_text.strip()[:500],
    }
    print(json.dumps(payload, indent=2))
    return 0 if non_empty_chunks else 1


def cmd_seed_slack_personas(*, dry_run: bool, replace_legacy_prefix: bool, recent_limit: int) -> int:
    settings = get_settings()
    if not settings.slack_bot_token:
        print(json.dumps({"status": "error", "error": "missing_slack_bot_token"}, indent=2))
        return 1

    try:
        seeder = SlackPersonaSeeder(WebClient(token=settings.slack_bot_token))
        payload = seeder.seed_workspace(
            dry_run=dry_run,
            replace_legacy_prefix=replace_legacy_prefix,
            recent_limit=recent_limit,
        )
    except SlackApiError as exc:
        payload = {
            "status": "error",
            "error": "slack_api_error",
            "detail": str(exc.response.get("error") or exc),
        }
        print(json.dumps(payload, indent=2))
        return 1
    except ValueError as exc:
        payload = {
            "status": "error",
            "error": "invalid_seed_configuration",
            "detail": str(exc),
        }
        print(json.dumps(payload, indent=2))
        return 1

    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") in {"planned", "seeded"} else 1


def cmd_seed_slack_files(*, dry_run: bool, recent_limit: int, force_upload: bool, file_names: list[str] | None) -> int:
    settings = get_settings()
    if not settings.slack_bot_token:
        print(json.dumps({"status": "error", "error": "missing_slack_bot_token"}, indent=2))
        return 1

    try:
        seeder = SlackFileSeeder(WebClient(token=settings.slack_bot_token))
        payload = seeder.seed_workspace(
            sample_files_dir=settings.sample_data_dir / "files",
            dry_run=dry_run,
            recent_limit=recent_limit,
            force_upload_matching=force_upload,
            file_names=set(file_names) if file_names else None,
        )
    except SlackApiError as exc:
        payload = {
            "status": "error",
            "error": "slack_api_error",
            "detail": str(exc.response.get("error") or exc),
        }
        print(json.dumps(payload, indent=2))
        return 1
    except (FileNotFoundError, ValueError) as exc:
        payload = {
            "status": "error",
            "error": "invalid_seed_configuration",
            "detail": str(exc),
        }
        print(json.dumps(payload, indent=2))
        return 1

    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") in {"planned", "seeded"} else 1


def cmd_sync_slack_demo_sources(*, recent_limit: int) -> int:
    settings = get_settings()
    if not settings.slack_bot_token:
        print(json.dumps({"status": "error", "error": "missing_slack_bot_token"}, indent=2))
        return 1

    try:
        payload = asyncio.run(
            sync_live_demo_sources(
                WebClient(token=settings.slack_bot_token),
                settings.sample_data_dir,
                recent_limit=recent_limit,
            )
        )
    except SlackApiError as exc:
        payload = {
            "status": "error",
            "error": "slack_api_error",
            "detail": str(exc.response.get("error") or exc),
        }
        print(json.dumps(payload, indent=2))
        return 1
    except ValueError as exc:
        payload = {
            "status": "error",
            "error": "invalid_sync_configuration",
            "detail": str(exc),
        }
        print(json.dumps(payload, indent=2))
        return 1

    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") == "synced" else 1


def cmd_sync_slack_channel_history(*, channel_id: str, channel_name: str | None, recent_limit: int) -> int:
    settings = get_settings()
    if not settings.slack_bot_token:
        print(json.dumps({"status": "error", "error": "missing_slack_bot_token"}, indent=2))
        return 1

    try:
        payload = asyncio.run(
            backfill_slack_channel_history(
                AsyncWebClient(token=settings.slack_bot_token),
                channel_id=channel_id,
                channel_name=channel_name,
                recent_limit=recent_limit,
            )
        )
    except SlackApiError as exc:
        payload = {
            "status": "error",
            "error": "slack_api_error",
            "detail": str(exc.response.get("error") or exc),
        }
        print(json.dumps(payload, indent=2))
        return 1
    except ValueError as exc:
        payload = {
            "status": "error",
            "error": "invalid_sync_configuration",
            "detail": str(exc),
        }
        print(json.dumps(payload, indent=2))
        return 1

    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") == "synced" else 1


async def _sync_all_slack_history(*, recent_limit: int, reindex: bool) -> dict[str, object]:
    settings = get_settings()
    client = AsyncWebClient(token=settings.slack_bot_token)
    results = []
    for channel_id in settings.slack_ingest_channels:
        results.append(
            await backfill_slack_channel_history(
                client,
                channel_id=channel_id,
                recent_limit=recent_limit,
            )
        )

    payload: dict[str, object] = {
        "status": "synced",
        "channel_count": len(results),
        "seen_message_count": sum(int(result.get("seen_message_count") or 0) for result in results),
        "seen_thread_reply_count": sum(int(result.get("seen_thread_reply_count") or 0) for result in results),
        "ingested_message_source_count": sum(int(result.get("ingested_message_source_count") or 0) for result in results),
        "ingested_file_source_count": sum(int(result.get("ingested_file_source_count") or 0) for result in results),
        "channels": [
            {
                "channel_id": result.get("channel_id"),
                "channel_name": result.get("channel_name"),
                "seen_message_count": result.get("seen_message_count"),
                "seen_thread_reply_count": result.get("seen_thread_reply_count"),
                "ingested_message_source_count": result.get("ingested_message_source_count"),
                "ingested_file_source_count": result.get("ingested_file_source_count"),
            }
            for result in results
        ],
    }
    if reindex:
        payload["indexing"] = await index_all_chunks(reset_collection=True)
    return payload


def cmd_sync_slack_history(*, recent_limit: int, reindex: bool) -> int:
    settings = get_settings()
    if not settings.slack_bot_token:
        print(json.dumps({"status": "error", "error": "missing_slack_bot_token"}, indent=2))
        return 1
    if not settings.slack_ingest_channels:
        print(json.dumps({"status": "error", "error": "missing_slack_ingest_channels"}, indent=2))
        return 1

    payload = asyncio.run(_sync_all_slack_history(recent_limit=recent_limit, reindex=reindex))
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") == "synced" else 1


async def _run_prune_slack_storage(
    *,
    context_retention_days: int | None,
    download_retention_days: int | None,
    reindex: bool,
) -> dict[str, object]:
    payload = await prune_slack_storage(
        context_retention_days=context_retention_days,
        download_retention_days=download_retention_days,
    )
    if reindex:
        payload["indexing"] = await index_all_chunks(reset_collection=True)
    return payload


def cmd_prune_slack_storage(
    *,
    context_retention_days: int | None,
    download_retention_days: int | None,
    reindex: bool,
) -> int:
    payload = asyncio.run(
        _run_prune_slack_storage(
            context_retention_days=context_retention_days,
            download_retention_days=download_retention_days,
            reindex=reindex,
        )
    )
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") in {"pruned", "skipped"} else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cre-cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("import-samples")
    build_large_corpus_parser = subparsers.add_parser("build-large-corpus")
    build_large_corpus_parser.add_argument("--rows", type=int, default=DEFAULT_ROW_COUNT)
    build_large_corpus_parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    subparsers.add_parser("status")
    subparsers.add_parser("audit-data")
    index_chunks_parser = subparsers.add_parser("index-chunks")
    index_chunks_parser.add_argument("--reset", action="store_true")
    ocr_smoke_parser = subparsers.add_parser("ocr-smoke")
    ocr_smoke_parser.add_argument("path")
    ocr_smoke_parser.add_argument("--source-type")
    ocr_smoke_parser.add_argument("--mime-type")
    ask_parser = subparsers.add_parser("ask")
    ask_parser.add_argument("query")
    explain_parser = subparsers.add_parser("explain-query")
    explain_parser.add_argument("query_id")
    replay_parser = subparsers.add_parser("replay-query")
    replay_parser.add_argument("query_id")
    eval_golden_parser = subparsers.add_parser("eval-golden")
    eval_golden_parser.add_argument("--case", dest="cases", action="append")
    demo_doctor_parser = subparsers.add_parser("demo-doctor")
    demo_doctor_parser.add_argument("--skip-public-callback", action="store_true")
    demo_doctor_parser.add_argument("--live-toolhouse", action="store_true")
    demo_dry_run_parser = subparsers.add_parser("demo-dry-run")
    demo_dry_run_parser.add_argument("--skip-public-callback", action="store_true")
    demo_dry_run_parser.add_argument("--live-toolhouse", action="store_true")
    secret_scan_parser = subparsers.add_parser("secret-scan")
    secret_scan_parser.add_argument("--root", default=".")
    submission_report_parser = subparsers.add_parser("submission-report")
    submission_report_parser.add_argument("--skip-public-callback", action="store_true")
    submission_report_parser.add_argument("--live-toolhouse", action="store_true")
    submission_report_parser.add_argument("--format", choices=["json", "markdown"], default="json")
    submission_report_parser.add_argument("--output")
    toolhouse_smoke_parser = subparsers.add_parser("toolhouse-smoke")
    toolhouse_smoke_parser.add_argument(
        "query",
        nargs="?",
        default="Show industrial listings over 30k SF under $25/SF.",
    )
    seed_slack_parser = subparsers.add_parser("seed-slack-personas")
    seed_slack_parser.add_argument("--dry-run", action="store_true")
    seed_slack_parser.add_argument("--replace-legacy-prefix", action="store_true")
    seed_slack_parser.add_argument("--recent-limit", type=int, default=100)
    seed_slack_files_parser = subparsers.add_parser("seed-slack-files")
    seed_slack_files_parser.add_argument("--dry-run", action="store_true")
    seed_slack_files_parser.add_argument("--recent-limit", type=int, default=100)
    seed_slack_files_parser.add_argument("--force-upload", action="store_true")
    seed_slack_files_parser.add_argument("--file", dest="file_names", action="append")
    sync_slack_sources_parser = subparsers.add_parser("sync-slack-demo-sources")
    sync_slack_sources_parser.add_argument("--recent-limit", type=int, default=100)
    sync_slack_history_parser = subparsers.add_parser("sync-slack-channel-history")
    sync_slack_history_parser.add_argument("--channel-id", required=True)
    sync_slack_history_parser.add_argument("--channel-name")
    sync_slack_history_parser.add_argument("--recent-limit", type=int, default=100)
    sync_all_slack_history_parser = subparsers.add_parser("sync-slack-history")
    sync_all_slack_history_parser.add_argument("--recent-limit", type=int, default=100)
    sync_all_slack_history_parser.add_argument("--reindex", action="store_true")
    prune_slack_storage_parser = subparsers.add_parser("prune-slack-storage")
    prune_slack_storage_parser.add_argument("--context-retention-days", type=int)
    prune_slack_storage_parser.add_argument("--download-retention-days", type=int)
    prune_slack_storage_parser.add_argument("--reindex", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "import-samples":
        return cmd_import_samples()
    if args.command == "build-large-corpus":
        return cmd_build_large_corpus(rows=int(args.rows), seed=int(args.seed))
    if args.command == "status":
        return cmd_status()
    if args.command == "audit-data":
        return cmd_audit_data()
    if args.command == "index-chunks":
        return cmd_index_chunks(reset=bool(args.reset))
    if args.command == "ocr-smoke":
        return cmd_ocr_smoke(str(args.path), source_type=args.source_type, mime_type=args.mime_type)
    if args.command == "ask":
        return cmd_ask(args.query)
    if args.command == "explain-query":
        return cmd_explain_query(args.query_id)
    if args.command == "replay-query":
        return cmd_replay_query(args.query_id)
    if args.command == "eval-golden":
        return cmd_eval_golden(case_names=list(args.cases or []))
    if args.command == "demo-doctor":
        return cmd_demo_doctor(
            skip_public_callback=bool(args.skip_public_callback),
            live_toolhouse=bool(args.live_toolhouse),
        )
    if args.command == "demo-dry-run":
        return cmd_demo_dry_run(
            skip_public_callback=bool(args.skip_public_callback),
            live_toolhouse=bool(args.live_toolhouse),
        )
    if args.command == "secret-scan":
        return cmd_secret_scan(root=str(args.root))
    if args.command == "submission-report":
        return cmd_submission_report(
            skip_public_callback=bool(args.skip_public_callback),
            live_toolhouse=bool(args.live_toolhouse),
            output_format=str(args.format),
            output_path=str(args.output) if args.output else None,
        )
    if args.command == "toolhouse-smoke":
        return cmd_toolhouse_smoke(args.query)
    if args.command == "seed-slack-personas":
        return cmd_seed_slack_personas(
            dry_run=bool(args.dry_run),
            replace_legacy_prefix=bool(args.replace_legacy_prefix),
            recent_limit=int(args.recent_limit),
        )
    if args.command == "seed-slack-files":
        return cmd_seed_slack_files(
            dry_run=bool(args.dry_run),
            recent_limit=int(args.recent_limit),
            force_upload=bool(args.force_upload),
            file_names=list(args.file_names or []),
        )
    if args.command == "sync-slack-demo-sources":
        return cmd_sync_slack_demo_sources(recent_limit=int(args.recent_limit))
    if args.command == "sync-slack-channel-history":
        return cmd_sync_slack_channel_history(
            channel_id=str(args.channel_id),
            channel_name=str(args.channel_name) if args.channel_name else None,
            recent_limit=int(args.recent_limit),
        )
    if args.command == "sync-slack-history":
        return cmd_sync_slack_history(recent_limit=int(args.recent_limit), reindex=bool(args.reindex))
    if args.command == "prune-slack-storage":
        return cmd_prune_slack_storage(
            context_retention_days=int(args.context_retention_days) if args.context_retention_days is not None else None,
            download_retention_days=int(args.download_retention_days) if args.download_retention_days is not None else None,
            reindex=bool(args.reindex),
        )

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
