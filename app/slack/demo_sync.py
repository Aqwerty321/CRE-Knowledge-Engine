from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from slack_sdk import WebClient

from app.ingestion.sample_importer import SampleDatasetModel, SampleSourceModel, import_sample_dataset, load_sample_manifest
from app.slack.demo_files import build_default_file_seed_plan
from app.slack.demo_seed import build_default_persona_seed_plan


@dataclass(frozen=True)
class LiveSlackFileMatch:
    channel_id: str
    channel_name: str
    slack_file_id: str
    slack_ts: str
    posted_at: datetime
    source_url: str | None


@dataclass(frozen=True)
class LiveSlackMessageMatch:
    channel_id: str
    channel_name: str
    slack_ts: str
    posted_at: datetime
    source_url: str | None
    slack_user_id: str | None


def _primary_file_channel_map() -> dict[str, str]:
    channels_by_file: dict[str, str] = {}
    for seed in build_default_file_seed_plan():
        channels_by_file.setdefault(seed.file_name, seed.channel_name)
    return channels_by_file


def _primary_file_title_map() -> dict[str, str]:
    titles_by_file: dict[str, str] = {}
    for seed in build_default_file_seed_plan():
        titles_by_file.setdefault(seed.file_name, seed.title)
    return titles_by_file


def _primary_message_channel_map() -> dict[str, str]:
    channels_by_text: dict[str, str] = {}
    for seed in build_default_persona_seed_plan():
        if seed.reply_to_seed_key is not None:
            continue
        channels_by_text.setdefault(seed.text, seed.channel_name)
    return channels_by_text


def _slack_ts_to_datetime(slack_ts: str) -> datetime:
    return datetime.fromtimestamp(float(slack_ts), tz=timezone.utc)


def _resolve_channel_ids(client: WebClient, channel_names: set[str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    cursor: str | None = None

    while True:
        response = client.conversations_list(types="public_channel,private_channel", limit=1000, cursor=cursor)
        for channel in response.get("channels", []):
            channel_name = str(channel.get("name") or "")
            if channel_name in channel_names:
                resolved[channel_name] = str(channel.get("id") or "")

        if len(resolved) == len(channel_names):
            break

        cursor = str(response.get("response_metadata", {}).get("next_cursor") or "")
        if not cursor:
            break

    missing = sorted(channel_names - set(resolved))
    if missing:
        raise ValueError(f"Missing Slack channels for demo sync: {', '.join(missing)}")

    return resolved


def _fetch_channel_histories(client: WebClient, channel_ids: dict[str, str], recent_limit: int) -> dict[str, list[dict[str, Any]]]:
    histories: dict[str, list[dict[str, Any]]] = {}
    for channel_name, channel_id in channel_ids.items():
        response = client.conversations_history(channel=channel_id, limit=recent_limit)
        histories[channel_name] = list(response.get("messages", []))
    return histories


def _build_live_file_matches(
    histories: dict[str, list[dict[str, Any]]],
    channel_ids: dict[str, str],
) -> dict[str, LiveSlackFileMatch]:
    matches: dict[str, LiveSlackFileMatch] = {}
    titles_by_file = _primary_file_title_map()

    for file_name, channel_name in _primary_file_channel_map().items():
        expected_title = titles_by_file.get(file_name)
        for message in histories[channel_name]:
            for file_payload in list(message.get("files", [])):
                live_name = str(file_payload.get("name") or "")
                live_title = str(file_payload.get("title") or "")
                if live_name != file_name and live_title != expected_title:
                    continue

                slack_ts = str(message.get("ts") or "")
                matches[file_name] = LiveSlackFileMatch(
                    channel_id=channel_ids[channel_name],
                    channel_name=channel_name,
                    slack_file_id=str(file_payload.get("id") or ""),
                    slack_ts=slack_ts,
                    posted_at=_slack_ts_to_datetime(slack_ts),
                    source_url=str(file_payload.get("permalink") or "") or None,
                )
                break
            if file_name in matches:
                break

    return matches


def _build_live_message_matches(
    client: WebClient,
    histories: dict[str, list[dict[str, Any]]],
    channel_ids: dict[str, str],
) -> dict[str, LiveSlackMessageMatch]:
    matches: dict[str, LiveSlackMessageMatch] = {}

    for text, channel_name in _primary_message_channel_map().items():
        for message in histories[channel_name]:
            if str(message.get("text") or "") != text:
                continue

            slack_ts = str(message.get("ts") or "")
            permalink = client.chat_getPermalink(channel=channel_ids[channel_name], message_ts=slack_ts)
            matches[text] = LiveSlackMessageMatch(
                channel_id=channel_ids[channel_name],
                channel_name=channel_name,
                slack_ts=slack_ts,
                posted_at=_slack_ts_to_datetime(slack_ts),
                source_url=str(permalink.get("permalink") or "") or None,
                slack_user_id=str(message.get("user") or "") or None,
            )
            break

    return matches


def build_live_demo_datasets(client: WebClient, sample_data_dir: Path, recent_limit: int = 100) -> tuple[list[SampleDatasetModel], dict[str, Any]]:
    manifest = load_sample_manifest(sample_data_dir)
    auth_payload = client.auth_test()
    team_id = str(auth_payload.get("team_id") or manifest.team_id)

    required_channels = set(_primary_file_channel_map().values()) | set(_primary_message_channel_map().values())
    channel_ids = _resolve_channel_ids(client, required_channels)
    histories = _fetch_channel_histories(client, channel_ids, recent_limit)
    file_matches = _build_live_file_matches(histories, channel_ids)
    message_matches = _build_live_message_matches(client, histories, channel_ids)

    unresolved_files: list[str] = []
    unresolved_messages: list[str] = []
    grouped_sources: dict[tuple[str, str], list[SampleSourceModel]] = defaultdict(list)
    resolved_file_source_count = 0
    resolved_message_source_count = 0

    for source in manifest.sources:
        if source.source_type == "slack_message":
            message_text = str(source.raw_text or "")
            live_match = message_matches.get(message_text)
            if live_match is None:
                unresolved_messages.append(source.source_id)
                continue

            updated_source = source.model_copy(
                update={
                    "slack_ts": live_match.slack_ts,
                    "posted_at": live_match.posted_at,
                    "source_url": live_match.source_url,
                    "slack_user_id": live_match.slack_user_id or source.slack_user_id,
                }
            )
            grouped_sources[(live_match.channel_id, live_match.channel_name)].append(updated_source)
            resolved_message_source_count += 1
            continue

        if source.local_path is None:
            unresolved_files.append(source.source_id)
            continue

        live_match = file_matches.get(Path(source.local_path).name)
        if live_match is None:
            unresolved_files.append(source.source_id)
            continue

        updated_source = source.model_copy(
            update={
                "slack_file_id": live_match.slack_file_id,
                "slack_ts": live_match.slack_ts,
                "posted_at": live_match.posted_at,
                "source_url": live_match.source_url or source.source_url,
            }
        )
        grouped_sources[(live_match.channel_id, live_match.channel_name)].append(updated_source)
        resolved_file_source_count += 1

    if unresolved_files or unresolved_messages:
        unresolved_parts: list[str] = []
        if unresolved_files:
            unresolved_parts.append(f"file sources: {', '.join(unresolved_files)}")
        if unresolved_messages:
            unresolved_parts.append(f"message sources: {', '.join(unresolved_messages)}")
        raise ValueError(f"Could not resolve live Slack metadata for { '; '.join(unresolved_parts) }")

    datasets = [
        SampleDatasetModel(
            team_id=team_id,
            channel_id=channel_id,
            channel_name=channel_name,
            sources=sources,
        )
        for (channel_id, channel_name), sources in sorted(grouped_sources.items(), key=lambda item: item[0][1])
    ]

    metadata = {
        "team_id": team_id,
        "channel_ids": channel_ids,
        "matched_file_source_count": resolved_file_source_count,
        "matched_message_source_count": resolved_message_source_count,
        "dataset_count": len(datasets),
    }
    return datasets, metadata


async def sync_live_demo_sources(client: WebClient, sample_data_dir: Path, recent_limit: int = 100) -> dict[str, Any]:
    datasets, metadata = build_live_demo_datasets(client, sample_data_dir, recent_limit)
    import_results: list[dict[str, Any]] = []
    total_imported_sources = 0
    total_imported_chunks = 0
    total_imported_property_records = 0
    total_imported_jobs = 0
    database_counts: dict[str, int] = {}

    for dataset in datasets:
        result = await import_sample_dataset(dataset, sample_data_dir)
        import_results.append(
            {
                "channel_name": dataset.channel_name,
                "channel_id": dataset.channel_id,
                "source_count": len(dataset.sources),
                "imported_source_count": result["imported_source_count"],
            }
        )
        total_imported_sources += int(result["imported_source_count"])
        total_imported_chunks += int(result["imported_chunk_count"])
        total_imported_property_records += int(result["imported_property_record_count"])
        total_imported_jobs += int(result["imported_job_count"])
        database_counts = dict(result["database_counts"])

    return {
        "status": "synced",
        **metadata,
        "import_results": import_results,
        "imported_source_count": total_imported_sources,
        "imported_chunk_count": total_imported_chunks,
        "imported_property_record_count": total_imported_property_records,
        "imported_job_count": total_imported_jobs,
        "database_counts": database_counts,
    }


__all__ = ["build_live_demo_datasets", "sync_live_demo_sources"]