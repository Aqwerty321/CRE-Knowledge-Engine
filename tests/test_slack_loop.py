from __future__ import annotations

import asyncio
import hashlib
import hmac
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

from app.answering.query_service import explain_query
from app.config import get_settings
from app.db.session import SessionFactory, engine
from app.ingestion.sample_importer import import_sample_data
from app.ingestion.slack_ingestor import backfill_slack_channel_history
from app.main import create_app
from app.models import AnswerSnapshot, Chunk, EvidenceItem, IngestionJob, PropertyRecord, Query, SlackEvent, SourceDocument
from app.slack.gateway import RecordingSlackGateway
from app.slack.runtime import get_slack_app, get_slack_handler
from app.slack.service import build_answer_blocks, build_slack_reply_text
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
    await import_sample_data(Path("sample-data"))
    async with SessionFactory() as session:
        async with session.begin():
            await session.execute(delete(AnswerSnapshot))
            await session.execute(delete(EvidenceItem))
            await session.execute(delete(Query))
            await session.execute(delete(IngestionJob).where(IngestionJob.job_type == "answer_query"))
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


def _find_actions_block(blocks: list[dict[str, object]]) -> dict[str, object]:
    for block in blocks:
        if block.get("type") == "actions":
            return block
    raise AssertionError("actions block not found")


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
    assert blocks[1]["type"] == "section"
    assert "```" in blocks[1]["text"]["text"]
    assert blocks[2]["type"] == "context"
    assert "Instant answer" in blocks[2]["elements"][0]["text"]
    assert blocks[3]["type"] == "actions"


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
    assert any("```" in block.get("text", {}).get("text", "") for block in posted_reply["blocks"] if block.get("type") == "section")
    actions_block = _find_actions_block(posted_reply["blocks"])
    action_element = actions_block["elements"][0]
    assert action_element["action_id"] == "show_sources"
    assert UUID(action_element["value"])
    assert actions_block["elements"][1]["action_id"] == "look_deeper"

    latest_query = async_runner.run(_load_latest_query())
    assert latest_query is not None
    assert latest_query.slack_channel_id == "C_CRE_LISTINGS_DEMO"
    assert latest_query.slack_user_id == "U_REQUESTOR"
    assert latest_query.slack_ts == "1715860000.000100"


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
    assert processed[0]["pending_message_ts"] == fake_gateway.thread_replies[-1]["ts"]
    assert processed[0]["validation"]["valid"] is True
    assert fake_gateway.updated_messages
    assert any(block.get("type") == "context" for block in fake_gateway.thread_replies[-1]["blocks"])
    assert fake_gateway.thread_replies[-1]["text"].startswith("_Mode: Agent mode - local deeper review_")
    assert "Deeper review" in fake_gateway.thread_replies[-1]["text"]


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