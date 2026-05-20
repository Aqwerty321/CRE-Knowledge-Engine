from pathlib import Path

import asyncio
from types import SimpleNamespace

import pytest

import app.evaluation.golden as golden_module
from app.evaluation import render_submission_report_markdown, scan_workspace_for_secrets


def test_secret_scan_detects_and_redacts_realistic_tokens(tmp_path: Path) -> None:
    token = "xoxb-" + "A" * 24
    (tmp_path / "leaky.md").write_text(f"token={token}\n", encoding="utf-8")

    payload = scan_workspace_for_secrets(tmp_path)

    assert payload["status"] == "failed"
    assert payload["finding_count"] == 1
    finding = payload["findings"][0]
    assert finding["pattern"] == "slack_token"
    assert finding["match"] != token
    assert "..." in finding["match"]


def test_secret_scan_ignores_env_names_and_local_env_file(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("Set CRE_TOOLHOUSE_API_KEY in your local environment.\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SLACK_BOT_TOKEN=xoxb-" + "A" * 24 + "\n", encoding="utf-8")

    payload = scan_workspace_for_secrets(tmp_path)

    assert payload["status"] == "passed"
    assert payload["finding_count"] == 0
    assert payload["scanned_file_count"] == 1


def test_submission_report_markdown_summarizes_readiness() -> None:
    rendered = render_submission_report_markdown(
        {
            "status": "ready",
            "doctor": {"status": "ready", "failed_check_count": 0},
            "demo_dry_run": {
                "status": "passed",
                "failed_step_count": 0,
                "steps": [
                    {
                        "name": "office_filter",
                        "status": "passed",
                        "query": "Show office buildings under $50/sq ft.",
                        "query_id": "query-1",
                        "route_mode": "instant",
                        "evidence_count": 2,
                    }
                ],
            },
            "secret_scan": {"status": "passed", "finding_count": 0},
            "deliverables": {
                "readme": "README.md",
                "architecture_diagram": "README.md mermaid diagram",
                "demo_video_script": "docs/slack-demo-video-script.md",
                "demo_runbook": "docs/slack-demo-runbook.md",
                "follow_up_answers": {"hardest_part": "Keeping evidence aligned."},
            },
        }
    )

    assert "Overall status: ready" in rendered
    assert "Demo doctor: ready" in rendered
    assert "office_filter: passed" in rendered
    assert "Hardest Part" in rendered


def test_demo_doctor_accepts_safe_live_toolhouse_status(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_collect_database_counts() -> dict[str, object]:
        return {"source_documents": 35, "chunks": 35, "property_records": 2431, "slack_source_posts": 50}

    async def fake_check_vector_dependencies() -> dict[str, str]:
        return {"qdrant": "ok", "embedding": "ok", "rerank": "ok", "ocr": "ok"}

    async def fake_collect_ingestion_quality_report() -> dict[str, object]:
        return {
            "toolhouse_readiness": {"status": "ready_for_bounded_agent"},
            "source_document_count": 35,
            "property_record_count": 2431,
            "conflict_groups": [],
        }

    async def fake_run_golden_evals() -> dict[str, object]:
        return {"status": "passed", "case_count": 8, "passed_count": 8, "failed_count": 0, "cases": []}

    async def fake_answer_query(_query: str) -> dict[str, object]:
        return {"query_id": "query-1"}

    async def fake_run_toolhouse_deeper_review(_query_id: str) -> dict[str, object]:
        return {
            "status": "needs_more_evidence",
            "query_id": "query-1",
            "toolhouse_run_id": "run-1",
            "toolhouse_fallback": False,
            "dependency_state": {"toolhouse": True, "local_deeper_review": False, "llm": True},
            "validation": {"valid": True},
        }

    monkeypatch.setattr(
        golden_module,
        "get_settings",
        lambda: SimpleNamespace(
            vector_search_enabled=False,
            vector_index_on_import=False,
            ocr_enabled=False,
            toolhouse_api_key="toolhouse-key",
            toolhouse_agent_id="toolhouse-agent",
            toolhouse_mcp_bearer_token="toolhouse-mcp-token",
            public_callback_url=None,
        ),
    )
    monkeypatch.setattr(golden_module, "collect_database_counts", fake_collect_database_counts)
    monkeypatch.setattr(golden_module, "check_vector_dependencies", fake_check_vector_dependencies)
    monkeypatch.setattr(golden_module, "collect_ingestion_quality_report", fake_collect_ingestion_quality_report)
    monkeypatch.setattr(golden_module, "run_golden_evals", fake_run_golden_evals)
    monkeypatch.setattr(golden_module, "answer_query", fake_answer_query)
    monkeypatch.setattr(golden_module, "run_toolhouse_deeper_review", fake_run_toolhouse_deeper_review)

    payload = asyncio.run(golden_module.demo_doctor(include_public_callback=False, include_toolhouse_smoke=True))

    assert payload["status"] == "ready"
    assert payload["failed_check_count"] == 0
    toolhouse_check = next(check for check in payload["checks"] if check["name"] == "toolhouse_smoke")
    assert toolhouse_check["status"] == "ok"


def test_demo_dry_run_accepts_safe_live_toolhouse_status(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_demo_doctor(*, include_public_callback: bool = False, include_toolhouse_smoke: bool = False) -> dict[str, object]:
        return {"status": "ready", "failed_check_count": 0}

    async def fake_run_demo_dry_run_step(step) -> dict[str, object]:
        return {
            "name": step.name,
            "status": "passed",
            "failures": [],
            "query": step.query,
            "query_id": "loading-query" if step.name == "loading_access" else f"{step.name}-query",
            "replay_command": None,
            "route_mode": step.expected_route_mode,
            "evidence_count": 1,
        }

    async def fake_run_toolhouse_deeper_review(_query_id: str) -> dict[str, object]:
        return {
            "status": "external_context_only",
            "query_id": "loading-query",
            "agent_run_id": "agent-run-1",
            "toolhouse_agent_id": "toolhouse-agent",
            "toolhouse_run_id": "toolhouse-run-1",
            "toolhouse_fallback": False,
            "dependency_state": {"toolhouse": True, "local_deeper_review": False, "llm": True},
            "validation": {"valid": True},
            "rendered_answer": "External context only.",
        }

    monkeypatch.setattr(golden_module, "demo_doctor", fake_demo_doctor)
    monkeypatch.setattr(golden_module, "_run_demo_dry_run_step", fake_run_demo_dry_run_step)
    monkeypatch.setattr(golden_module, "run_toolhouse_deeper_review", fake_run_toolhouse_deeper_review)

    payload = asyncio.run(golden_module.demo_dry_run(include_public_callback=False, live_toolhouse=True))

    assert payload["status"] == "passed"
    assert payload["failed_step_count"] == 0
    assert payload["toolhouse_step"]["status"] == "passed"