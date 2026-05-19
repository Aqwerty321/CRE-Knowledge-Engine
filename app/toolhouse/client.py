from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import aiohttp

from app.config import get_settings
from app.db.session import SessionFactory
from app.models import AgentRun
from app.toolhouse.local_agent import build_escalation_payload, run_local_deeper_review, validate_agent_response


TOOLHOUSE_AGENT_ID = "0c2c4555-5d96-47e4-8e05-f956de7a102e"
TOOLHOUSE_BASE_URL = "https://agents.toolhouse.ai"


@dataclass(frozen=True)
class ToolhouseRunResult:
    agent_id: str
    run_id: str | None
    raw_response: str
    response_payload: dict[str, Any] | None
    parse_error: str | None = None


class ToolhouseClient:
    def __init__(self, *, api_key: str, agent_id: str, base_url: str = TOOLHOUSE_BASE_URL) -> None:
        self._api_key = api_key
        self._agent_id = agent_id
        self._base_url = base_url.rstrip("/")

    async def send_message(self, message: str, *, run_id: str | None = None) -> ToolhouseRunResult:
        method = "PUT" if run_id else "POST"
        url = f"{self._base_url}/{self._agent_id}"
        if run_id:
            url = f"{url}/{run_id}"

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        chunks: list[str] = []
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=headers, json={"message": message}) as response:
                response.raise_for_status()
                returned_run_id = response.headers.get("X-Toolhouse-Run-ID") or run_id
                async for chunk in response.content.iter_any():
                    if chunk:
                        chunks.append(chunk.decode("utf-8", errors="replace"))

        raw_response = "".join(chunks).strip()
        response_payload, parse_error = parse_toolhouse_response_payload(raw_response)
        return ToolhouseRunResult(
            agent_id=self._agent_id,
            run_id=returned_run_id,
            raw_response=raw_response,
            response_payload=response_payload,
            parse_error=parse_error,
        )


def parse_toolhouse_response_payload(raw_response: str) -> tuple[dict[str, Any] | None, str | None]:
    candidate = raw_response.strip()
    if not candidate:
        return None, "empty_response"

    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None, "json_object_not_found"
        try:
            payload = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            return None, f"invalid_json: {exc.msg}"

    if not isinstance(payload, dict):
        return None, "json_root_not_object"
    return payload, None


def build_toolhouse_message(escalation_payload: dict[str, Any]) -> str:
    message_payload = {
        **escalation_payload,
        "task": "look_deeper",
        "instructions": (
            "Use CRE Backend MCP first. Return only the strict JSON object required by the "
            "CRE MCP Look Deeper Analyst output contract. For answered responses, cite at least one "
            "allowed evidence ID from this run. The initial payload includes evidence_context, backend_mcp_tools, "
            "and recommended MCP calls. Use describe_backend_schema, expand_query_context, summarize_inventory, "
            "rank_properties, get_property_timeline, find_property_conflicts, search_properties, aggregate_properties, "
            "search_source_chunks, get_source_detail, nearby_properties, and audit_data as needed. "
            "If the initial evidence bundle is empty, do not stop after explain_evidence: use backend MCP search, "
            "schema, audit, aggregate, or coordinator tools to find citable backend evidence. If slack_context is present "
            "and the user asked a follow-up such as 'this', 'that', or 'where is it located', read Slack history only for "
            "antecedent recovery, then verify the recovered property through CRE Backend MCP and mint evidence before answering. "
            "If a useful backend result is not in allowed_evidence_ids, call expand_query_evidence for this query before "
            "citing it. If no backend evidence can be minted, return needs_more_evidence or external_context_only instead "
            "of answering as fact. Do not post to Slack. Keep rendered_answer terse and aligned with "
            "the backend instant-answer style: use a short bold heading or takeaway, 2 to 4 concise bullets max, "
            "no mode labels, no trust-receipt boilerplate, and only a short italic caveat when it materially helps. "
            "When comparing 2 to 5 properties, you may include a compact comparison_table object instead of repeating "
            "all facts in prose."
        ),
    }
    return json.dumps(message_payload, indent=2, sort_keys=True)


def _configured_client() -> ToolhouseClient | None:
    settings = get_settings()
    if not settings.toolhouse_api_key or not settings.toolhouse_agent_id:
        return None
    return ToolhouseClient(api_key=settings.toolhouse_api_key, agent_id=settings.toolhouse_agent_id)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid_or_none(value: str) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


async def _create_agent_run(query_id: str, *, provider: str, escalation_payload: dict[str, Any]) -> UUID:
    allowed_evidence_ids = []
    if isinstance(escalation_payload.get("allowed_evidence_ids"), list):
        allowed_evidence_ids = [str(value) for value in escalation_payload["allowed_evidence_ids"]]

    async with SessionFactory() as session:
        async with session.begin():
            agent_run = AgentRun(
                query_id=_uuid_or_none(query_id),
                original_query_id=str(query_id),
                provider=provider,
                status="running",
                allowed_evidence_ids_json=allowed_evidence_ids,
                started_at=_utcnow(),
            )
            session.add(agent_run)
            await session.flush()
            return agent_run.id


async def _finish_agent_run(agent_run_id: UUID, **updates: Any) -> None:
    async with SessionFactory() as session:
        async with session.begin():
            agent_run = await session.get(AgentRun, agent_run_id)
            if agent_run is None:
                return
            for field_name, value in updates.items():
                setattr(agent_run, field_name, value)
            agent_run.finished_at = _utcnow()


def _fallback_with_toolhouse_error(local_payload: dict[str, Any], *, error: str, run_id: str | None = None) -> dict[str, Any]:
    dependency_state = dict(local_payload.get("dependency_state") or {})
    dependency_state.update({"toolhouse": False, "toolhouse_error": error})
    local_payload["dependency_state"] = dependency_state
    local_payload["toolhouse_run_id"] = run_id
    local_payload["toolhouse_fallback"] = True
    return local_payload


async def run_toolhouse_deeper_review(
    query_id: str,
    *,
    client: ToolhouseClient | None = None,
) -> dict[str, Any]:
    escalation_payload = await build_escalation_payload(query_id)
    active_client = client or _configured_client()
    initial_provider = "toolhouse" if active_client is not None else "local"
    agent_run_id = await _create_agent_run(query_id, provider=initial_provider, escalation_payload=escalation_payload)

    if escalation_payload.get("status") != "ready":
        payload = {
            "status": "not_ready",
            "answer_mode": "agent_mode",
            "query_id": query_id,
            "rendered_answer": str(escalation_payload.get("message") or "No local evidence bundle is available."),
            "validation": {"valid": False, "invalid_evidence_ids": []},
            "escalation_payload": escalation_payload,
        }
        await _finish_agent_run(
            agent_run_id,
            provider="none",
            status="not_ready",
            answer_mode="agent_mode",
            validation_json=dict(payload["validation"]),
            response_payload_json={},
            dependency_state_json={},
            rendered_answer=str(payload["rendered_answer"]),
        )
        payload["agent_run_id"] = str(agent_run_id)
        return payload

    if active_client is None:
        payload = await run_local_deeper_review(query_id)
        await _finish_agent_run(
            agent_run_id,
            provider="local",
            status=str(payload.get("status") or "unknown"),
            answer_mode=str(payload.get("answer_mode") or "agent_mode"),
            cited_evidence_ids_json=[str(value) for value in payload.get("cited_evidence_ids", [])],
            validation_json=dict(payload.get("validation") or {}),
            dependency_state_json=dict(payload.get("dependency_state") or {}),
            rendered_answer=str(payload.get("rendered_answer") or ""),
            response_payload_json={},
        )
        payload["agent_run_id"] = str(agent_run_id)
        return payload

    try:
        result = await active_client.send_message(build_toolhouse_message(escalation_payload))
    except (aiohttp.ClientError, TimeoutError) as exc:
        local_payload = await run_local_deeper_review(query_id)
        payload = _fallback_with_toolhouse_error(local_payload, error=f"transport_error: {exc}")
        await _finish_agent_run(
            agent_run_id,
            provider="local_fallback",
            status=str(payload.get("status") or "unknown"),
            answer_mode=str(payload.get("answer_mode") or "agent_mode"),
            cited_evidence_ids_json=[str(value) for value in payload.get("cited_evidence_ids", [])],
            validation_json=dict(payload.get("validation") or {}),
            dependency_state_json=dict(payload.get("dependency_state") or {}),
            fallback_reason=f"transport_error: {exc}",
            rendered_answer=str(payload.get("rendered_answer") or ""),
            response_payload_json={},
        )
        payload["agent_run_id"] = str(agent_run_id)
        return payload

    if result.response_payload is None:
        local_payload = await run_local_deeper_review(query_id)
        error = f"parse_error: {result.parse_error}"
        payload = _fallback_with_toolhouse_error(
            local_payload,
            error=error,
            run_id=result.run_id,
        )
        await _finish_agent_run(
            agent_run_id,
            provider="local_fallback",
            status=str(payload.get("status") or "unknown"),
            answer_mode=str(payload.get("answer_mode") or "agent_mode"),
            toolhouse_agent_id=result.agent_id,
            toolhouse_run_id=result.run_id,
            cited_evidence_ids_json=[str(value) for value in payload.get("cited_evidence_ids", [])],
            validation_json=dict(payload.get("validation") or {}),
            dependency_state_json=dict(payload.get("dependency_state") or {}),
            fallback_reason=error,
            rendered_answer=str(payload.get("rendered_answer") or ""),
            raw_response=result.raw_response,
            response_payload_json={},
        )
        payload["agent_run_id"] = str(agent_run_id)
        return payload

    response_payload = result.response_payload
    refreshed_escalation_payload = await build_escalation_payload(query_id)
    validation_payload = refreshed_escalation_payload if refreshed_escalation_payload.get("status") == "ready" else escalation_payload
    validation = validate_agent_response(
        allowed_evidence_ids=set(validation_payload["allowed_evidence_ids"]),
        response_payload=response_payload,
    )
    if not validation["valid"]:
        local_payload = await run_local_deeper_review(query_id)
        invalid_ids = ", ".join(validation.get("invalid_evidence_ids") or [])
        schema_errors = "; ".join(validation.get("schema_errors") or [])
        detail = "; ".join(part for part in [f"invalid_ids: {invalid_ids}" if invalid_ids else "", schema_errors] if part)
        fallback_payload = _fallback_with_toolhouse_error(
            local_payload,
            error=f"validation_error: {detail or 'invalid Toolhouse response'}",
            run_id=result.run_id,
        )
        fallback_payload["toolhouse_agent_id"] = result.agent_id
        fallback_payload["toolhouse_validation"] = validation
        await _finish_agent_run(
            agent_run_id,
            provider="local_fallback",
            status=str(fallback_payload.get("status") or "unknown"),
            answer_mode=str(fallback_payload.get("answer_mode") or "agent_mode"),
            toolhouse_agent_id=result.agent_id,
            toolhouse_run_id=result.run_id,
            cited_evidence_ids_json=[str(value) for value in fallback_payload.get("cited_evidence_ids", [])],
            validation_json=dict(validation),
            dependency_state_json=dict(fallback_payload.get("dependency_state") or {}),
            fallback_reason=f"validation_error: {detail or 'invalid Toolhouse response'}",
            rendered_answer=str(fallback_payload.get("rendered_answer") or ""),
            raw_response=result.raw_response,
            allowed_evidence_ids_json=[str(value) for value in validation_payload.get("allowed_evidence_ids", [])],
            response_payload_json=dict(response_payload),
        )
        fallback_payload["agent_run_id"] = str(agent_run_id)
        return fallback_payload

    payload = {
        "status": str(response_payload.get("status") or "answered"),
        "answer_mode": "agent_mode",
        "query_id": query_id,
        "rendered_answer": str(response_payload.get("rendered_answer") or "Toolhouse returned no answer text."),
        "comparison_table": response_payload.get("comparison_table") if isinstance(response_payload.get("comparison_table"), dict) else None,
        "cited_evidence_ids": [str(value) for value in response_payload.get("cited_evidence_ids", [])],
        "validation": validation,
        "dependency_state": {"toolhouse": True, "local_deeper_review": False, "llm": True},
        "toolhouse_agent_id": result.agent_id,
        "toolhouse_run_id": result.run_id,
        "toolhouse_response": response_payload,
        "escalation_payload": validation_payload,
    }
    await _finish_agent_run(
        agent_run_id,
        provider="toolhouse",
        status=str(payload.get("status") or "unknown"),
        answer_mode="agent_mode",
        toolhouse_agent_id=result.agent_id,
        toolhouse_run_id=result.run_id,
        cited_evidence_ids_json=[str(value) for value in payload.get("cited_evidence_ids", [])],
        validation_json=dict(validation),
        dependency_state_json=dict(payload.get("dependency_state") or {}),
        rendered_answer=str(payload.get("rendered_answer") or ""),
        raw_response=result.raw_response,
        allowed_evidence_ids_json=[str(value) for value in validation_payload.get("allowed_evidence_ids", [])],
        response_payload_json=dict(response_payload),
    )
    payload["agent_run_id"] = str(agent_run_id)
    return payload


__all__ = [
    "TOOLHOUSE_AGENT_ID",
    "ToolhouseClient",
    "ToolhouseRunResult",
    "build_toolhouse_message",
    "parse_toolhouse_response_payload",
    "run_toolhouse_deeper_review",
]