from __future__ import annotations

import asyncio
import logging
from time import monotonic

from app.config import get_settings
from app.indexing import index_all_chunks
from app.ingestion.slack_ingestor import prune_slack_storage
from app.slack.gateway import get_slack_gateway
from app.workers.query_worker import process_pending_query_jobs

logger = logging.getLogger(__name__)


async def _maybe_prune_slack_storage(*, last_prune_monotonic: float | None) -> float | None:
    settings = get_settings()
    interval_seconds = float(settings.slack_storage_prune_interval_seconds)
    if interval_seconds <= 0 or not settings.slack_ingest_channels:
        return last_prune_monotonic

    now = monotonic()
    if last_prune_monotonic is not None and (now - last_prune_monotonic) < interval_seconds:
        return last_prune_monotonic

    payload = await prune_slack_storage()
    if int(payload.get("deleted_context_source_count") or 0) > 0:
        await index_all_chunks(reset_collection=True)
    return now


async def run_query_worker_loop(
    *,
    stop_event: asyncio.Event,
    poll_interval_seconds: float,
    batch_limit: int,
) -> None:
    slack_gateway = get_slack_gateway()
    last_prune_monotonic: float | None = None

    while not stop_event.is_set():
        try:
            await process_pending_query_jobs(slack_gateway=slack_gateway, limit=batch_limit)
            last_prune_monotonic = await _maybe_prune_slack_storage(last_prune_monotonic=last_prune_monotonic)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Background Slack query worker iteration failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
        except asyncio.TimeoutError:
            continue


__all__ = ["run_query_worker_loop"]