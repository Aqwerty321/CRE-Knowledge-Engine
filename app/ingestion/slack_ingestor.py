from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiohttp
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy import delete, exists, select

from app.config import get_settings
from app.db.session import SessionFactory
from app.extraction.property_extractor import has_cre_ingest_signal, has_structured_listing_signal
from app.ingestion.sample_importer import SampleDatasetModel, SampleSourceModel, import_sample_dataset
from app.models import IngestionJob, PropertyRecord, SlackEvent, SourceDocument


INGEST_MESSAGE_JOB = "ingest_slack_message"
INGEST_FILE_JOB = "ingest_slack_file"
INGEST_JOB_TYPES = {INGEST_MESSAGE_JOB, INGEST_FILE_JOB}
SUPPORTED_TEXT_FILE_SUFFIXES = {".txt", ".md"}
SUPPORTED_TEXT_FILE_MIME_TYPES = {"text/plain", "text/markdown", "text/x-markdown"}
RUNNING_INGEST_STATUSES = {"queued", "running"}
QUERY_LIKE_PREFIXES = (
    "what ",
    "show ",
    "find ",
    "which ",
    "list ",
    "give me ",
    "can you ",
    "could you ",
    "do we ",
    "are there ",
    "best ",
    "top ",
    "where ",
    "who ",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _event_retry_meta(headers: dict[str, str]) -> tuple[int | None, str | None]:
    retry_num_raw = headers.get("x-slack-retry-num")
    retry_reason = headers.get("x-slack-retry-reason")
    retry_num = int(retry_num_raw) if retry_num_raw is not None else None
    return retry_num, retry_reason


def _team_id_from_payload(payload: dict[str, Any]) -> str:
    if payload.get("team_id"):
        return str(payload["team_id"])
    authorizations = payload.get("authorizations")
    if isinstance(authorizations, list) and authorizations:
        authorization = authorizations[0]
        if isinstance(authorization, dict):
            return str(authorization.get("team_id") or "")
    return ""


def _channel_id_from_event(event: dict[str, Any]) -> str:
    item = event.get("item") if isinstance(event.get("item"), dict) else {}
    return str(event.get("channel") or event.get("channel_id") or item.get("channel") or "")


def _ts_to_datetime(slack_ts: str | None) -> datetime:
    if not slack_ts:
        return _utcnow()
    try:
        return datetime.fromtimestamp(float(slack_ts), tz=timezone.utc)
    except ValueError:
        return _utcnow()


async def _resolve_channel_name(client: AsyncWebClient, channel_id: str) -> str:
    try:
        response = await client.conversations_info(channel=channel_id)
    except SlackApiError:
        return channel_id

    channel_payload = response.get("channel") if isinstance(response.get("channel"), dict) else {}
    return str(channel_payload.get("name") or channel_id)


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return cleaned.strip(".-") or "slack-file"


def _source_type_for_file(file_name: str, mime_type: str | None) -> str:
    suffix = Path(file_name).suffix.lower()
    mime = (mime_type or "").lower()
    if suffix == ".pdf" or mime == "application/pdf":
        return "pdf"
    if suffix in {".xlsx", ".xlsm"} or "spreadsheetml" in mime:
        return "xlsx"
    if suffix == ".csv" or mime == "text/csv":
        return "csv"
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"} or mime.startswith("image/"):
        return "image"
    return "text"


def _message_event_is_ignored(event: dict[str, Any]) -> tuple[bool, str | None]:
    subtype = str(event.get("subtype") or "")
    if event.get("bot_id") or subtype == "bot_message":
        return True, "bot_message"
    if subtype and subtype not in {"file_share", "thread_broadcast"}:
        return True, f"unsupported_message_subtype:{subtype}"
    if not str(event.get("text") or "").strip() and not event.get("files"):
        return True, "empty_message"
    return False, None


def _file_payload_is_ingestible(file_payload: dict[str, Any]) -> bool:
    file_name = str(file_payload.get("name") or file_payload.get("title") or "")
    mime_type = str(file_payload.get("mimetype") or file_payload.get("filetype") or "") or None
    source_type = _source_type_for_file(file_name, mime_type)
    if source_type in {"pdf", "xlsx", "csv", "image"}:
        return True
    suffix = Path(file_name).suffix.lower()
    mime = (mime_type or "").lower()
    return source_type == "text" and (suffix in SUPPORTED_TEXT_FILE_SUFFIXES or mime in SUPPORTED_TEXT_FILE_MIME_TYPES)


def _message_text_has_ingest_signal(text: str) -> bool:
    normalized = re.sub(r"<@[^>]+>", "", text).strip().lower()
    if not normalized:
        return False
    if normalized.endswith("?"):
        return False
    if any(normalized.startswith(prefix) for prefix in QUERY_LIKE_PREFIXES):
        return False
    return has_cre_ingest_signal(text)


def _message_text_has_listing_signal(text: str) -> bool:
    normalized = re.sub(r"<@[^>]+>", "", text).strip().lower()
    if not normalized:
        return False
    if normalized.endswith("?"):
        return False
    if any(normalized.startswith(prefix) for prefix in QUERY_LIKE_PREFIXES):
        return False
    return has_structured_listing_signal(text)


def _ingest_policy_for_channel(channel_id: str) -> str:
    return get_settings().slack_ingest_policy_for_channel(channel_id)


def _message_should_be_ingested(*, channel_id: str, text: str) -> bool:
    policy = _ingest_policy_for_channel(channel_id)
    if policy in {"disabled", "files_only"}:
        return False
    if policy == "listings_only":
        return _message_text_has_listing_signal(text)
    return _message_text_has_ingest_signal(text)


def _file_should_be_ingested(*, channel_id: str, file_payload: dict[str, Any]) -> bool:
    policy = _ingest_policy_for_channel(channel_id)
    if policy == "disabled":
        return False
    return _file_payload_is_ingestible(file_payload)


def _resolved_retention_days(explicit_days: int | None, default_days: int) -> int | None:
    if explicit_days is None:
        return default_days if default_days > 0 else None
    return explicit_days if explicit_days > 0 else None


def _path_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _source_url_from_file(file_payload: dict[str, Any]) -> str | None:
    return str(file_payload.get("permalink") or file_payload.get("url_private") or "") or None


async def _permalink_for_message(client: AsyncWebClient | None, channel_id: str, slack_ts: str) -> str | None:
    if client is None or not channel_id or not slack_ts:
        return None
    try:
        response = await client.chat_getPermalink(channel=channel_id, message_ts=slack_ts)
        return str(response.get("permalink") or "") or None
    except SlackApiError:
        return None


async def enqueue_slack_ingestion_event(payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    settings = get_settings()
    event = dict(payload.get("event", {}))
    event_type = str(event.get("type") or "unknown")
    team_id = _team_id_from_payload(payload)
    event_id = str(payload.get("event_id") or "")
    channel_id = _channel_id_from_event(event)
    retry_num, retry_reason = _event_retry_meta(headers)

    async with SessionFactory() as session:
        async with session.begin():
            existing_event = await session.scalar(
                select(SlackEvent).where(
                    SlackEvent.slack_team_id == team_id,
                    SlackEvent.slack_event_id == event_id,
                )
            )
            if existing_event is not None:
                if retry_num is not None:
                    existing_event.retry_num = retry_num
                if retry_reason is not None:
                    existing_event.retry_reason = retry_reason
                existing_event.processed_at = _utcnow()
                return {"status": "duplicate", "event_id": event_id}

            slack_event = SlackEvent(
                slack_event_id=event_id,
                slack_team_id=team_id or None,
                slack_channel_id=channel_id or None,
                event_type=event_type,
                retry_num=retry_num,
                retry_reason=retry_reason,
                payload_hash=_payload_hash(payload),
                status="received",
            )
            session.add(slack_event)
            await session.flush()

            if channel_id not in settings.slack_ingest_channels:
                slack_event.status = "ignored"
                slack_event.error_code = "channel_not_allowed"
                slack_event.processed_at = _utcnow()
                return {"status": "ignored", "event_id": event_id, "channel_id": channel_id}

            jobs: list[IngestionJob] = []
            if event_type == "message":
                ignored, reason = _message_event_is_ignored(event)
                if ignored:
                    slack_event.status = "ignored"
                    slack_event.error_code = reason
                    slack_event.processed_at = _utcnow()
                    return {"status": "ignored", "event_id": event_id, "reason": reason}

                text = str(event.get("text") or "").strip()
                if text and _message_should_be_ingested(channel_id=channel_id, text=text):
                    jobs.append(
                        IngestionJob(
                            job_type=INGEST_MESSAGE_JOB,
                            status="queued",
                            attempt_count=0,
                            checkpoint_json={
                                "slack_event_id": event_id,
                                "team_id": team_id,
                                "channel_id": channel_id,
                                "channel_name": str(event.get("channel_name") or channel_id),
                                "user_id": str(event.get("user") or ""),
                                "message_ts": str(event.get("ts") or event.get("event_ts") or ""),
                                "thread_ts": str(event.get("thread_ts") or ""),
                                "text": text,
                            },
                        )
                    )

                event_files = event.get("files") if isinstance(event.get("files"), list) else []
                for file_payload in event_files:
                    if not isinstance(file_payload, dict):
                        continue
                    if not _file_should_be_ingested(channel_id=channel_id, file_payload=file_payload):
                        continue
                    jobs.append(
                        IngestionJob(
                            job_type=INGEST_FILE_JOB,
                            status="queued",
                            attempt_count=0,
                            checkpoint_json={
                                "slack_event_id": event_id,
                                "team_id": team_id,
                                "channel_id": channel_id,
                                "channel_name": str(event.get("channel_name") or channel_id),
                                "user_id": str(event.get("user") or ""),
                                "message_ts": str(event.get("ts") or event.get("event_ts") or ""),
                                "thread_ts": str(event.get("thread_ts") or ""),
                                "file_id": str(file_payload.get("id") or ""),
                                "file_payload": file_payload,
                            },
                        )
                    )

            if event_type == "file_shared":
                file_id = str(event.get("file_id") or "")
                if file_id and _ingest_policy_for_channel(channel_id) != "disabled":
                    jobs.append(
                        IngestionJob(
                            job_type=INGEST_FILE_JOB,
                            status="queued",
                            attempt_count=0,
                            checkpoint_json={
                                "slack_event_id": event_id,
                                "team_id": team_id,
                                "channel_id": channel_id,
                                "channel_name": channel_id,
                                "user_id": str(event.get("user_id") or event.get("user") or ""),
                                "message_ts": str(event.get("event_ts") or ""),
                                "thread_ts": "",
                                "file_id": file_id,
                            },
                        )
                    )

            if not jobs:
                slack_event.status = "ignored"
                slack_event.error_code = "no_ingest_signal"
                slack_event.processed_at = _utcnow()
                return {"status": "ignored", "event_id": event_id, "reason": "no_ingest_signal"}

            for job in jobs:
                session.add(job)
            await session.flush()
            slack_event.status = "queued"
            slack_event.processed_at = _utcnow()
            return {
                "status": "queued",
                "event_id": event_id,
                "channel_id": channel_id,
                "job_ids": [str(job.id) for job in jobs],
            }


async def ingest_slack_message_checkpoint(checkpoint: dict[str, Any], client: AsyncWebClient | None = None) -> dict[str, Any]:
    team_id = str(checkpoint.get("team_id") or "")
    channel_id = str(checkpoint.get("channel_id") or "")
    message_ts = str(checkpoint.get("message_ts") or "")
    text = str(checkpoint.get("text") or "").strip()
    if not _message_should_be_ingested(channel_id=channel_id, text=text):
        return {"status": "ignored", "source_type": "slack_message", "reason": "no_ingest_signal"}
    source_url = await _permalink_for_message(client, channel_id, message_ts)
    source = SampleSourceModel(
        source_id=f"slack-message:{channel_id}:{message_ts}",
        source_type="slack_message",
        posted_at=_ts_to_datetime(message_ts),
        slack_user_id=str(checkpoint.get("user_id") or "") or None,
        slack_ts=message_ts or None,
        slack_thread_ts=str(checkpoint.get("thread_ts") or "") or None,
        source_url=source_url,
        raw_text=text,
    )
    dataset = SampleDatasetModel(
        team_id=team_id,
        channel_id=channel_id,
        channel_name=str(checkpoint.get("channel_name") or channel_id),
        sources=[source],
    )
    result = await import_sample_dataset(dataset, get_settings().sample_data_dir)
    return {"status": "ingested", "source_type": "slack_message", **result}


async def _fetch_file_payload(client: AsyncWebClient | None, file_id: str) -> dict[str, Any]:
    if client is None:
        raise ValueError("Slack client is required to resolve file_shared events")
    response = await client.files_info(file=file_id)
    file_payload = response.get("file")
    if not isinstance(file_payload, dict):
        raise ValueError(f"Slack file metadata not found for {file_id}")
    return file_payload


async def _download_file(file_payload: dict[str, Any], *, team_id: str, file_id: str, client: AsyncWebClient | None) -> Path:
    if file_payload.get("local_path"):
        return Path(str(file_payload["local_path"]))

    download_url = str(file_payload.get("url_private_download") or file_payload.get("url_private") or "")
    if not download_url:
        raise ValueError(f"Slack file {file_id} has no private download URL")

    token = str(getattr(client, "token", "") or get_settings().slack_bot_token or "")
    if not token:
        raise ValueError("Slack bot token is required to download files")

    file_name = _safe_filename(str(file_payload.get("name") or file_payload.get("title") or file_id))
    target_dir = get_settings().slack_download_dir / _safe_filename(team_id or "workspace")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{_safe_filename(file_id)}-{file_name}"
    if target_path.exists():
        return target_path

    async with aiohttp.ClientSession(headers={"Authorization": f"Bearer {token}"}) as session:
        async with session.get(download_url) as response:
            response.raise_for_status()
            target_path.write_bytes(await response.read())
    return target_path


async def _fetch_thread_replies(
    client: AsyncWebClient,
    *,
    channel_id: str,
    thread_ts: str,
    max_replies: int = 200,
) -> list[dict[str, Any]]:
    replies: list[dict[str, Any]] = []
    cursor: str | None = None
    while len(replies) < max_replies:
        try:
            response = await client.conversations_replies(
                channel=channel_id,
                ts=thread_ts,
                limit=min(200, max_replies - len(replies)),
                cursor=cursor,
            )
        except SlackApiError:
            break
        messages = [message for message in list(response.get("messages", [])) if isinstance(message, dict)]
        replies.extend(messages)
        cursor = str(response.get("response_metadata", {}).get("next_cursor") or "")
        if not cursor:
            break
    return replies


async def ingest_slack_file_checkpoint(checkpoint: dict[str, Any], client: AsyncWebClient | None = None) -> dict[str, Any]:
    team_id = str(checkpoint.get("team_id") or "")
    channel_id = str(checkpoint.get("channel_id") or "")
    file_payload = checkpoint.get("file_payload") if isinstance(checkpoint.get("file_payload"), dict) else {}
    file_id = str(file_payload.get("id") or checkpoint.get("file_id") or "")
    if not file_payload:
        file_payload = await _fetch_file_payload(client, file_id)
    if not _file_should_be_ingested(channel_id=channel_id, file_payload=file_payload):
        return {"status": "ignored", "source_type": "slack_file", "file_id": file_id, "reason": "unsupported_file_type"}

    local_path = await _download_file(file_payload, team_id=team_id, file_id=file_id, client=client)
    file_name = str(file_payload.get("name") or file_payload.get("title") or local_path.name)
    mime_type = str(file_payload.get("mimetype") or file_payload.get("filetype") or "") or None
    message_ts = str(checkpoint.get("message_ts") or file_payload.get("created") or "")
    source_url = await _permalink_for_message(client, channel_id, message_ts)
    source = SampleSourceModel(
        source_id=f"slack-file:{file_id}",
        source_type=_source_type_for_file(file_name, mime_type),
        posted_at=_ts_to_datetime(message_ts),
        slack_user_id=str(checkpoint.get("user_id") or file_payload.get("user") or "") or None,
        slack_ts=str(checkpoint.get("message_ts") or "") or None,
        slack_thread_ts=str(checkpoint.get("thread_ts") or "") or None,
        slack_file_id=file_id,
        file_name=file_name,
        file_mime_type=mime_type,
        source_url=source_url or _source_url_from_file(file_payload),
        local_path=str(local_path),
    )
    dataset = SampleDatasetModel(
        team_id=team_id,
        channel_id=channel_id,
        channel_name=str(checkpoint.get("channel_name") or channel_id),
        sources=[source],
    )
    result = await import_sample_dataset(dataset, get_settings().sample_data_dir)
    return {"status": "ingested", "source_type": source.source_type, "file_id": file_id, **result}


async def process_slack_ingestion_job(
    job_type: str,
    checkpoint: dict[str, Any],
    client: AsyncWebClient | None = None,
) -> dict[str, Any]:
    if job_type == INGEST_MESSAGE_JOB:
        return await ingest_slack_message_checkpoint(checkpoint, client)
    if job_type == INGEST_FILE_JOB:
        return await ingest_slack_file_checkpoint(checkpoint, client)
    raise ValueError(f"Unsupported Slack ingestion job type: {job_type}")


async def backfill_slack_channel_history(
    client: AsyncWebClient,
    *,
    channel_id: str,
    channel_name: str | None = None,
    recent_limit: int = 100,
) -> dict[str, Any]:
    auth_payload = await client.auth_test()
    team_id = str(auth_payload.get("team_id") or "")
    resolved_channel_name = channel_name or await _resolve_channel_name(client, channel_id)
    cursor: str | None = None
    seen_messages = 0
    seen_thread_replies = 0
    ingested_messages = 0
    ingested_files = 0
    import_results: list[dict[str, Any]] = []

    while seen_messages < recent_limit:
        response = await client.conversations_history(
            channel=channel_id,
            limit=min(200, recent_limit - seen_messages),
            cursor=cursor,
        )
        messages = list(response.get("messages", []))
        if not messages:
            break

        for message in messages:
            if not isinstance(message, dict):
                continue
            seen_messages += 1
            ignored, _reason = _message_event_is_ignored(message)
            if ignored:
                continue
            base_checkpoint = {
                "team_id": team_id,
                "channel_id": channel_id,
                "channel_name": resolved_channel_name,
                "user_id": str(message.get("user") or ""),
                "message_ts": str(message.get("ts") or ""),
                "thread_ts": str(message.get("thread_ts") or ""),
            }
            text = str(message.get("text") or "").strip()
            if text and _message_should_be_ingested(channel_id=channel_id, text=text):
                result = await ingest_slack_message_checkpoint({**base_checkpoint, "text": text}, client)
                import_results.append(result)
                ingested_messages += int(result.get("imported_source_count") or 0)
            message_files = message.get("files") if isinstance(message.get("files"), list) else []
            for file_payload in message_files:
                if not isinstance(file_payload, dict):
                    continue
                if not _file_should_be_ingested(channel_id=channel_id, file_payload=file_payload):
                    continue
                result = await ingest_slack_file_checkpoint(
                    {
                        **base_checkpoint,
                        "file_id": str(file_payload.get("id") or ""),
                        "file_payload": file_payload,
                    },
                    client,
                )
                import_results.append(result)
                ingested_files += int(result.get("imported_source_count") or 0)

            reply_count = int(message.get("reply_count") or 0)
            thread_ts = str(message.get("thread_ts") or message.get("ts") or "")
            if reply_count > 0 and thread_ts:
                replies = await _fetch_thread_replies(client, channel_id=channel_id, thread_ts=thread_ts)
                for reply in replies:
                    reply_ts = str(reply.get("ts") or "")
                    if not reply_ts or reply_ts == str(message.get("ts") or ""):
                        continue
                    seen_thread_replies += 1
                    ignored, _reason = _message_event_is_ignored(reply)
                    if ignored:
                        continue
                    reply_checkpoint = {
                        "team_id": team_id,
                        "channel_id": channel_id,
                        "channel_name": resolved_channel_name,
                        "user_id": str(reply.get("user") or ""),
                        "message_ts": reply_ts,
                        "thread_ts": thread_ts,
                    }
                    reply_text = str(reply.get("text") or "").strip()
                    if reply_text and _message_should_be_ingested(channel_id=channel_id, text=reply_text):
                        result = await ingest_slack_message_checkpoint({**reply_checkpoint, "text": reply_text}, client)
                        import_results.append(result)
                        ingested_messages += int(result.get("imported_source_count") or 0)
                    reply_files = reply.get("files") if isinstance(reply.get("files"), list) else []
                    for file_payload in reply_files:
                        if not isinstance(file_payload, dict):
                            continue
                        if not _file_should_be_ingested(channel_id=channel_id, file_payload=file_payload):
                            continue
                        result = await ingest_slack_file_checkpoint(
                            {
                                **reply_checkpoint,
                                "file_id": str(file_payload.get("id") or ""),
                                "file_payload": file_payload,
                            },
                            client,
                        )
                        import_results.append(result)
                        ingested_files += int(result.get("imported_source_count") or 0)

        cursor = str(response.get("response_metadata", {}).get("next_cursor") or "")
        if not cursor:
            break

    return {
        "status": "synced",
        "team_id": team_id,
        "channel_id": channel_id,
        "channel_name": resolved_channel_name,
        "seen_message_count": seen_messages,
        "seen_thread_reply_count": seen_thread_replies,
        "ingested_message_source_count": ingested_messages,
        "ingested_file_source_count": ingested_files,
        "import_results": import_results,
    }


async def prune_slack_storage(
    *,
    context_retention_days: int | None = None,
    download_retention_days: int | None = None,
) -> dict[str, object]:
    settings = get_settings()
    live_channel_ids = set(settings.slack_ingest_channels)
    if not live_channel_ids:
        return {
            "status": "skipped",
            "reason": "missing_slack_ingest_channels",
            "deleted_context_source_count": 0,
            "released_download_count": 0,
            "deleted_orphan_download_count": 0,
        }

    resolved_context_days = _resolved_retention_days(context_retention_days, settings.slack_context_retention_days)
    resolved_download_days = _resolved_retention_days(download_retention_days, settings.slack_download_retention_days)
    context_cutoff = _utcnow() - timedelta(days=resolved_context_days) if resolved_context_days is not None else None
    download_cutoff = _utcnow() - timedelta(days=resolved_download_days) if resolved_download_days is not None else None
    download_root = settings.slack_download_dir

    deleted_context_sources: list[dict[str, str | None]] = []
    released_downloads: list[str] = []
    orphan_downloads: list[str] = []

    async with SessionFactory() as session:
        property_backed_ids = set(
            await session.scalars(select(PropertyRecord.document_id).distinct())
        )
        busy_source_ids = set(
            await session.scalars(
                select(IngestionJob.source_document_id)
                .where(
                    IngestionJob.source_document_id.is_not(None),
                    IngestionJob.status.in_(sorted(RUNNING_INGEST_STATUSES)),
                )
                .distinct()
            )
        )
        result = await session.execute(
            select(SourceDocument)
            .where(
                SourceDocument.slack_channel_id.in_(sorted(live_channel_ids)),
            )
            .order_by(SourceDocument.posted_at, SourceDocument.ingested_at)
        )
        source_documents = list(result.scalars())

        referenced_download_paths = {
            str(source.local_path)
            for source in source_documents
            if source.local_path
        }

        context_ids_to_delete = []
        source_ids_to_release_paths = []
        paths_to_delete: set[str] = set()
        for source in source_documents:
            is_property_backed = source.id in property_backed_ids
            if (
                context_cutoff is not None
                and source.source_type == "slack_message"
                and source.id not in busy_source_ids
                and not is_property_backed
                and source.posted_at is not None
                and source.posted_at <= context_cutoff
            ):
                context_ids_to_delete.append(source.id)
                deleted_context_sources.append(
                    {
                        "id": str(source.id),
                        "slack_ts": source.slack_ts,
                        "channel_id": source.slack_channel_id,
                        "source_type": source.source_type,
                    }
                )
                continue

            if (
                download_cutoff is not None
                and source.slack_file_id
                and source.local_path
                and source.id not in busy_source_ids
                and source.posted_at is not None
                and source.posted_at <= download_cutoff
            ):
                local_path = Path(source.local_path)
                if _path_within_root(local_path, download_root):
                    source_ids_to_release_paths.append(source.id)
                    paths_to_delete.add(str(local_path))
                    released_downloads.append(str(local_path))

    if context_ids_to_delete or source_ids_to_release_paths:
        async with SessionFactory() as session:
            async with session.begin():
                if context_ids_to_delete:
                    result = await session.execute(select(SourceDocument).where(SourceDocument.id.in_(context_ids_to_delete)))
                    for source in result.scalars():
                        await session.delete(source)
                if source_ids_to_release_paths:
                    result = await session.execute(select(SourceDocument).where(SourceDocument.id.in_(source_ids_to_release_paths)))
                    for source in result.scalars():
                        source.local_path = None

    if download_cutoff is not None and download_root.exists():
        for path in download_root.rglob("*"):
            if not path.is_file():
                continue
            if not _path_within_root(path, download_root):
                continue
            if str(path) in paths_to_delete:
                continue
            if str(path) in referenced_download_paths:
                continue
            if datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) > download_cutoff:
                continue
            orphan_downloads.append(str(path))
            paths_to_delete.add(str(path))

    for path_str in sorted(paths_to_delete):
        path = Path(path_str)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue

    return {
        "status": "pruned",
        "context_retention_days": resolved_context_days,
        "download_retention_days": resolved_download_days,
        "deleted_context_source_count": len(deleted_context_sources),
        "deleted_context_sources": deleted_context_sources,
        "released_download_count": len(released_downloads),
        "released_downloads": released_downloads,
        "deleted_orphan_download_count": len(orphan_downloads),
        "deleted_orphan_downloads": orphan_downloads,
    }


__all__ = [
    "INGEST_FILE_JOB",
    "INGEST_JOB_TYPES",
    "INGEST_MESSAGE_JOB",
    "backfill_slack_channel_history",
    "enqueue_slack_ingestion_event",
    "prune_slack_storage",
    "process_slack_ingestion_job",
]