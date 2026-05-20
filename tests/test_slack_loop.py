from __future__ import annotations

import asyncio
import csv
import hashlib
import hmac
import io
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from fastapi.testclient import TestClient
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.answering.follow_up_suggestions import store_agent_follow_up_suggestions
from app.answering.query_service import explain_query
from app.config import get_settings
from app.db.session import SessionFactory, engine
from app.ingestion.sample_importer import import_sample_data
from app.ingestion.slack_ingestor import backfill_slack_channel_history
from app.main import create_app
from app.models import AnswerSnapshot, Chunk, EvidenceItem, IngestionJob, PropertyRecord, Query, SlackEvent, SourceDocument, ThreadSession
from app.slack.gateway import RecordingSlackGateway
from app.slack.runtime import get_slack_app, get_slack_handler
from app.slack.service import (
    FOLLOW_UP_MODAL_REFRESH_ACTION_ID,
    build_answer_blocks,
    build_comparison_table_csv_attachment,
    build_slack_reply_text,
    enqueue_follow_up_request,
    validate_follow_up_modal_submission,
)
from app.workers import process_pending_query_jobs


SLACK_TEST_SOURCE_TS_VALUES = {
    "1715860001.000100",
    "1715860002.000100",
    "1715860003.000100",
    "1715860004.000100",
    "1715860005.000100",
}


def _ensure_schema() -> None:
    command.upgrade(Config("alembic.ini"), "head")


def _configure_slack_env(monkeypatch: pytest.MonkeyPatch, *, ingest_channel_policies: str = "") -> None:
    monkeypatch.setenv("CRE_SLACK_SIGNING_SECRET", "test-signing-secret")
    monkeypatch.setenv("CRE_SLACK_BOT_TOKEN", "xoxb-test-token")
    monkeypatch.setenv("CRE_CONFIGURED_CHANNEL_IDS", "C_CRE_LISTINGS_DEMO")
    monkeypatch.setenv("CRE_SLACK_INGEST_CHANNEL_POLICIES_RAW", ingest_channel_policies)
    monkeypatch.setenv("CRE_SLACK_CONTEXT_RETENTION_DAYS", "30")
    monkeypatch.setenv("CRE_SLACK_DOWNLOAD_RETENTION_DAYS", "7")
    monkeypatch.setenv("CRE_TOOLHOUSE_API_KEY", "")
    monkeypatch.setenv("CRE_TOOLHOUSE_AGENT_ID", "")
    monkeypatch.setenv("CRE_TOOLHOUSE_MCP_BEARER_TOKEN", "")
    get_settings.cache_clear()
    get_slack_app.cache_clear()
    get_slack_handler.cache_clear()


async def _prepare_slack_database() -> None:
    await import_sample_data(Path("sample-data"), include_generated=False)
    async with SessionFactory() as session:
        async with session.begin():
            await session.execute(delete(AnswerSnapshot))
            await session.execute(delete(EvidenceItem))
            await session.execute(delete(Query))
            await session.execute(delete(ThreadSession))
            await session.execute(delete(IngestionJob).where(IngestionJob.job_type.in_(["answer_query", "look_deeper", "force_agent", "follow_up"])))
            await session.execute(delete(SlackEvent))


async def _cleanup_slack_test_sources() -> None:
    async with SessionFactory() as session:
        async with session.begin():
            await session.execute(delete(SourceDocument).where(SourceDocument.slack_ts.in_(SLACK_TEST_SOURCE_TS_VALUES)))


async def _counts() -> dict[str, int]:
    async with SessionFactory() as session:
        slack_events = int(await session.scalar(select(func.count()).select_from(SlackEvent)) or 0)
        queued_jobs = int(
            await session.scalar(
                select(func.count())
                .select_from(IngestionJob)
                .where(IngestionJob.job_type == "answer_query")
            )
            or 0
        )
        queued_ingest_jobs = int(
            await session.scalar(
                select(func.count())
                .select_from(IngestionJob)
                .where(IngestionJob.job_type.in_(["ingest_slack_message", "ingest_slack_file"]), IngestionJob.status == "queued")
            )
            or 0
        )
        queries = int(await session.scalar(select(func.count()).select_from(Query)) or 0)
        return {
            "slack_events": slack_events,
            "query_jobs": queued_jobs,
            "queued_ingest_jobs": queued_ingest_jobs,
            "queries": queries,
        }


async def _load_source_for_slack_ts(slack_ts: str) -> tuple[SourceDocument | None, list[Chunk]]:
    async with SessionFactory() as session:
        source = await session.scalar(select(SourceDocument).where(SourceDocument.slack_ts == slack_ts))
        if source is None:
            return None, []
        result = await session.execute(select(Chunk).where(Chunk.document_id == source.id).order_by(Chunk.chunk_index))
        return source, list(result.scalars())


async def _load_properties_for_slack_ts(slack_ts: str) -> list[PropertyRecord]:
    async with SessionFactory() as session:
        source = await session.scalar(select(SourceDocument).where(SourceDocument.slack_ts == slack_ts))
        if source is None:
            return []
        result = await session.execute(select(PropertyRecord).where(PropertyRecord.document_id == source.id).order_by(PropertyRecord.address))
        return list(result.scalars())


async def _load_latest_query() -> Query | None:
    async with SessionFactory() as session:
        result = await session.execute(select(Query).order_by(Query.created_at.desc()).limit(1))
        return result.scalar_one_or_none()


async def _load_latest_job(job_type: str) -> IngestionJob | None:
    async with SessionFactory() as session:
        result = await session.execute(
            select(IngestionJob).where(IngestionJob.job_type == job_type).order_by(IngestionJob.created_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()


async def _load_thread_session(channel_id: str, thread_ts: str) -> ThreadSession | None:
    async with SessionFactory() as session:
        return await session.scalar(
            select(ThreadSession).where(
                ThreadSession.slack_channel_id == channel_id,
                ThreadSession.slack_thread_ts == thread_ts,
            )
        )


@pytest.fixture
def async_runner() -> asyncio.Runner:
    with asyncio.Runner() as runner:
        yield runner
        runner.run(engine.dispose())


@pytest.fixture
def configured_slack_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_slack_env(monkeypatch)


@pytest.fixture
def configured_slack_env_files_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_slack_env(monkeypatch, ingest_channel_policies="C_CRE_LISTINGS_DEMO=files_only")


@pytest.fixture
def prepared_slack_db(async_runner: asyncio.Runner, configured_slack_env: None) -> None:
    try:
        _ensure_schema()
        async_runner.run(_prepare_slack_database())
    except (OSError, SQLAlchemyError) as exc:
        pytest.skip(f"Postgres not available for Slack loop tests: {exc}")
    yield
    async_runner.run(_cleanup_slack_test_sources())


@pytest.fixture
def prepared_slack_db_files_only(async_runner: asyncio.Runner, configured_slack_env_files_only: None) -> None:
    try:
        _ensure_schema()
        async_runner.run(_prepare_slack_database())
    except (OSError, SQLAlchemyError) as exc:
        pytest.skip(f"Postgres not available for Slack loop tests: {exc}")
    yield
    async_runner.run(_cleanup_slack_test_sources())


def _signed_headers(secret: str, body: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    signature_base = f"v0:{timestamp}:{body}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), signature_base, hashlib.sha256).hexdigest()
    return {
        "x-slack-request-timestamp": timestamp,
        "x-slack-signature": f"v0={digest}",
    }


async def _post_request(
    path: str,
    *,
    content: str,
    headers: dict[str, str],
):
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://testserver") as client:
        return await client.post(path, content=content, headers=headers)


async def _get_request(path: str):
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://testserver") as client:
        return await client.get(path)


def _app_mention_payload(channel_id: str = "C_CRE_LISTINGS_DEMO") -> dict[str, object]:
    return {
        "token": "ignored",
        "team_id": "T_CRE_DEMO",
        "api_app_id": "A_CRE_DEMO",
        "event": {
            "type": "app_mention",
            "channel": channel_id,
            "user": "U_REQUESTOR",
            "text": "<@U_BOT> Show office buildings under $50/sq ft.",
            "ts": "1715860000.000100",
        },
        "type": "event_callback",
        "event_id": "Ev_test_app_mention_1",
        "event_time": 1715860000,
        "authorizations": [{"team_id": "T_CRE_DEMO"}],
    }


def _unsupported_app_mention_payload(channel_id: str = "C_CRE_LISTINGS_DEMO") -> dict[str, object]:
    payload = _app_mention_payload(channel_id)
    payload["event_id"] = "Ev_test_app_mention_unsupported_1"
    event = dict(payload["event"])
    event["text"] = "<@U_BOT> where is this located"
    event["ts"] = "1715860000.000200"
    payload["event"] = event
    return payload


def _auto_thread_follow_up_payload(channel_id: str = "C_CRE_LISTINGS_DEMO") -> dict[str, object]:
    payload = _app_mention_payload(channel_id)
    payload["event_id"] = "Ev_test_app_mention_auto_follow_up_1"
    event = dict(payload["event"])
    event["text"] = "<@U_BOT> where is this located and what is the best use case"
    event["ts"] = "1715860000.000250"
    event["thread_ts"] = "1715860000.000100"
    payload["event"] = event
    return payload


def _force_agent_app_mention_payload(channel_id: str = "C_CRE_LISTINGS_DEMO") -> dict[str, object]:
    payload = _app_mention_payload(channel_id)
    payload["event_id"] = "Ev_test_app_mention_force_agent_1"
    event = dict(payload["event"])
    event["text"] = "<@U_BOT> /force-agent where is this located and what is the best use case"
    event["ts"] = "1715860000.000300"
    event["thread_ts"] = "1715860000.000100"
    payload["event"] = event
    return payload


class FakeSlackHistoryClient:
    async def auth_test(self) -> dict[str, str]:
        return {"team_id": "T_CRE_DEMO"}

    async def conversations_info(self, *, channel: str) -> dict[str, object]:
        assert channel == "C_CRE_LISTINGS_DEMO"
        return {"channel": {"name": "cre-listings"}}

    async def conversations_history(self, *, channel: str, limit: int, cursor: str | None = None) -> dict[str, object]:
        assert channel == "C_CRE_LISTINGS_DEMO"
        assert limit == 5
        assert cursor is None
        return {"messages": []}


def _message_payload(channel_id: str = "C_CRE_LISTINGS_DEMO") -> dict[str, object]:
    return {
        "token": "ignored",
        "team_id": "T_CRE_DEMO",
        "api_app_id": "A_CRE_DEMO",
        "event": {
            "type": "message",
            "channel": channel_id,
            "user": "U_REQUESTOR",
            "text": "ordinary channel chatter",
            "ts": "1715860001.000100",
        },
        "type": "event_callback",
        "event_id": "Ev_test_message_1",
        "event_time": 1715860001,
        "authorizations": [{"team_id": "T_CRE_DEMO"}],
    }


def test_backfill_slack_channel_history_resolves_channel_name() -> None:
    payload = asyncio.run(
        backfill_slack_channel_history(
            FakeSlackHistoryClient(),
            channel_id="C_CRE_LISTINGS_DEMO",
            recent_limit=5,
        )
    )

    assert payload["status"] == "synced"
    assert payload["channel_id"] == "C_CRE_LISTINGS_DEMO"
    assert payload["channel_name"] == "cre-listings"
    assert payload["seen_message_count"] == 0


def _listing_message_payload(channel_id: str = "C_CRE_LISTINGS_DEMO") -> dict[str, object]:
    payload = _message_payload(channel_id=channel_id)
    payload["event_id"] = "Ev_test_message_listing_1"
    payload["event"]["text"] = "New availability: 321 Test Rd industrial 20,000 SF at $22/SF, available immediate in Midtown."
    payload["event"]["ts"] = "1715860002.000100"
    return payload


def _address_only_message_payload(channel_id: str = "C_CRE_LISTINGS_DEMO") -> dict[str, object]:
    payload = _message_payload(channel_id=channel_id)
    payload["event_id"] = "Ev_test_message_address_only_1"
    payload["event"]["text"] = "Can someone check 123 Main Street?"
    payload["event"]["ts"] = "1715860003.000100"
    return payload


def _unsupported_file_share_message_payload(channel_id: str = "C_CRE_LISTINGS_DEMO") -> dict[str, object]:
    payload = _message_payload(channel_id=channel_id)
    payload["event_id"] = "Ev_test_message_unsupported_file_1"
    payload["event"]["subtype"] = "file_share"
    payload["event"]["text"] = "FYI"
    payload["event"]["ts"] = "1715860004.000100"
    payload["event"]["files"] = [
        {
            "id": "F_TEST_VIDEO_1",
            "name": "walkthrough.mp4",
            "mimetype": "video/mp4",
        }
    ]
    return payload


def _query_like_cre_message_payload(channel_id: str = "C_CRE_LISTINGS_DEMO") -> dict[str, object]:
    payload = _message_payload(channel_id=channel_id)
    payload["event_id"] = "Ev_test_message_query_like_1"
    payload["event"]["text"] = "<@U_BOT> Show office buildings under $50/sq ft."
    payload["event"]["ts"] = "1715860005.000100"
    return payload


def _interactivity_payload(query_id: str) -> dict[str, object]:
    return {
        "type": "block_actions",
        "user": {"id": "U_REQUESTOR"},
        "channel": {"id": "C_CRE_LISTINGS_DEMO"},
        "team": {"id": "T_CRE_DEMO"},
        "container": {"message_ts": "1715860000.000100", "thread_ts": "1715860000.000100"},
        "actions": [{"action_id": "show_sources", "value": query_id}],
    }


def _look_deeper_payload(query_id: str) -> dict[str, object]:
    payload = _interactivity_payload(query_id)
    payload["actions"] = [{"action_id": "look_deeper", "value": query_id}]
    return payload


def _force_agent_action_payload(query_id: str) -> dict[str, object]:
    payload = _interactivity_payload(query_id)
    payload["actions"] = [{"action_id": "force_agent_query", "value": query_id}]
    return payload


def _follow_up_action_payload(query_id: str) -> dict[str, object]:
    payload = _interactivity_payload(query_id)
    payload["trigger_id"] = "13345224609.738474920.followup-trigger"
    payload["actions"] = [{"action_id": "open_follow_up_modal", "value": query_id}]
    return payload


def _follow_up_modal_submission_payload(
    private_metadata: str,
    *,
    query_text: str = "Look deeper on location and use case",
    mode: str = "auto",
    suggestion_id: str | None = None,
) -> dict[str, object]:
    metadata = json.loads(private_metadata or "{}")
    metadata["mode"] = mode
    choice_value = suggestion_id or "custom"
    values: dict[str, object] = {
        "follow_up_mode_block": {
            "follow_up_mode": {
                "type": "radio_buttons",
                "selected_option": {"text": {"type": "plain_text", "text": mode.title()}, "value": mode},
            }
        },
        "follow_up_question_block": {
            "follow_up_question": {"type": "plain_text_input", "value": query_text}
        },
        "follow_up_suggestion_block": {
            "follow_up_suggestion": {
                "type": "radio_buttons",
                "selected_option": {"text": {"type": "plain_text", "text": "Suggested" if suggestion_id else "Custom question"}, "value": choice_value},
            }
        },
    }
    return {
        "type": "view_submission",
        "team": {"id": "T_CRE_DEMO"},
        "user": {"id": "U_REQUESTOR"},
        "view": {
            "type": "modal",
            "callback_id": "follow_up_agent_modal",
            "private_metadata": json.dumps(metadata, sort_keys=True),
            "state": {"values": values},
        },
    }


def _follow_up_refresh_action_payload(view: dict[str, object], mode: str = "auto") -> dict[str, object]:
    view = dict(view)
    view["state"] = {
        "values": {
            "follow_up_mode_block": {
                "follow_up_mode": {
                    "type": "radio_buttons",
                    "selected_option": {"text": {"type": "plain_text", "text": mode.title()}, "value": mode},
                }
            }
        }
    }
    return {
        "type": "block_actions",
        "user": {"id": "U_REQUESTOR"},
        "channel": {"id": "C_CRE_LISTINGS_DEMO"},
        "team": {"id": "T_CRE_DEMO"},
        "view": view,
        "actions": [{"action_id": FOLLOW_UP_MODAL_REFRESH_ACTION_ID, "value": "refresh"}],
    }


def _force_agent_command_body(query_text: str = "where is this located and what is the best use case") -> str:
    return urlencode(
        {
            "token": "ignored",
            "team_id": "T_CRE_DEMO",
            "team_domain": "cre-demo",
            "channel_id": "C_CRE_LISTINGS_DEMO",
            "channel_name": "cre-listings",
            "user_id": "U_REQUESTOR",
            "user_name": "aadityasoni2020",
            "command": "/force-agent",
            "text": query_text,
            "api_app_id": "A_CRE_DEMO",
            "trigger_id": "13345224609.738474920.8088930838d88f008e0",
            "response_url": "https://example.com/response",
        }
    )


def _message_shortcut_payload(
    message_text: str = "where is this located and what is the best use case",
    *,
    message_ts: str = "1715860000.000350",
    thread_ts: str = "1715860000.000100",
) -> dict[str, object]:
    return {
        "type": "message_action",
        "callback_id": "follow_up_agent_message_shortcut",
        "trigger_id": "13345224609.738474920.8088930838d88f008e1",
        "team": {"id": "T_CRE_DEMO"},
        "user": {"id": "U_REQUESTOR"},
        "channel": {"id": "C_CRE_LISTINGS_DEMO"},
        "message": {
            "type": "message",
            "user": "U_REQUESTOR",
            "text": message_text,
            "ts": message_ts,
            "thread_ts": thread_ts,
        },
        "response_url": "https://example.com/response",
    }


def _find_actions_block(blocks: list[dict[str, object]]) -> dict[str, object]:
    for block in blocks:
        if block.get("type") == "actions":
            return block
    raise AssertionError("actions block not found")


def _find_modal_block(view: dict[str, object], block_id: str) -> dict[str, object]:
    for block in view.get("blocks") or []:
        if isinstance(block, dict) and block.get("block_id") == block_id:
            return block
    raise AssertionError(f"modal block not found: {block_id}")


@pytest.mark.golden
def test_app_mention_enqueues_and_dedupes_retry(prepared_slack_db: None, async_runner: asyncio.Runner) -> None:
    payload = _app_mention_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}

    response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))
    assert response.status_code == 200

    retry_headers = {
        **headers,
        "x-slack-retry-num": "1",
        "x-slack-retry-reason": "http_timeout",
    }
    retry_response = async_runner.run(_post_request("/slack/events", content=body, headers=retry_headers))
    assert retry_response.status_code == 200

    counts = async_runner.run(_counts())
    assert counts["slack_events"] == 1
    assert counts["query_jobs"] == 1
    assert counts["queries"] == 0


@pytest.mark.golden
def test_app_mention_ignores_unconfigured_channel(prepared_slack_db: None, async_runner: asyncio.Runner) -> None:
    payload = _app_mention_payload(channel_id="C_OTHER")
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}

    response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))
    assert response.status_code == 200

    counts = async_runner.run(_counts())
    assert counts["slack_events"] == 1
    assert counts["query_jobs"] == 0


@pytest.mark.golden
def test_force_agent_app_mention_queues_direct_agent_job(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = _force_agent_app_mention_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}

    response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))
    assert response.status_code == 200

    counts = async_runner.run(_counts())
    assert counts["query_jobs"] == 0
    job = async_runner.run(_load_latest_job("force_agent"))
    assert job is not None
    assert job.checkpoint_json["query_text"] == "where is this located and what is the best use case"
    assert job.checkpoint_json["original_query_text"].startswith("/force-agent")
    assert job.checkpoint_json["thread_ts"] == "1715860000.000100"


@pytest.mark.golden
def test_force_agent_slash_command_queues_job_and_posts_ephemeral(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.slack import runtime as slack_runtime

    fake_gateway = RecordingSlackGateway()
    monkeypatch.setattr(slack_runtime, "get_slack_gateway", lambda: fake_gateway)
    get_slack_app.cache_clear()
    get_slack_handler.cache_clear()

    body = _force_agent_command_body()
    headers = {"content-type": "application/x-www-form-urlencoded", **_signed_headers("test-signing-secret", body)}

    response = async_runner.run(_post_request("/slack/commands", content=body, headers=headers))
    assert response.status_code == 200
    assert fake_gateway.ephemeral_replies
    assert fake_gateway.ephemeral_replies[-1]["text"] == "On it. Force-agent mode is going straight to Toolhouse with backend MCP checks."

    job = async_runner.run(_load_latest_job("force_agent"))
    assert job is not None
    assert job.checkpoint_json["event_type"] == "slash_command"
    assert job.checkpoint_json["thread_ts"] == ""
    assert job.checkpoint_json["query_text"] == "where is this located and what is the best use case"


@pytest.mark.golden
def test_generic_message_event_is_ignored_as_noise(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = _message_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}

    response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))

    assert response.status_code == 200
    counts = async_runner.run(_counts())
    assert counts["query_jobs"] == 0
    assert counts["queued_ingest_jobs"] == 0
    source, chunks = async_runner.run(_load_source_for_slack_ts("1715860001.000100"))
    assert source is None
    assert chunks == []


@pytest.mark.golden
def test_live_message_ingestion_extracts_structured_property_record(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = _listing_message_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}

    response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))

    assert response.status_code == 200
    processed = async_runner.run(process_pending_query_jobs(limit=1))

    assert len(processed) == 1
    properties = async_runner.run(_load_properties_for_slack_ts("1715860002.000100"))
    assert len(properties) == 1
    assert properties[0].address == "321 Test Rd"
    assert properties[0].property_type == "industrial"
    assert properties[0].sq_ft == 20000
    assert str(properties[0].price_per_sq_ft) == "22.00"
    assert properties[0].extraction_method == "heuristic_live_text"


@pytest.mark.golden
def test_live_message_ingestion_does_not_extract_address_only_chatter(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = _address_only_message_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}

    response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))

    assert response.status_code == 200
    counts = async_runner.run(_counts())
    assert counts["queued_ingest_jobs"] == 0
    source, chunks = async_runner.run(_load_source_for_slack_ts("1715860003.000100"))
    assert source is None
    assert chunks == []
    properties = async_runner.run(_load_properties_for_slack_ts("1715860003.000100"))
    assert properties == []


@pytest.mark.golden
def test_unsupported_file_share_message_is_ignored(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = _unsupported_file_share_message_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}

    response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))

    assert response.status_code == 200
    counts = async_runner.run(_counts())
    assert counts["queued_ingest_jobs"] == 0
    source, chunks = async_runner.run(_load_source_for_slack_ts("1715860004.000100"))
    assert source is None
    assert chunks == []


@pytest.mark.golden
def test_query_like_cre_message_is_ignored_for_ingestion(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = _query_like_cre_message_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}

    response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))

    assert response.status_code == 200
    counts = async_runner.run(_counts())
    assert counts["queued_ingest_jobs"] == 0
    source, chunks = async_runner.run(_load_source_for_slack_ts("1715860005.000100"))
    assert source is None
    assert chunks == []


@pytest.mark.golden
def test_files_only_channel_policy_skips_listing_messages(
    prepared_slack_db_files_only: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = _listing_message_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}

    response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))

    assert response.status_code == 200
    counts = async_runner.run(_counts())
    assert counts["queued_ingest_jobs"] == 0
    source, chunks = async_runner.run(_load_source_for_slack_ts("1715860002.000100"))
    assert source is None
    assert chunks == []


def test_build_slack_reply_text_normalizes_agent_markdown() -> None:
    formatted = build_slack_reply_text(
        {
            "answer_mode": "agent_mode",
            "dependency_state": {"toolhouse": True},
            "rendered_answer": "*Deeper read*\n• **240 Harbor Rd** at **$18.00/SF**\n• **88 Foundry Ln** at **$21.50/SF**",
        }
    )

    assert formatted.startswith("_Mode: Agent mode - Toolhouse-backed deeper review_")
    assert "**" not in formatted
    assert "•" not in formatted
    assert "- *240 Harbor Rd* at *$18.00/SF*" in formatted


def test_build_answer_blocks_adds_compact_trust_receipt_and_table() -> None:
    blocks = build_answer_blocks(
        {
            "answer_mode": "instant_answer",
            "route_mode": "instant",
            "reason_codes": ["structured_property_search"],
            "evidence_count": 3,
            "query_id": "query-1",
            "rendered_answer": "*Found 3 matching sourced listing(s)*",
            "comparison_table": {
                "title": "Quick comparison",
                "columns": ["Addr", "SF", "Rent", "Avail"],
                "rows": [
                    ["240 Harbor Rd", "62,000 SF", "$18.00/SF", "Aug 2026"],
                    ["88 Foundry Ln", "44,000 SF", "$21.50/SF", "Q2 2026"],
                ],
            },
        }
    )

    assert blocks[0]["type"] == "section"
    assert len([block for block in blocks if block["type"] == "section"]) == 1
    assert all("Quick comparison" not in json.dumps(block) for block in blocks)
    assert blocks[1]["type"] == "context"
    assert "Instant answer" in blocks[1]["elements"][0]["text"]
    assert blocks[2]["type"] == "actions"
    assert [element["action_id"] for element in blocks[2]["elements"]] == [
        "show_sources",
        "look_deeper",
        "open_follow_up_modal",
    ]

    attachment = build_comparison_table_csv_attachment(
        {
            "query_id": "query-1",
            "comparison_table": {
                "title": "Quick comparison",
                "columns": ["Addr", "SF", "Rent", "Avail"],
                "rows": [
                    ["240 Harbor Rd", "62,000 SF", "$18.00/SF", "Aug 2026"],
                    ["88 Foundry Ln", "44,000 SF", "$21.50/SF", "Q2 2026"],
                ],
            },
        }
    )
    assert attachment is not None
    assert attachment["filename"].endswith(".csv")
    assert "Addr,SF,Rent,Avail" in attachment["content"]
    reader = csv.reader(io.StringIO(attachment["content"]))
    rows = list(reader)
    assert rows[1] == ["240 Harbor Rd", "62,000 SF", "$18.00/SF", "Aug 2026"]


def test_build_answer_blocks_splits_long_answer_for_slack_section_limit() -> None:
    long_answer = "\n".join(f"- *Property {index}* - sourced inventory detail with market and pricing." for index in range(120))

    blocks = build_answer_blocks(
        {
            "answer_mode": "instant_answer",
            "route_mode": "instant",
            "reason_codes": ["broad_inventory"],
            "evidence_count": 10,
            "query_id": "query-1",
            "rendered_answer": long_answer,
        }
    )

    answer_sections = [block for block in blocks if block["type"] == "section" and "Property" in block["text"]["text"]]
    assert len(answer_sections) > 1
    assert all(len(block["text"]["text"]) <= 3000 for block in answer_sections)
    assert any(block["type"] == "actions" for block in blocks)


@pytest.mark.golden
def test_query_worker_posts_threaded_answer_with_show_sources_button(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = _app_mention_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}

    response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))
    assert response.status_code == 200

    gateway = RecordingSlackGateway()
    processed = async_runner.run(process_pending_query_jobs(slack_gateway=gateway, limit=1))

    assert len(processed) == 1
    assert gateway.thread_replies
    assert len(gateway.thread_replies) == 1
    assert gateway.updated_messages
    posted_reply = gateway.thread_replies[0]
    assert posted_reply["channel_id"] == "C_CRE_LISTINGS_DEMO"
    assert posted_reply["thread_ts"] == "1715860000.000100"
    assert posted_reply["text"].startswith("_Mode: Instant answer - structured backend retrieval_")
    assert "120 Main St" in posted_reply["text"]
    assert processed[0]["pending_message_ts"] == posted_reply["ts"]
    assert any(block.get("type") == "context" for block in posted_reply["blocks"])
    assert not any("Quick comparison" in json.dumps(block) for block in posted_reply["blocks"])
    assert gateway.uploaded_files
    assert gateway.uploaded_files[0]["thread_ts"] == "1715860000.000100"
    assert gateway.uploaded_files[0]["filename"].endswith(".csv")
    assert "Addr,SF,Rent,Avail" in gateway.uploaded_files[0]["content"]
    actions_block = _find_actions_block(posted_reply["blocks"])
    action_element = actions_block["elements"][0]
    assert action_element["action_id"] == "show_sources"
    assert UUID(action_element["value"])
    assert actions_block["elements"][1]["action_id"] == "look_deeper"
    assert actions_block["elements"][2]["action_id"] == "open_follow_up_modal"

    latest_query = async_runner.run(_load_latest_query())
    assert latest_query is not None
    assert latest_query.slack_channel_id == "C_CRE_LISTINGS_DEMO"
    assert latest_query.slack_user_id == "U_REQUESTOR"
    assert latest_query.slack_ts == "1715860000.000100"


@pytest.mark.golden
def test_auto_follow_up_reuses_sufficient_thread_evidence(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = _app_mention_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}

    response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))
    assert response.status_code == 200

    gateway = RecordingSlackGateway()
    async_runner.run(process_pending_query_jobs(slack_gateway=gateway, limit=1))
    parent_query_id = _find_actions_block(gateway.thread_replies[0]["blocks"])["elements"][0]["value"]

    session_before = async_runner.run(_load_thread_session("C_CRE_LISTINGS_DEMO", "1715860000.000100"))
    assert session_before is not None
    assert session_before.accumulated_evidence_ids_json

    async_runner.run(
        enqueue_follow_up_request(
            query_text="where is it located",
            mode="auto",
            parent_query_id=parent_query_id,
            channel_id="C_CRE_LISTINGS_DEMO",
            user_id="U_REQUESTOR",
            team_id="T_CRE_DEMO",
            thread_ts="1715860000.000100",
        )
    )
    processed = async_runner.run(process_pending_query_jobs(slack_gateway=gateway, limit=1))

    assert processed[0]["job_type"] == "follow_up"
    assert processed[0]["route_mode"] == "instant"
    assert processed[0]["follow_up"]["resolution"] == "sufficient"
    explain_payload = async_runner.run(explain_query(str(processed[0]["query_id"])))
    assert explain_payload["reason_codes"] == ["follow_up", "thread_evidence_reuse", "coverage_sufficient"]

    session_after = async_runner.run(_load_thread_session("C_CRE_LISTINGS_DEMO", "1715860000.000100"))
    assert session_after is not None
    assert len(session_after.query_history_json) >= 2


@pytest.mark.golden
def test_zero_evidence_slack_answer_offers_look_deeper_only(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = _unsupported_app_mention_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}

    response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))
    assert response.status_code == 200

    gateway = RecordingSlackGateway()
    processed = async_runner.run(process_pending_query_jobs(slack_gateway=gateway, limit=1))

    assert processed[0]["answer_status"] == "unsupported"
    posted_reply = gateway.thread_replies[0]
    actions_block = _find_actions_block(posted_reply["blocks"])
    assert [element["action_id"] for element in actions_block["elements"]] == ["look_deeper", "open_follow_up_modal"]
    assert "Use *Look deeper*" in posted_reply["text"]

    query_id = actions_block["elements"][0]["value"]
    explain_payload = async_runner.run(explain_query(query_id))
    assert explain_payload["evidence_count"] == 0
    assert explain_payload["slack_context"]["message_ts"] == "1715860000.000200"
    assert explain_payload["slack_context"]["thread_ts"] == "1715860000.000200"


@pytest.mark.golden
def test_auto_thread_follow_up_queues_follow_up_job(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = _auto_thread_follow_up_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}

    response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))
    assert response.status_code == 200

    counts = async_runner.run(_counts())
    assert counts["query_jobs"] == 0
    job = async_runner.run(_load_latest_job("follow_up"))
    assert job is not None
    assert job.checkpoint_json["query_text"] == "where is this located and what is the best use case"
    assert job.checkpoint_json["mode"] == "auto"
    assert job.checkpoint_json["follow_up_source"] == "auto_thread_follow_up"
    assert job.checkpoint_json["follow_up_reason_codes"] == ["auto_thread_follow_up"]


@pytest.mark.golden
def test_auto_thread_follow_up_uses_coverage_router_and_preserves_thread_context(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = _auto_thread_follow_up_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}

    response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))
    assert response.status_code == 200

    gateway = RecordingSlackGateway()
    processed = async_runner.run(process_pending_query_jobs(slack_gateway=gateway, limit=1))

    assert processed[0]["job_type"] == "follow_up"
    assert processed[0]["follow_up"]["mode"] == "auto"
    assert processed[0]["pending_message_ts"] == gateway.thread_replies[0]["ts"]
    assert gateway.thread_replies[0]["thread_ts"] == "1715860000.000100"

    query = async_runner.run(_load_latest_query())
    assert query is not None
    query = async_runner.run(_load_latest_query())
    assert query is not None
    explain_payload = async_runner.run(explain_query(str(query.id)))
    assert "follow_up" in explain_payload["reason_codes"]
    assert explain_payload["slack_context"]["message_ts"] == "1715860000.000250"
    assert explain_payload["slack_context"]["thread_ts"] == "1715860000.000100"


@pytest.mark.golden
def test_force_agent_job_bypasses_instant_router_and_posts_agent_mode(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = _force_agent_app_mention_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}

    response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))
    assert response.status_code == 200

    gateway = RecordingSlackGateway()
    processed = async_runner.run(process_pending_query_jobs(slack_gateway=gateway, limit=1))

    assert processed[0]["job_type"] == "force_agent"
    assert processed[0]["force_agent"] is True
    assert processed[0]["answer_mode"] == "agent_mode"
    assert processed[0]["deeper_review_status"] == "needs_more_evidence"
    assert processed[0]["pending_message_ts"] == gateway.thread_replies[0]["ts"]
    assert gateway.thread_replies[0]["thread_ts"] == "1715860000.000100"
    assert gateway.updated_messages
    assert gateway.thread_replies[0]["text"].startswith("_Mode: Agent mode - local deeper review_")

    query = async_runner.run(_load_latest_query())
    assert query is not None
    assert query.route_mode == "agent_forced"
    assert query.query_text == "where is this located and what is the best use case"


@pytest.mark.golden
def test_force_agent_job_uploads_csv_when_deeper_review_returns_comparison_table(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _force_agent_app_mention_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}

    response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))
    assert response.status_code == 200

    async def fake_run_toolhouse_deeper_review(query_id: str) -> dict[str, object]:
        return {
            "status": "answered",
            "query_id": query_id,
            "answer_mode": "agent_mode",
            "rendered_answer": "*Deeper review*\nBest candidates attached as CSV.",
            "comparison_table": {
                "title": "Quick comparison",
                "columns": ["Addr", "SF", "Rent", "Avail"],
                "rows": [
                    ["240 Harbor Rd", "62,000 SF", "$18.00/SF", "Aug 2026"],
                    ["88 Foundry Ln", "44,000 SF", "$21.50/SF", "Q2 2026"],
                ],
            },
            "validation": {"valid": True},
            "dependency_state": {"toolhouse": True},
            "toolhouse_fallback": False,
            "toolhouse_agent_id": "agent-1",
            "toolhouse_run_id": "run-1",
            "escalation_payload": {"evidence": [{"id": "ev-1"}, {"id": "ev-2"}], "allowed_evidence_ids": ["ev-1", "ev-2"]},
            "cited_evidence_ids": ["ev-1", "ev-2"],
        }

    monkeypatch.setattr("app.workers.query_worker.run_toolhouse_deeper_review", fake_run_toolhouse_deeper_review)

    gateway = RecordingSlackGateway()
    processed = async_runner.run(process_pending_query_jobs(slack_gateway=gateway, limit=1))

    assert processed[0]["job_type"] == "force_agent"
    assert processed[0]["deeper_review_status"] == "answered"
    assert processed[0]["comparison_csv_status"] == "uploaded"
    assert gateway.uploaded_files
    assert gateway.uploaded_files[-1]["thread_ts"] == "1715860000.000100"
    assert gateway.uploaded_files[-1]["filename"].endswith(".csv")
    csv_rows = list(csv.reader(io.StringIO(gateway.uploaded_files[-1]["content"])))
    assert csv_rows[0] == ["Addr", "SF", "Rent", "Avail"]
    assert csv_rows[1] == ["240 Harbor Rd", "62,000 SF", "$18.00/SF", "Aug 2026"]

    query = async_runner.run(_load_latest_query())
    assert query is not None
    explain_payload = async_runner.run(explain_query(str(query.id)))
    assert explain_payload["reason_codes"] == ["force_agent", "instant_router_skipped"]
    assert explain_payload["slack_context"]["message_ts"] == "1715860000.000300"
    assert explain_payload["slack_context"]["thread_ts"] == "1715860000.000100"


@pytest.mark.golden
def test_force_agent_slash_command_posts_channel_update_without_thread(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.slack import runtime as slack_runtime

    fake_gateway = RecordingSlackGateway()
    monkeypatch.setattr(slack_runtime, "get_slack_gateway", lambda: fake_gateway)
    get_slack_app.cache_clear()
    get_slack_handler.cache_clear()

    body = _force_agent_command_body()
    headers = {"content-type": "application/x-www-form-urlencoded", **_signed_headers("test-signing-secret", body)}
    response = async_runner.run(_post_request("/slack/commands", content=body, headers=headers))
    assert response.status_code == 200

    processed = async_runner.run(process_pending_query_jobs(slack_gateway=fake_gateway, limit=1))

    assert processed[0]["job_type"] == "force_agent"
    assert processed[0]["force_agent"] is True
    assert processed[0]["deeper_review_status"] == "needs_more_evidence"
    assert fake_gateway.thread_replies[0]["thread_ts"] == ""
    assert fake_gateway.updated_messages
    assert fake_gateway.thread_replies[0]["text"].startswith("_Mode: Agent mode - local deeper review_")


@pytest.mark.golden
def test_follow_up_message_shortcut_opens_thread_modal(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.slack import runtime as slack_runtime

    fake_gateway = RecordingSlackGateway()
    monkeypatch.setattr(slack_runtime, "get_slack_gateway", lambda: fake_gateway)
    get_slack_app.cache_clear()
    get_slack_handler.cache_clear()

    shortcut_payload = _message_shortcut_payload()
    form_body = urlencode({"payload": json.dumps(shortcut_payload)})
    headers = {"content-type": "application/x-www-form-urlencoded", **_signed_headers("test-signing-secret", form_body)}

    response = async_runner.run(_post_request("/slack/interactivity", content=form_body, headers=headers))
    assert response.status_code == 200
    assert fake_gateway.opened_modals
    opened = fake_gateway.opened_modals[-1]
    assert opened["trigger_id"] == "13345224609.738474920.8088930838d88f008e1"
    view = opened["view"]
    assert view["callback_id"] == "follow_up_agent_modal"
    metadata = json.loads(view["private_metadata"])
    assert metadata["thread_ts"] == "1715860000.000100"
    assert metadata["channel_id"] == "C_CRE_LISTINGS_DEMO"


@pytest.mark.golden
def test_runtime_background_worker_processes_enqueued_job(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers import background as worker_background

    gateway = RecordingSlackGateway()
    monkeypatch.setattr(worker_background, "get_slack_gateway", lambda: gateway)

    payload = _app_mention_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}

    with TestClient(
        create_app(enable_background_worker=True, worker_poll_interval_seconds=0.01, worker_batch_limit=1)
    ) as client:
        response = client.post("/slack/events", content=body, headers=headers)
        assert response.status_code == 200

        deadline = time.monotonic() + 1.0
        while not gateway.updated_messages and time.monotonic() < deadline:
            time.sleep(0.02)

    assert gateway.thread_replies
    assert len(gateway.thread_replies) == 1
    assert gateway.updated_messages
    posted_reply = gateway.thread_replies[0]
    assert posted_reply["channel_id"] == "C_CRE_LISTINGS_DEMO"
    assert posted_reply["thread_ts"] == "1715860000.000100"
    assert posted_reply["text"].startswith("_Mode: Instant answer - structured backend retrieval_")
    assert "120 Main St" in posted_reply["text"]
    assert any(block.get("type") == "context" for block in posted_reply["blocks"])

    async_runner.run(engine.dispose())
    latest_query = async_runner.run(_load_latest_query())
    assert latest_query is not None
    assert latest_query.slack_channel_id == "C_CRE_LISTINGS_DEMO"


@pytest.mark.golden
def test_show_sources_action_posts_ephemeral_evidence_reply(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.slack import runtime as slack_runtime

    fake_gateway = RecordingSlackGateway()
    monkeypatch.setattr(slack_runtime, "get_slack_gateway", lambda: fake_gateway)
    get_slack_app.cache_clear()
    get_slack_handler.cache_clear()

    payload = _app_mention_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}
    enqueue_response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))
    assert enqueue_response.status_code == 200
    async_runner.run(process_pending_query_jobs(slack_gateway=fake_gateway, limit=1))

    query_id = _find_actions_block(fake_gateway.thread_replies[0]["blocks"])["elements"][0]["value"]
    action_payload = _interactivity_payload(query_id)
    form_body = urlencode({"payload": json.dumps(action_payload)})
    action_headers = {
        "content-type": "application/x-www-form-urlencoded",
        **_signed_headers("test-signing-secret", form_body),
    }

    action_response = async_runner.run(
        _post_request("/slack/interactivity", content=form_body, headers=action_headers)
    )
    assert action_response.status_code == 200
    assert fake_gateway.ephemeral_replies
    assert fake_gateway.ephemeral_replies[0]["thread_ts"] == "1715860000.000100"
    assert "Sources for:" in fake_gateway.ephemeral_replies[0]["text"]
    assert "*Supporting*" in fake_gateway.ephemeral_replies[0]["text"]
    assert "main-street-office-flyer.pdf" in fake_gateway.ephemeral_replies[0]["text"]


@pytest.mark.golden
def test_look_deeper_action_enqueues_and_posts_local_deeper_review(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.slack import runtime as slack_runtime

    fake_gateway = RecordingSlackGateway()
    monkeypatch.setattr(slack_runtime, "get_slack_gateway", lambda: fake_gateway)
    get_slack_app.cache_clear()
    get_slack_handler.cache_clear()

    payload = _app_mention_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}
    enqueue_response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))
    assert enqueue_response.status_code == 200
    async_runner.run(process_pending_query_jobs(slack_gateway=fake_gateway, limit=1))

    query_id = _find_actions_block(fake_gateway.thread_replies[0]["blocks"])["elements"][1]["value"]
    action_payload = _look_deeper_payload(query_id)
    form_body = urlencode({"payload": json.dumps(action_payload)})
    action_headers = {
        "content-type": "application/x-www-form-urlencoded",
        **_signed_headers("test-signing-secret", form_body),
    }

    action_response = async_runner.run(
        _post_request("/slack/interactivity", content=form_body, headers=action_headers)
    )
    assert action_response.status_code == 200
    assert fake_gateway.ephemeral_replies[-1]["thread_ts"] == "1715860000.000100"
    assert fake_gateway.ephemeral_replies[-1]["text"] == "On it. Entering agent mode and checking the messy bits."

    processed = async_runner.run(process_pending_query_jobs(slack_gateway=fake_gateway, limit=1))

    assert processed[0]["answer_mode"] == "agent_mode"
    assert processed[0]["deeper_review_status"] == "answered"


@pytest.mark.golden
def test_follow_up_button_opens_modal_and_submission_queues_follow_up(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.slack import runtime as slack_runtime

    fake_gateway = RecordingSlackGateway()
    monkeypatch.setattr(slack_runtime, "get_slack_gateway", lambda: fake_gateway)
    get_slack_app.cache_clear()
    get_slack_handler.cache_clear()

    payload = _app_mention_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}
    enqueue_response = async_runner.run(_post_request("/slack/events", content=body, headers=headers))
    assert enqueue_response.status_code == 200
    async_runner.run(process_pending_query_jobs(slack_gateway=fake_gateway, limit=1))

    query_id = _find_actions_block(fake_gateway.thread_replies[0]["blocks"])["elements"][2]["value"]
    action_payload = _follow_up_action_payload(query_id)
    form_body = urlencode({"payload": json.dumps(action_payload)})
    action_headers = {
        "content-type": "application/x-www-form-urlencoded",
        **_signed_headers("test-signing-secret", form_body),
    }

    action_response = async_runner.run(_post_request("/slack/interactivity", content=form_body, headers=action_headers))
    assert action_response.status_code == 200
    assert fake_gateway.opened_modals
    opened_view = fake_gateway.opened_modals[-1]["view"]
    assert opened_view["callback_id"] == "follow_up_agent_modal"
    metadata = json.loads(opened_view["private_metadata"])
    assert metadata["parent_query_id"] == query_id
    assert metadata["thread_ts"] == "1715860000.000100"

    submit_payload = _follow_up_modal_submission_payload(opened_view["private_metadata"], mode="agent")
    submit_form_body = urlencode({"payload": json.dumps(submit_payload)})
    submit_headers = {
        "content-type": "application/x-www-form-urlencoded",
        **_signed_headers("test-signing-secret", submit_form_body),
    }
    submit_response = async_runner.run(_post_request("/slack/interactivity", content=submit_form_body, headers=submit_headers))
    assert submit_response.status_code == 200
    assert fake_gateway.ephemeral_replies[-1]["thread_ts"] == "1715860000.000100"
    assert fake_gateway.ephemeral_replies[-1]["text"] == "On it. Follow-up queued in Agent mode."

    job = async_runner.run(_load_latest_job("follow_up"))
    assert job is not None
    assert job.checkpoint_json["query_text"] == "Look deeper on location and use case"
    assert job.checkpoint_json["mode"] == "agent"
    assert job.checkpoint_json["parent_query_id"] == query_id
    assert job.checkpoint_json["thread_ts"] == "1715860000.000100"
    assert job.checkpoint_json["event_type"] == "follow_up_modal"

    processed = async_runner.run(process_pending_query_jobs(slack_gateway=fake_gateway, limit=1))
    assert processed[0]["pending_message_ts"] == fake_gateway.thread_replies[-1]["ts"]
    assert processed[0]["job_type"] == "follow_up"
    assert processed[0]["follow_up"]["mode"] == "agent"
    assert processed[0]["validation"]["valid"] is True
    assert fake_gateway.updated_messages
    assert any(block.get("type") == "context" for block in fake_gateway.thread_replies[-1]["blocks"])
    assert fake_gateway.thread_replies[-1]["text"].startswith("_Mode: Agent mode - local deeper review_")
    assert "Deeper review" in fake_gateway.thread_replies[-1]["text"]


@pytest.mark.golden
def test_follow_up_modal_opens_with_generate_suggestions_when_cache_empty(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.slack import runtime as slack_runtime
    from app.answering import follow_up_suggestions as suggestions_module

    fake_gateway = RecordingSlackGateway()
    monkeypatch.setattr(slack_runtime, "get_slack_gateway", lambda: fake_gateway)
    generation_calls: list[dict[str, object]] = []

    async def unexpected_generation(context: dict[str, object]) -> list[dict[str, object]]:
        generation_calls.append(context)
        return []

    monkeypatch.setattr(suggestions_module, "_toolhouse_candidate_questions", unexpected_generation)
    get_slack_app.cache_clear()
    get_slack_handler.cache_clear()

    payload = _app_mention_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}
    assert async_runner.run(_post_request("/slack/events", content=body, headers=headers)).status_code == 200
    async_runner.run(process_pending_query_jobs(slack_gateway=fake_gateway, limit=1))

    query_id = _find_actions_block(fake_gateway.thread_replies[0]["blocks"])["elements"][2]["value"]
    action_payload = _follow_up_action_payload(query_id)
    form_body = urlencode({"payload": json.dumps(action_payload)})
    action_headers = {"content-type": "application/x-www-form-urlencoded", **_signed_headers("test-signing-secret", form_body)}

    response = async_runner.run(_post_request("/slack/interactivity", content=form_body, headers=action_headers))

    assert response.status_code == 200
    assert fake_gateway.opened_modals
    assert not fake_gateway.updated_modals
    assert generation_calls == []
    opened_view = fake_gateway.opened_modals[-1]["view"]
    mode_block = _find_modal_block(opened_view, "follow_up_mode_block")
    assert mode_block["element"]["type"] == "radio_buttons"
    assert mode_block["element"]["action_id"] == "follow_up_mode"
    assert mode_block["element"]["initial_option"]["value"] == "auto"
    assert [option["value"] for option in mode_block["element"]["options"]] == ["instant", "auto", "agent"]
    assert _find_modal_block(opened_view, "follow_up_suggestions_empty_block")
    suggestion_block = _find_modal_block(opened_view, "follow_up_suggestion_block")
    options = suggestion_block["element"]["options"]
    assert len(options) == 1
    assert options[0]["value"] == "custom"
    refresh_block = _find_modal_block(opened_view, "follow_up_refresh_block")
    assert refresh_block["elements"][0]["action_id"] == FOLLOW_UP_MODAL_REFRESH_ACTION_ID
    assert refresh_block["elements"][0]["text"]["text"] == "Generate suggestions"
    assert refresh_block["elements"][0]["value"] == "generate"

    thread_session = async_runner.run(_load_thread_session("C_CRE_LISTINGS_DEMO", "1715860000.000100"))
    assert thread_session is not None
    assert "follow_up_suggestions" not in thread_session.session_context_json


@pytest.mark.golden
def test_follow_up_generate_button_preserves_mode_and_generates_suggestions(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.slack import runtime as slack_runtime
    from app.answering import follow_up_suggestions as suggestions_module

    fake_gateway = RecordingSlackGateway()
    monkeypatch.setattr(slack_runtime, "get_slack_gateway", lambda: fake_gateway)
    generation_calls: list[dict[str, object]] = []

    async def generated_candidates(context: dict[str, object]) -> list[dict[str, object]]:
        generation_calls.append(context)
        return [{"kind": "price_spread", "question": "What's the rent spread for the current set?"}]

    monkeypatch.setattr(suggestions_module, "_toolhouse_candidate_questions", generated_candidates)
    get_slack_app.cache_clear()
    get_slack_handler.cache_clear()

    payload = _app_mention_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}
    assert async_runner.run(_post_request("/slack/events", content=body, headers=headers)).status_code == 200
    async_runner.run(process_pending_query_jobs(slack_gateway=fake_gateway, limit=1))

    query_id = _find_actions_block(fake_gateway.thread_replies[0]["blocks"])["elements"][2]["value"]
    action_payload = _follow_up_action_payload(query_id)
    form_body = urlencode({"payload": json.dumps(action_payload)})
    action_headers = {"content-type": "application/x-www-form-urlencoded", **_signed_headers("test-signing-secret", form_body)}
    assert async_runner.run(_post_request("/slack/interactivity", content=form_body, headers=action_headers)).status_code == 200
    assert generation_calls == []

    opened_view = fake_gateway.opened_modals[-1]["view"]
    generate_block = _find_modal_block(opened_view, "follow_up_refresh_block")
    assert generate_block["elements"][0]["text"]["text"] == "Generate suggestions"
    mode_payload = _follow_up_refresh_action_payload(opened_view, "agent")
    mode_body = urlencode({"payload": json.dumps(mode_payload)})
    mode_headers = {"content-type": "application/x-www-form-urlencoded", **_signed_headers("test-signing-secret", mode_body)}

    response = async_runner.run(_post_request("/slack/interactivity", content=mode_body, headers=mode_headers))

    assert response.status_code == 200
    assert len(generation_calls) == 1
    assert fake_gateway.updated_modals[0]["view"]["blocks"][1]["block_id"] == "follow_up_suggestions_loading_block"
    toggled_view = fake_gateway.updated_modals[-1]["view"]
    metadata = json.loads(toggled_view["private_metadata"])
    assert metadata["mode"] == "agent"
    assert metadata["has_follow_up_suggestions"] is True
    mode_block = _find_modal_block(toggled_view, "follow_up_mode_block")
    assert mode_block["element"]["initial_option"]["value"] == "agent"
    suggestion_block = _find_modal_block(toggled_view, "follow_up_suggestion_block")
    assert len(suggestion_block["element"]["options"]) == 6
    assert suggestion_block["element"]["options"][0]["text"]["text"] == "What's the rent spread for the current set?"
    refresh_block = _find_modal_block(toggled_view, "follow_up_refresh_block")
    assert refresh_block["elements"][0]["text"]["text"] == "Refresh suggestions"

    thread_session = async_runner.run(_load_thread_session("C_CRE_LISTINGS_DEMO", "1715860000.000100"))
    assert thread_session is not None
    stored = thread_session.session_context_json["follow_up_suggestions"]["suggestions"]
    price_spread = [suggestion for suggestion in stored if suggestion["kind"] == "price_spread"]
    assert price_spread[0]["source"] == "toolhouse_refresh"
    assert price_spread[0]["validation"]["raw_sql_execution"] is False


@pytest.mark.golden
def test_toolhouse_answer_suggestions_are_cached_for_next_modal(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.slack import runtime as slack_runtime

    fake_gateway = RecordingSlackGateway()
    monkeypatch.setattr(slack_runtime, "get_slack_gateway", lambda: fake_gateway)
    get_slack_app.cache_clear()
    get_slack_handler.cache_clear()

    payload = _app_mention_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}
    assert async_runner.run(_post_request("/slack/events", content=body, headers=headers)).status_code == 200
    async_runner.run(process_pending_query_jobs(slack_gateway=fake_gateway, limit=1))

    query_id = _find_actions_block(fake_gateway.thread_replies[0]["blocks"])["elements"][2]["value"]
    thread_session = async_runner.run(_load_thread_session("C_CRE_LISTINGS_DEMO", "1715860000.000100"))
    assert thread_session is not None
    evidence_ids = [str(value) for value in thread_session.accumulated_evidence_ids_json]
    async_runner.run(
        store_agent_follow_up_suggestions(
            response_payload={"suggested_followups": [{"kind": "price_spread", "question": "What's the rent spread for the current set?"}]},
            query_id=query_id,
            slack_channel_id="C_CRE_LISTINGS_DEMO",
            slack_thread_ts="1715860000.000100",
            parent_query_id=query_id,
            evidence_ids=evidence_ids,
            toolhouse_run_id="run-cached-suggestions",
        )
    )

    action_payload = _follow_up_action_payload(query_id)
    form_body = urlencode({"payload": json.dumps(action_payload)})
    action_headers = {"content-type": "application/x-www-form-urlencoded", **_signed_headers("test-signing-secret", form_body)}

    response = async_runner.run(_post_request("/slack/interactivity", content=form_body, headers=action_headers))

    assert response.status_code == 200
    opened_view = fake_gateway.opened_modals[-1]["view"]
    suggestion_block = _find_modal_block(opened_view, "follow_up_suggestion_block")
    options = suggestion_block["element"]["options"]
    assert options[0]["text"]["text"] == "What's the rent spread for the current set?"
    assert options[0]["description"]["text"] == "Instant, prevalidated SQL"
    refresh_block = _find_modal_block(opened_view, "follow_up_refresh_block")
    assert refresh_block["elements"][0]["text"]["text"] == "Refresh suggestions"


def test_follow_up_modal_validation_rejects_custom_text_with_suggestion() -> None:
    private_metadata = json.dumps({"channel_id": "C_CRE_LISTINGS_DEMO", "thread_ts": "1715860000.000100"})
    payload = _follow_up_modal_submission_payload(
        private_metadata,
        query_text="Use my wording instead",
        mode="auto",
        suggestion_id="suggestion-1",
    )

    errors = validate_follow_up_modal_submission(payload["view"])

    assert errors == {"follow_up_question_block": "Clear this field or select Custom question."}


@pytest.mark.golden
def test_selected_suggested_follow_up_runs_instant_prevalidated_template(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.slack import runtime as slack_runtime

    fake_gateway = RecordingSlackGateway()
    monkeypatch.setattr(slack_runtime, "get_slack_gateway", lambda: fake_gateway)
    get_slack_app.cache_clear()
    get_slack_handler.cache_clear()

    payload = _app_mention_payload()
    body = json.dumps(payload)
    headers = {"content-type": "application/json", **_signed_headers("test-signing-secret", body)}
    assert async_runner.run(_post_request("/slack/events", content=body, headers=headers)).status_code == 200
    async_runner.run(process_pending_query_jobs(slack_gateway=fake_gateway, limit=1))

    query_id = _find_actions_block(fake_gateway.thread_replies[0]["blocks"])["elements"][2]["value"]
    action_payload = _follow_up_action_payload(query_id)
    form_body = urlencode({"payload": json.dumps(action_payload)})
    action_headers = {"content-type": "application/x-www-form-urlencoded", **_signed_headers("test-signing-secret", form_body)}
    assert async_runner.run(_post_request("/slack/interactivity", content=form_body, headers=action_headers)).status_code == 200

    opened_view = fake_gateway.opened_modals[-1]["view"]
    generate_payload = _follow_up_refresh_action_payload(opened_view, "auto")
    generate_body = urlencode({"payload": json.dumps(generate_payload)})
    generate_headers = {"content-type": "application/x-www-form-urlencoded", **_signed_headers("test-signing-secret", generate_body)}
    assert async_runner.run(_post_request("/slack/interactivity", content=generate_body, headers=generate_headers)).status_code == 200

    updated_view = fake_gateway.updated_modals[-1]["view"]
    suggestion_block = _find_modal_block(updated_view, "follow_up_suggestion_block")
    suggestion_id = suggestion_block["element"]["options"][0]["value"]
    submit_payload = _follow_up_modal_submission_payload(
        updated_view["private_metadata"],
        query_text="",
        mode="agent",
        suggestion_id=suggestion_id,
    )
    submit_body = urlencode({"payload": json.dumps(submit_payload)})
    submit_headers = {"content-type": "application/x-www-form-urlencoded", **_signed_headers("test-signing-secret", submit_body)}

    submit_response = async_runner.run(_post_request("/slack/interactivity", content=submit_body, headers=submit_headers))
    assert submit_response.status_code == 200
    assert fake_gateway.ephemeral_replies[-1]["text"] == "On it. Suggested follow-up queued in Instant mode."

    job = async_runner.run(_load_latest_job("follow_up"))
    assert job is not None
    assert job.checkpoint_json["mode"] == "instant"
    assert job.checkpoint_json["event_type"] == "follow_up_suggestion"
    assert job.checkpoint_json["suggested_follow_up"]["kind"] == "average_rent"

    processed = async_runner.run(process_pending_query_jobs(slack_gateway=fake_gateway, limit=1))
    assert processed[0]["job_type"] == "follow_up"
    assert processed[0]["answer_mode"] == "instant_answer"
    assert processed[0]["route_mode"] == "instant"
    assert processed[0]["follow_up"]["resolution"] == "suggested_prevalidated_sql"
    assert "Average rent" in fake_gateway.thread_replies[-1]["text"]

    explain_payload = async_runner.run(explain_query(str(processed[0]["query_id"])))
    assert "prevalidated_sql" in explain_payload["reason_codes"]
    thread_session = async_runner.run(_load_thread_session("C_CRE_LISTINGS_DEMO", "1715860000.000100"))
    assert thread_session is not None
    stored_suggestions = thread_session.session_context_json["follow_up_suggestions"]["suggestions"]
    answered = [suggestion for suggestion in stored_suggestions if suggestion["id"] == suggestion_id]
    assert answered[0]["status"] == "answered"


@pytest.mark.golden
def test_dependency_health_reports_slack_and_toolhouse_state(
    prepared_slack_db: None,
    async_runner: asyncio.Runner,
) -> None:
    response = async_runner.run(_get_request("/health/deps"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["checks"]["slack"] == "configured"
    assert payload["checks"]["toolhouse"] == "missing_config"