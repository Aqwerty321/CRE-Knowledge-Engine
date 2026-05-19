from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionFactory, engine
from app.ingestion.sample_importer import SampleDatasetModel, collect_database_counts, import_sample_data, import_sample_dataset, load_sample_manifest
from app.models import AnswerSnapshot, Chunk, EvidenceItem, IngestionJob, PropertyFieldValue, PropertyRecord, Query, SlackEvent, SlackSourcePost, SourceDocument


def _ensure_schema() -> None:
    command.upgrade(Config("alembic.ini"), "head")


async def _prepare_database() -> None:
    async with SessionFactory() as session:
        async with session.begin():
            await session.execute(delete(AnswerSnapshot))
            await session.execute(delete(EvidenceItem))
            await session.execute(delete(Query))
            await session.execute(delete(SlackEvent))
            await session.execute(delete(IngestionJob))
            await session.execute(delete(PropertyFieldValue))
            await session.execute(delete(PropertyRecord))
            await session.execute(delete(Chunk))
            await session.execute(delete(SourceDocument))
    await import_sample_data(Path("sample-data"))


@pytest.fixture
def async_runner() -> asyncio.Runner:
    with asyncio.Runner() as runner:
        yield runner
        runner.run(engine.dispose())


@pytest.fixture
def prepared_db(async_runner: asyncio.Runner) -> None:
    try:
        _ensure_schema()
        async_runner.run(_prepare_database())
    except (OSError, SQLAlchemyError) as exc:
        pytest.skip(f"Postgres not available for Slack demo sync tests: {exc}")


async def _load_main_source() -> SourceDocument | None:
    async with SessionFactory() as session:
        result = await session.execute(
            select(SourceDocument).where(SourceDocument.local_path.like("%main-street-office-flyer.pdf"))
        )
        return result.scalar_one_or_none()


async def _load_sources_by_slack_ts(slack_ts_values: list[str]) -> list[SourceDocument]:
    async with SessionFactory() as session:
        result = await session.execute(
            select(SourceDocument)
            .where(SourceDocument.slack_ts.in_(slack_ts_values))
            .order_by(SourceDocument.slack_ts)
        )
        return list(result.scalars())


async def _load_posts_by_slack_file_id(slack_file_id: str) -> list[SlackSourcePost]:
    async with SessionFactory() as session:
        result = await session.execute(
            select(SlackSourcePost)
            .where(SlackSourcePost.slack_file_id == slack_file_id)
            .order_by(SlackSourcePost.slack_channel_id, SlackSourcePost.slack_ts)
        )
        return list(result.scalars())


async def _load_sources_by_slack_file_id(slack_file_id: str) -> list[SourceDocument]:
    async with SessionFactory() as session:
        result = await session.execute(
            select(SourceDocument)
            .where(SourceDocument.slack_file_id == slack_file_id)
            .order_by(SourceDocument.ingested_at)
        )
        return list(result.scalars())


@pytest.mark.golden
def test_import_sample_dataset_updates_existing_source_without_duplication(
    prepared_db: None,
    async_runner: asyncio.Runner,
) -> None:
    manifest = load_sample_manifest(Path("sample-data"))
    main_source = next(source for source in manifest.sources if source.source_id == "F1")
    expected_source_count = len(manifest.sources)
    updated_source = main_source.model_copy(
        update={
            "slack_file_id": "F_LIVE_MAIN",
            "slack_ts": "1778994885.905099",
            "posted_at": datetime(2026, 5, 17, 13, 41, 25, tzinfo=timezone.utc),
            "source_url": "https://slack.example/files/F_LIVE_MAIN",
        }
    )
    dataset = SampleDatasetModel(
        team_id="T_LIVE_DEMO",
        channel_id="C_LIVE_LISTINGS",
        channel_name="cre-listings",
        sources=[updated_source],
    )

    counts_before = async_runner.run(collect_database_counts())
    result = async_runner.run(import_sample_dataset(dataset, Path("sample-data")))
    counts_after = async_runner.run(collect_database_counts())
    source_document = async_runner.run(_load_main_source())

    assert result["status"] == "imported"
    assert counts_before["source_documents"] == expected_source_count
    assert counts_after["source_documents"] == expected_source_count
    assert source_document is not None
    assert source_document.slack_team_id == "T_LIVE_DEMO"
    assert source_document.slack_channel_name == "cre-listings"
    assert source_document.slack_file_id == "F_LIVE_MAIN"
    assert source_document.source_url == "https://slack.example/files/F_LIVE_MAIN"


@pytest.mark.golden
def test_live_slack_messages_with_same_text_keep_distinct_source_documents(
    prepared_db: None,
    async_runner: asyncio.Runner,
) -> None:
    duplicate_text = "321 Slack Way industrial 20,000 SF at $22/SF, available immediate in Midtown."
    dataset = SampleDatasetModel(
        team_id="T_LIVE_DEMO",
        channel_id="C_LIVE_LISTINGS",
        channel_name="cre-listings",
        sources=[
            {
                "source_id": "slack-message-a",
                "source_type": "slack_message",
                "posted_at": datetime(2026, 5, 17, 13, 50, 0, tzinfo=timezone.utc),
                "slack_ts": "1778997000.000100",
                "source_url": "https://slack.example/messages/1778997000.000100",
                "raw_text": duplicate_text,
            },
            {
                "source_id": "slack-message-b",
                "source_type": "slack_message",
                "posted_at": datetime(2026, 5, 17, 13, 51, 0, tzinfo=timezone.utc),
                "slack_ts": "1778997060.000100",
                "source_url": "https://slack.example/messages/1778997060.000100",
                "raw_text": duplicate_text,
            },
        ],
    )

    counts_before = async_runner.run(collect_database_counts())
    result = async_runner.run(import_sample_dataset(dataset, Path("sample-data")))
    counts_after = async_runner.run(collect_database_counts())
    live_sources = async_runner.run(
        _load_sources_by_slack_ts(["1778997000.000100", "1778997060.000100"])
    )

    assert result["status"] == "imported"
    assert counts_after["source_documents"] == counts_before["source_documents"] + 2
    assert len(live_sources) == 2
    assert [source.slack_ts for source in live_sources] == ["1778997000.000100", "1778997060.000100"]
    assert all(source.source_url for source in live_sources)


@pytest.mark.golden
def test_same_slack_file_shared_in_multiple_channels_keeps_distinct_posts(
    prepared_db: None,
    async_runner: asyncio.Runner,
) -> None:
    manifest = load_sample_manifest(Path("sample-data"))
    main_source = next(source for source in manifest.sources if source.source_id == "F1")
    shared_file_id = "F_MULTI_CHANNEL_MAIN"
    first_share = main_source.model_copy(
        update={
            "slack_file_id": shared_file_id,
            "slack_ts": "1778998000.000100",
            "posted_at": datetime(2026, 5, 17, 14, 10, 0, tzinfo=timezone.utc),
            "source_url": "https://slack.example/files/F_MULTI_CHANNEL_MAIN/listings",
        }
    )
    second_share = main_source.model_copy(
        update={
            "slack_file_id": shared_file_id,
            "slack_ts": "1778998060.000100",
            "posted_at": datetime(2026, 5, 17, 14, 11, 0, tzinfo=timezone.utc),
            "source_url": "https://slack.example/files/F_MULTI_CHANNEL_MAIN/private",
        }
    )

    counts_before = async_runner.run(collect_database_counts())
    first_result = async_runner.run(
        import_sample_dataset(
            SampleDatasetModel(
                team_id="T_LIVE_DEMO",
                channel_id="C_LIVE_LISTINGS",
                channel_name="cre-listings",
                sources=[first_share],
            ),
            Path("sample-data"),
        )
    )
    second_result = async_runner.run(
        import_sample_dataset(
            SampleDatasetModel(
                team_id="T_LIVE_DEMO",
                channel_id="C_PRIVATE_DEMO",
                channel_name="cre-private-demo",
                sources=[second_share],
            ),
            Path("sample-data"),
        )
    )
    counts_after = async_runner.run(collect_database_counts())
    source_documents = async_runner.run(_load_sources_by_slack_file_id(shared_file_id))
    source_posts = async_runner.run(_load_posts_by_slack_file_id(shared_file_id))

    assert first_result["imported_slack_source_post_count"] == 1
    assert second_result["imported_slack_source_post_count"] == 1
    assert counts_after["source_documents"] == counts_before["source_documents"]
    assert counts_after["slack_source_posts"] == counts_before["slack_source_posts"] + 2
    assert len(source_documents) == 1
    assert len(source_posts) == 2
    assert {post.slack_channel_name for post in source_posts} == {"cre-listings", "cre-private-demo"}
    assert {post.source_document_id for post in source_posts} == {source_documents[0].id}