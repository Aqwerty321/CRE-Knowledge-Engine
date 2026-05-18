from pathlib import Path

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