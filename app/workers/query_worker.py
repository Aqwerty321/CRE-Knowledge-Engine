from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.answering.query_service import answer_query
from app.db.session import SessionFactory
from app.ingestion.slack_ingestor import INGEST_JOB_TYPES, process_slack_ingestion_job
from app.models import IngestionJob
from app.slack.gateway import SlackGateway
from app.slack.service import (
    build_answer_blocks,
    build_deeper_review_blocks,
    build_failed_status_blocks,
    build_failed_status_text,
    build_pending_status_blocks,
    build_pending_status_text,
    build_slack_reply_text,
)
from app.toolhouse import run_toolhouse_deeper_review


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _merge_checkpoint_json(existing: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    merged.update(updates)
    return merged


def _thread_ts_for_checkpoint(checkpoint: dict[str, Any]) -> str:
    return str(checkpoint.get("thread_ts") or checkpoint.get("query_ts") or "")


async def _claim_query_job_ids(limit: int) -> list[UUID]:
    async with SessionFactory() as session:
        async with session.begin():
            result = await session.execute(
                select(IngestionJob)
                .where(
                    IngestionJob.job_type.in_(["answer_query", "look_deeper", *sorted(INGEST_JOB_TYPES)]),
                    IngestionJob.status == "queued",
                )
                .order_by(IngestionJob.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            jobs = list(result.scalars())
            claimed_ids: list[UUID] = []
            for job in jobs:
                job.status = "running"
                job.attempt_count = int(job.attempt_count or 0) + 1
                job.started_at = _utcnow()
                claimed_ids.append(job.id)
            return claimed_ids


async def _mark_job_failed(job_id: UUID, error_message: str, updates: dict[str, Any] | None = None) -> None:
    async with SessionFactory() as session:
        async with session.begin():
            job = await session.get(IngestionJob, job_id)
            if job is None:
                return
            job.status = "failed"
            job.error_message = error_message
            job.finished_at = _utcnow()
            if updates:
                job.checkpoint_json = _merge_checkpoint_json(dict(job.checkpoint_json), updates)


async def _update_job_checkpoint(job_id: UUID, updates: dict[str, Any]) -> None:
    async with SessionFactory() as session:
        async with session.begin():
            job = await session.get(IngestionJob, job_id)
            if job is None:
                return
            job.checkpoint_json = _merge_checkpoint_json(dict(job.checkpoint_json), updates)


async def _complete_job(job_id: UUID, updates: dict[str, Any]) -> None:
    async with SessionFactory() as session:
        async with session.begin():
            job = await session.get(IngestionJob, job_id)
            if job is None:
                return
            job.status = "succeeded"
            job.finished_at = _utcnow()
            job.checkpoint_json = _merge_checkpoint_json(dict(job.checkpoint_json), updates)
            job.error_message = None


async def process_pending_query_jobs(slack_gateway: SlackGateway | None = None, limit: int = 10) -> list[dict[str, Any]]:
    claimed_ids = await _claim_query_job_ids(limit)
    processed: list[dict[str, Any]] = []

    for job_id in claimed_ids:
        checkpoint: dict[str, Any] = {}
        job_type = ""
        try:
            async with SessionFactory() as session:
                job = await session.get(IngestionJob, job_id)
                if job is None:
                    continue
                job_type = str(job.job_type)
                checkpoint = dict(job.checkpoint_json)

            pending_message_ts = str(checkpoint.get("pending_message_ts") or "")
            if slack_gateway is not None and job_type in {"answer_query", "look_deeper"}:
                channel_id = str(checkpoint.get("channel_id") or "")
                thread_ts = _thread_ts_for_checkpoint(checkpoint)
                if channel_id and thread_ts and not pending_message_ts:
                    pending_response = await slack_gateway.post_thread_reply(
                        channel_id=channel_id,
                        thread_ts=thread_ts,
                        text=build_pending_status_text(job_type=job_type),
                        blocks=build_pending_status_blocks(job_type=job_type),
                    )
                    pending_message_ts = str(pending_response.get("ts") or "")
                    checkpoint["pending_message_ts"] = pending_message_ts
                    await _update_job_checkpoint(
                        job_id,
                        {
                            "pending_message_ts": pending_message_ts,
                            "delivery_status": "pending",
                        },
                    )

            if job_type in INGEST_JOB_TYPES:
                ingestion_payload = await process_slack_ingestion_job(
                    job_type,
                    checkpoint,
                    slack_gateway.client if slack_gateway is not None else None,
                )
                updates = {
                    "delivery_status": "not_applicable",
                    "ingestion_status": ingestion_payload.get("status"),
                    "source_type": ingestion_payload.get("source_type"),
                    "imported_source_count": ingestion_payload.get("imported_source_count"),
                    "imported_chunk_count": ingestion_payload.get("imported_chunk_count"),
                    "imported_property_record_count": ingestion_payload.get("imported_property_record_count"),
                }
            elif job_type == "look_deeper":
                deeper_payload = await run_toolhouse_deeper_review(str(checkpoint.get("query_id") or ""))
                delivery_payload = {"delivery_status": "prepared"}
                if slack_gateway is not None:
                    channel_id = str(checkpoint.get("channel_id") or "")
                    thread_ts = _thread_ts_for_checkpoint(checkpoint)
                    formatted_text = build_slack_reply_text(deeper_payload)
                    if channel_id and pending_message_ts:
                        response = await slack_gateway.update_message(
                            channel_id=channel_id,
                            message_ts=pending_message_ts,
                            text=formatted_text,
                            blocks=build_deeper_review_blocks(deeper_payload),
                        )
                    else:
                        response = await slack_gateway.post_thread_reply(
                            channel_id=channel_id,
                            thread_ts=thread_ts,
                            text=formatted_text,
                            blocks=build_deeper_review_blocks(deeper_payload),
                        )
                    delivery_payload = {
                        "delivery_status": "posted",
                        "delivery_ts": response.get("ts"),
                    }
                updates = {
                    **delivery_payload,
                    "query_id": deeper_payload["query_id"],
                    "answer_mode": deeper_payload.get("answer_mode"),
                    "deeper_review_status": deeper_payload["status"],
                    "pending_message_ts": pending_message_ts or None,
                    "validation": deeper_payload.get("validation"),
                    "toolhouse_agent_id": deeper_payload.get("toolhouse_agent_id"),
                    "toolhouse_run_id": deeper_payload.get("toolhouse_run_id"),
                    "toolhouse_fallback": deeper_payload.get("toolhouse_fallback", False),
                }
            else:
                answer_payload = await answer_query(
                    str(checkpoint.get("query_text") or ""),
                    slack_channel_id=str(checkpoint.get("channel_id") or "") or None,
                    slack_user_id=str(checkpoint.get("user_id") or "") or None,
                    slack_ts=str(checkpoint.get("query_ts") or "") or None,
                )

                delivery_payload = {"delivery_status": "prepared"}
                if slack_gateway is not None:
                    channel_id = str(checkpoint.get("channel_id") or "")
                    thread_ts = _thread_ts_for_checkpoint(checkpoint)
                    formatted_text = build_slack_reply_text(answer_payload)
                    if channel_id and pending_message_ts:
                        response = await slack_gateway.update_message(
                            channel_id=channel_id,
                            message_ts=pending_message_ts,
                            text=formatted_text,
                            blocks=build_answer_blocks(answer_payload),
                        )
                    else:
                        response = await slack_gateway.post_thread_reply(
                            channel_id=channel_id,
                            thread_ts=thread_ts,
                            text=formatted_text,
                            blocks=build_answer_blocks(answer_payload),
                        )
                    delivery_payload = {
                        "delivery_status": "posted",
                        "delivery_ts": response.get("ts"),
                    }

                updates = {
                    **delivery_payload,
                    "query_id": answer_payload["query_id"],
                    "answer_mode": answer_payload.get("answer_mode"),
                    "pending_message_ts": pending_message_ts or None,
                    "route_mode": answer_payload.get("route_mode"),
                    "answer_snapshot_id": answer_payload["answer_snapshot_id"],
                }
            await _complete_job(job_id, updates)
            processed.append({"job_id": str(job_id), "job_type": job_type, **updates})
        except Exception as exc:  # noqa: BLE001
            if slack_gateway is not None and checkpoint and job_type in {"answer_query", "look_deeper"}:
                channel_id = str(checkpoint.get("channel_id") or "")
                thread_ts = _thread_ts_for_checkpoint(checkpoint)
                pending_message_ts = str(checkpoint.get("pending_message_ts") or "")
                try:
                    if channel_id and pending_message_ts:
                        await slack_gateway.update_message(
                            channel_id=channel_id,
                            message_ts=pending_message_ts,
                            text=build_failed_status_text(job_type=job_type),
                            blocks=build_failed_status_blocks(job_type=job_type),
                        )
                    elif channel_id and thread_ts:
                        await slack_gateway.post_thread_reply(
                            channel_id=channel_id,
                            thread_ts=thread_ts,
                            text=build_failed_status_text(job_type=job_type),
                            blocks=build_failed_status_blocks(job_type=job_type),
                        )
                except Exception:
                    pass
            await _mark_job_failed(
                job_id,
                str(exc),
                updates={
                    "delivery_status": "failed",
                    "pending_message_ts": checkpoint.get("pending_message_ts"),
                },
            )
            raise

    return processed


__all__ = ["process_pending_query_jobs"]