from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.evaluation.golden import demo_doctor, demo_dry_run


@dataclass(frozen=True)
class SecretPattern:
    name: str
    regex: re.Pattern[str]


SECRET_PATTERNS: tuple[SecretPattern, ...] = (
    SecretPattern("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}\b")),
    SecretPattern("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{36,}\b")),
    SecretPattern("openai_style_key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    SecretPattern("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    SecretPattern("toolhouse_style_key", re.compile(r"\bth_[A-Za-z0-9_-]{24,}\b")),
    SecretPattern("private_key", re.compile(r"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY")),
)

SCAN_SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".ini", ".yml", ".yaml", ".sh", ".csv"}
SCAN_FILE_NAMES = {".env.example", "Makefile", "Dockerfile"}
EXCLUDED_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".runtime",
    ".venv",
    "__pycache__",
    "cache",
    "downloads",
    "htmlcov",
    "node_modules",
    "venv",
}
EXCLUDED_FILE_NAMES = {".env", ".env.local", "uv.lock", "graph.html", "graph.json"}


def _should_scan_file(path: Path) -> bool:
    if path.name in EXCLUDED_FILE_NAMES:
        return False
    if path.name in SCAN_FILE_NAMES:
        return True
    return path.suffix in SCAN_SUFFIXES


def _iter_scan_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED_DIR_NAMES for part in relative.parts[:-1]):
            continue
        if _should_scan_file(path):
            files.append(path)
    return sorted(files)


def _redact_secret(value: str) -> str:
    if len(value) <= 12:
        return "<redacted>"
    return f"{value[:6]}...{value[-4:]}"


def scan_workspace_for_secrets(root: Path | str = ".") -> dict[str, object]:
    scan_root = Path(root).resolve()
    findings: list[dict[str, object]] = []
    scanned_files = _iter_scan_files(scan_root)

    for path in scanned_files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern in SECRET_PATTERNS:
                for match in pattern.regex.finditer(line):
                    findings.append(
                        {
                            "path": str(path.relative_to(scan_root)),
                            "line": line_number,
                            "pattern": pattern.name,
                            "match": _redact_secret(match.group(0)),
                        }
                    )

    return {
        "status": "passed" if not findings else "failed",
        "root": str(scan_root),
        "scanned_file_count": len(scanned_files),
        "finding_count": len(findings),
        "findings": findings,
        "excluded_local_files": sorted(EXCLUDED_FILE_NAMES),
        "note": "Scans source, docs, config, and sample text files while excluding local env/runtime artifacts.",
    }


async def build_submission_report(
    *,
    include_public_callback: bool = True,
    include_toolhouse_smoke: bool = False,
    scan_root: Path | str = ".",
) -> dict[str, object]:
    doctor_payload = await demo_doctor(
        include_public_callback=include_public_callback,
        include_toolhouse_smoke=include_toolhouse_smoke,
    )
    dry_run_payload = await demo_dry_run(
        include_public_callback=include_public_callback,
        live_toolhouse=False,
    )
    secret_scan_payload = scan_workspace_for_secrets(scan_root)
    ready = (
        doctor_payload.get("status") == "ready"
        and dry_run_payload.get("status") == "passed"
        and secret_scan_payload.get("status") == "passed"
    )
    return {
        "status": "ready" if ready else "needs_attention",
        "deliverables": {
            "github_repo": "ready_when_pushed",
            "readme": "README.md",
            "architecture_diagram": "README.md mermaid diagram",
            "demo_video_script": "docs/slack-demo-video-script.md",
            "demo_runbook": "docs/slack-demo-runbook.md",
            "follow_up_answers": {
                "hardest_part": "Keeping Slack ingestion, document extraction, retrieval, citations, Slack actions, and Toolhouse synthesis aligned around replayable evidence IDs.",
                "two_more_weeks": "Add production OAuth and multi-workspace permissions, admin review UI, full telemetry, external geocoding and drive-time search, object storage, retrieval benchmarks, and data retention workflows.",
                "trade_offs": "Postgres-backed jobs and deterministic retrieval were chosen over Redis/Celery/LangChain complexity so the take-home stays reproducible and source-grounded.",
            },
        },
        "doctor": doctor_payload,
        "demo_dry_run": dry_run_payload,
        "secret_scan": secret_scan_payload,
    }


def render_submission_report_markdown(payload: dict[str, object]) -> str:
    doctor = dict(payload.get("doctor") or {})
    dry_run = dict(payload.get("demo_dry_run") or {})
    secret_scan = dict(payload.get("secret_scan") or {})
    deliverables = dict(payload.get("deliverables") or {})
    lines = [
        "# CRE Knowledge Engine Submission Report",
        "",
        f"Overall status: {payload.get('status')}",
        "",
        "## Readiness Checks",
        "",
        f"- Demo doctor: {doctor.get('status')} ({doctor.get('failed_check_count', 0)} failed checks)",
        f"- Demo dry run: {dry_run.get('status')} ({dry_run.get('failed_step_count', 0)} failed steps)",
        f"- Secret scan: {secret_scan.get('status')} ({secret_scan.get('finding_count', 0)} findings)",
        "",
        "## Demo Dry Run",
        "",
    ]
    for step in list(dry_run.get("steps") or []):
        if not isinstance(step, dict):
            continue
        lines.append(f"- {step.get('name')}: {step.get('status')} - `{step.get('query')}`")
        lines.append(
            f"  query_id={step.get('query_id')} route={step.get('route_mode')} evidence={step.get('evidence_count')}"
        )
    lines.extend(
        [
            "",
            "## Deliverables",
            "",
            f"- README: {deliverables.get('readme')}",
            f"- Architecture diagram: {deliverables.get('architecture_diagram')}",
            f"- Demo script: {deliverables.get('demo_video_script')}",
            f"- Demo runbook: {deliverables.get('demo_runbook')}",
            "",
            "## Follow-Up Talking Points",
            "",
        ]
    )
    followups = dict(deliverables.get("follow_up_answers") or {})
    for label, answer in followups.items():
        lines.append(f"- {label.replace('_', ' ').title()}: {answer}")
    return "\n".join(lines) + "\n"


__all__ = [
    "build_submission_report",
    "render_submission_report_markdown",
    "scan_workspace_for_secrets",
]