from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_PRIMARY_EMAIL = "aaditya@toolhouse.ai"
DEFAULT_SECONDARY_EMAIL = "aadityasoni2020@gmail.com"
DEFAULT_INTERVAL_SECONDS = 45.0
DEFAULT_TOOLHOUSE_POLL_INTERVAL_SECONDS = 12.0
DEMO_DATA_DIR = Path(__file__).resolve().parents[1] / "gmail-demo-data"
SUBJECT_PREFIX = "[CRE-DEMO]"
TOOLHOUSE_AGENT_RUNS_URL = "https://api.toolhouse.ai/v1/agent-runs"
TOOLHOUSE_USER_AGENT = "Mozilla/5.0 (compatible; CRE-Gmail-Demo/0.1)"
UUID_PATTERN = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
)


@dataclass(frozen=True)
class SeedEmail:
    sequence: int
    title: str
    subject: str
    body: str


def load_email_templates(path: Path | None = None) -> list[SeedEmail]:
    template_path = path or (DEMO_DATA_DIR / "email-templates.md")
    text = template_path.read_text(encoding="utf-8")
    sections = re.finditer(
        r"^##\s+(?P<sequence>\d+)\s+—\s+(?P<title>.+?)\n(?P<section>.*?)(?=^##\s+\d+\s+—|\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )

    messages: list[SeedEmail] = []
    for match in sections:
        section = match.group("section")
        subject_match = re.search(r"^\*\*Subject:\*\*\s*(.+)$", section, flags=re.MULTILINE)
        body_match = re.search(r"^\*\*Body:\*\*\s*\n(?P<body>.*)\Z", section, flags=re.MULTILINE | re.DOTALL)
        if not subject_match or not body_match:
            raise ValueError(f"Template section {match.group('sequence')} is missing Subject or Body.")

        subject = subject_match.group(1).strip()
        if not subject.startswith(SUBJECT_PREFIX):
            subject = f"{SUBJECT_PREFIX} {subject}"
        messages.append(
            SeedEmail(
                sequence=int(match.group("sequence")),
                title=match.group("title").strip(),
                subject=subject,
                body=body_match.group("body").strip(),
            )
        )

    if len(messages) != 10 or [message.sequence for message in messages] != list(range(1, 11)):
        raise ValueError("The live demo requires exactly ten templates numbered 1 through 10.")
    return messages


def select_messages(messages: Sequence[SeedEmail], *, start_at: int, limit: int | None) -> list[SeedEmail]:
    if start_at < 1:
        raise ValueError("start_at must be at least 1")
    selected = [message for message in messages if message.sequence >= start_at]
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        selected = selected[:limit]
    if not selected:
        raise ValueError("No seed messages selected.")
    return selected


def _toolhouse_request(
    url: str,
    *,
    api_key: str,
    method: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": TOOLHOUSE_USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed Toolhouse HTTPS endpoint
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Toolhouse returned HTTP {exc.code}: {detail[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Toolhouse request failed: {exc.reason}") from exc
    if not body:
        raise RuntimeError("Toolhouse returned an empty response.")
    result = json.loads(body)
    if not isinstance(result, dict):
        raise RuntimeError("Toolhouse returned a non-object response.")
    return result


def normalize_toolhouse_chat_id(value: str) -> str:
    """Accept either a Toolhouse Chat UUID or a copied agents.toolhouse.ai URL."""

    match = UUID_PATTERN.search(value.strip())
    if not match:
        raise ValueError(
            "GMAIL_DEMO_TOOLHOUSE_CHAT_ID must be a Toolhouse Chat UUID or a share URL containing that UUID."
        )
    return match.group(0)


def normalize_toolhouse_agent_url(value: str) -> str | None:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.hostname != "agents.toolhouse.ai":
        return None
    match = UUID_PATTERN.search(parsed.path)
    if not match:
        raise ValueError("The Toolhouse Agent URL does not contain a valid Agent UUID.")
    return f"https://agents.toolhouse.ai/{match.group(0)}"


def run_toolhouse_agent_endpoint(
    *,
    api_key: str,
    agent_url: str,
    timeout_seconds: float,
    message: str | None = None,
) -> str:
    data = json.dumps({"message": message}).encode("utf-8") if message else b""
    request = Request(
        agent_url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "text/event-stream, application/json",
            "Content-Type": "application/json",
            "User-Agent": TOOLHOUSE_USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - validated Toolhouse HTTPS host
            while response.read(64 * 1024):
                pass
            run_id = response.headers.get("X-Toolhouse-Run-ID")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Toolhouse Agent endpoint returned HTTP {exc.code}: {detail[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Toolhouse Agent endpoint failed: {exc.reason}") from exc
    return run_id or normalize_toolhouse_chat_id(agent_url)


def verify_toolhouse_run_result(*, api_key: str, run_id: str) -> None:
    result: dict[str, object] | None = None
    for attempt in range(3):
        try:
            result = _toolhouse_request(
                f"{TOOLHOUSE_AGENT_RUNS_URL}/{run_id}",
                api_key=api_key,
                method="GET",
            )
            break
        except TimeoutError:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
    if result is None:  # pragma: no cover - defensive; the loop either assigns or raises
        raise RuntimeError("Toolhouse did not return Agent Run details.")
    data = result.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Toolhouse did not return Agent Run details.")
    status = data.get("status")
    message = str(data.get("last_agent_message") or "").strip()
    if status != "completed":
        raise RuntimeError(f"Toolhouse Agent Run ended with status {status!r}.")
    normalized = message.lower()
    reported_errors = re.search(r"(?im)^-?\s*errors:\s*([1-9][0-9]*)\s*$", message)
    non_operational_ack = normalized.rstrip(".!") in {"started", "started working"}
    missing_connected_tools = (
        "i can't complete" in normalized
        or "i can’t complete" in normalized
        or "do not currently have" in normalized
        or "don't currently have" in normalized
        or "don’t currently have" in normalized
    )
    if (
        normalized.startswith("blocked:")
        or normalized.startswith("stopped with an error")
        or "i’m blocked" in normalized
        or "i'm blocked" in normalized
        or reported_errors
        or non_operational_ack
        or missing_connected_tools
    ):
        raise RuntimeError(f"Toolhouse workflow blocked: {message[:1200]}")
    if message:
        print(f"Toolhouse result: {message[:1200]}", flush=True)


def trigger_toolhouse_run(
    *,
    api_key: str,
    chat_id: str,
    run_vars: dict[str, str] | None = None,
) -> str:
    payload: dict[str, object] = {"chat_id": normalize_toolhouse_chat_id(chat_id)}
    if run_vars:
        payload["vars"] = run_vars
    result = _toolhouse_request(
        TOOLHOUSE_AGENT_RUNS_URL,
        api_key=api_key,
        method="POST",
        payload=payload,
    )
    data = result.get("data")
    run_id = data.get("id") if isinstance(data, dict) else None
    if not isinstance(run_id, str) or not run_id:
        raise RuntimeError("Toolhouse did not return an Agent Run ID.")
    return run_id


def wait_for_toolhouse_run(*, api_key: str, run_id: str, timeout_seconds: float) -> str:
    if timeout_seconds <= 0:
        raise ValueError("Toolhouse timeout must be greater than zero.")
    deadline = time.monotonic() + timeout_seconds
    previous_status = ""
    transient_failures = 0
    while time.monotonic() < deadline:
        try:
            result = _toolhouse_request(
                f"{TOOLHOUSE_AGENT_RUNS_URL}/{run_id}",
                api_key=api_key,
                method="GET",
            )
            transient_failures = 0
        except (RuntimeError, TimeoutError) as exc:
            transient_failures += 1
            if transient_failures >= 5:
                raise RuntimeError(
                    f"Toolhouse Agent Run status failed {transient_failures} consecutive times: {exc}"
                ) from exc
            time.sleep(DEFAULT_TOOLHOUSE_POLL_INTERVAL_SECONDS)
            continue
        data = result.get("data")
        status = data.get("status") if isinstance(data, dict) else None
        if not isinstance(status, str):
            raise RuntimeError("Toolhouse Agent Run response did not contain a status.")
        if status != previous_status:
            print(f"Toolhouse run {run_id}: {status}", flush=True)
            previous_status = status
        if status == "completed":
            return status
        if status == "failed":
            detail = data.get("last_agent_message") if isinstance(data, dict) else None
            raise RuntimeError(f"Toolhouse Agent Run failed: {detail or 'inspect Agent Logs'}")
        time.sleep(DEFAULT_TOOLHOUSE_POLL_INTERVAL_SECONDS)
    raise RuntimeError(f"Toolhouse Agent Run {run_id} exceeded {timeout_seconds:g} seconds.")


def _toolhouse_run_needs_configuration(*, api_key: str, run_id: str) -> bool:
    result = _toolhouse_request(
        f"{TOOLHOUSE_AGENT_RUNS_URL}/{run_id}",
        api_key=api_key,
        method="GET",
    )
    data = result.get("data")
    message = str(data.get("last_agent_message") or "") if isinstance(data, dict) else ""
    normalized = message.lower()
    return "spreadsheet_id_here" in normalized or "your_name_here" in normalized


def _continue_toolhouse_run_with_configuration(
    *,
    api_key: str,
    run_id: str,
    run_vars: dict[str, str],
    timeout_seconds: float,
) -> None:
    spreadsheet_id = run_vars.get("spreadsheet_id", "").strip()
    sender_name = run_vars.get("sender_name", "").strip()
    if not spreadsheet_id or not sender_name:
        raise RuntimeError("Toolhouse prompt configuration requires spreadsheet_id and sender_name.")
    _toolhouse_request(
        f"{TOOLHOUSE_AGENT_RUNS_URL}/{run_id}",
        api_key=api_key,
        method="PUT",
        payload={
            "message": (
                f"Use spreadsheet ID {spreadsheet_id} and reply sender name {sender_name}. "
                "Continue the Gmail CRE worker procedure now. Google Sheets is the only property database."
            )
        },
    )
    wait_for_toolhouse_run(
        api_key=api_key,
        run_id=run_id,
        timeout_seconds=timeout_seconds,
    )


def run_toolhouse_and_wait(
    *,
    api_key: str,
    chat_id_or_agent_url: str,
    timeout_seconds: float,
    run_vars: dict[str, str] | None = None,
    agent_message: str | None = None,
) -> str:
    agent_url = normalize_toolhouse_agent_url(chat_id_or_agent_url)
    if agent_url:
        print(f"Toolhouse Agent endpoint: running", flush=True)
        run_id = run_toolhouse_agent_endpoint(
            api_key=api_key,
            agent_url=agent_url,
            timeout_seconds=timeout_seconds,
            message=agent_message,
        )
        print(f"Toolhouse Agent run_id={run_id}", flush=True)
        if run_vars and _toolhouse_run_needs_configuration(api_key=api_key, run_id=run_id):
            print("Toolhouse Agent endpoint: supplying configured Sheet variables", flush=True)
            _continue_toolhouse_run_with_configuration(
                api_key=api_key,
                run_id=run_id,
                run_vars=run_vars,
                timeout_seconds=timeout_seconds,
            )
        verify_toolhouse_run_result(api_key=api_key, run_id=run_id)
        print(f"Toolhouse Agent endpoint: completed", flush=True)
        return run_id

    run_id = trigger_toolhouse_run(
        api_key=api_key,
        chat_id=chat_id_or_agent_url,
        run_vars=run_vars,
    )
    wait_for_toolhouse_run(api_key=api_key, run_id=run_id, timeout_seconds=timeout_seconds)
    if run_vars and _toolhouse_run_needs_configuration(api_key=api_key, run_id=run_id):
        print("Toolhouse Agent Run: supplying configured Sheet variables", flush=True)
        _continue_toolhouse_run_with_configuration(
            api_key=api_key,
            run_id=run_id,
            run_vars=run_vars,
            timeout_seconds=timeout_seconds,
        )
    verify_toolhouse_run_result(api_key=api_key, run_id=run_id)
    return run_id


def send_live_messages(
    messages: Sequence[SeedEmail],
    *,
    sender: str,
    recipient: str,
    app_password: str,
    interval_seconds: float,
    toolhouse_api_key: str = "",
    toolhouse_chat_id: str = "",
    toolhouse_run_vars: dict[str, str] | None = None,
    delivery_wait_seconds: float = 8.0,
    toolhouse_timeout_seconds: float = 240.0,
) -> str:
    if interval_seconds < 0:
        raise ValueError("interval_seconds cannot be negative")
    password = "".join(app_password.split())
    if not password:
        raise ValueError("GMAIL_DEMO_SECONDARY_APP_PASSWORD is required for live sending.")
    trigger_toolhouse = bool(toolhouse_api_key or toolhouse_chat_id)
    if trigger_toolhouse and not (toolhouse_api_key and toolhouse_chat_id):
        raise ValueError("Both TOOLHOUSE_API_KEY and GMAIL_DEMO_TOOLHOUSE_CHAT_ID are required to trigger Agent Runs.")
    if delivery_wait_seconds < 0:
        raise ValueError("delivery_wait_seconds cannot be negative")

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as smtp:
        smtp.login(sender, password)
        for index, seed in enumerate(messages):
            message = EmailMessage()
            message["From"] = sender
            message["To"] = recipient
            message["Subject"] = seed.subject
            message["Date"] = format_datetime(datetime.now().astimezone())
            message["Message-ID"] = make_msgid(domain="gmail.com")
            message["X-CRE-Demo-Run-ID"] = run_id
            message["X-CRE-Demo-Sequence"] = str(seed.sequence)
            message.set_content(seed.body)
            smtp.send_message(message)
            print(f"sent {seed.sequence:02d}/10 -> {recipient}: {seed.subject}", flush=True)
            if trigger_toolhouse:
                if delivery_wait_seconds:
                    time.sleep(delivery_wait_seconds)
                agent_run_id = run_toolhouse_and_wait(
                    api_key=toolhouse_api_key,
                    chat_id_or_agent_url=toolhouse_chat_id,
                    timeout_seconds=toolhouse_timeout_seconds,
                    run_vars=toolhouse_run_vars,
                    agent_message=(
                        "Execute the Gmail CRE Demo Worker RUN PROCEDURE for ONLY the Gmail message "
                        f"with exact subject: {seed.subject}. Do not process any other Gmail message."
                    ),
                )
            elif index < len(messages) - 1 and interval_seconds:
                time.sleep(interval_seconds)
    return run_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send the ten real CRE demo emails from the secondary Gmail to the primary inbox.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Print the selected messages without connecting to Gmail.")
    mode.add_argument(
        "--confirm-live-send",
        action="store_true",
        help="Actually send email using the secondary Gmail App Password from the environment.",
    )
    mode.add_argument(
        "--trigger-toolhouse-only",
        action="store_true",
        help="Create and wait for one Toolhouse Agent Run without sending another Gmail message.",
    )
    parser.add_argument(
        "--sender",
        default=os.getenv("GMAIL_DEMO_SECONDARY_EMAIL", DEFAULT_SECONDARY_EMAIL),
        help=f"Sending Gmail address (default: {DEFAULT_SECONDARY_EMAIL}).",
    )
    parser.add_argument(
        "--recipient",
        default=os.getenv("GMAIL_DEMO_PRIMARY_EMAIL", DEFAULT_PRIMARY_EMAIL),
        help=f"Monitored primary inbox (default: {DEFAULT_PRIMARY_EMAIL}).",
    )
    parser.add_argument("--start-at", type=int, default=1, help="First numbered template to send (default: 1).")
    parser.add_argument("--limit", type=int, help="Maximum number of templates to send.")
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"Delay between live emails (default: {DEFAULT_INTERVAL_SECONDS:g}).",
    )
    parser.add_argument(
        "--trigger-toolhouse",
        action="store_true",
        help="After each Gmail delivery, create and wait for one Toolhouse Agent Run.",
    )
    parser.add_argument(
        "--delivery-wait-seconds",
        type=float,
        default=8.0,
        help="Wait after SMTP delivery before triggering Toolhouse (default: 8).",
    )
    parser.add_argument(
        "--toolhouse-timeout-seconds",
        type=float,
        default=240.0,
        help="Maximum time to wait for each Toolhouse Agent Run (default: 240).",
    )
    return parser


def _configured_toolhouse_run_vars() -> dict[str, str]:
    return {
        "spreadsheet_id": os.getenv("GMAIL_DEMO_SPREADSHEET_ID", "").strip(),
        "sender_name": os.getenv("GMAIL_DEMO_SENDER_NAME", "").strip(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        selected = select_messages(load_email_templates(), start_at=args.start_at, limit=args.limit)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print(f"sender: {args.sender}")
    print(f"recipient: {args.recipient}")
    if args.trigger_toolhouse_only:
        toolhouse_api_key = os.getenv("TOOLHOUSE_API_KEY", "")
        toolhouse_chat_id = os.getenv("GMAIL_DEMO_TOOLHOUSE_CHAT_ID", "")
        if not (toolhouse_api_key and toolhouse_chat_id):
            raise SystemExit(
                "--trigger-toolhouse-only requires TOOLHOUSE_API_KEY and GMAIL_DEMO_TOOLHOUSE_CHAT_ID in the environment."
            )
        try:
            agent_run_id = run_toolhouse_and_wait(
                api_key=toolhouse_api_key,
                chat_id_or_agent_url=toolhouse_chat_id,
                timeout_seconds=args.toolhouse_timeout_seconds,
                run_vars=_configured_toolhouse_run_vars(),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise SystemExit(f"Toolhouse-only trigger failed: {exc}") from exc
        print(f"Toolhouse-only trigger complete; run_id={agent_run_id}")
        return 0

    print(f"selected: {len(selected)} email(s)")
    if args.dry_run:
        for message in selected:
            print(f"{message.sequence:02d}/10 {message.subject}")
        print("dry run only; no Gmail connection was made")
        return 0

    app_password = os.getenv("GMAIL_DEMO_SECONDARY_APP_PASSWORD", "")
    toolhouse_api_key = os.getenv("TOOLHOUSE_API_KEY", "") if args.trigger_toolhouse else ""
    toolhouse_chat_id = os.getenv("GMAIL_DEMO_TOOLHOUSE_CHAT_ID", "") if args.trigger_toolhouse else ""
    if args.trigger_toolhouse and not (toolhouse_api_key and toolhouse_chat_id):
        raise SystemExit(
            "--trigger-toolhouse requires TOOLHOUSE_API_KEY and GMAIL_DEMO_TOOLHOUSE_CHAT_ID in the environment."
        )
    try:
        run_id = send_live_messages(
            selected,
            sender=args.sender,
            recipient=args.recipient,
            app_password=app_password,
            interval_seconds=args.interval_seconds,
            toolhouse_api_key=toolhouse_api_key,
            toolhouse_chat_id=toolhouse_chat_id,
            toolhouse_run_vars=_configured_toolhouse_run_vars(),
            delivery_wait_seconds=args.delivery_wait_seconds,
            toolhouse_timeout_seconds=args.toolhouse_timeout_seconds,
        )
    except (OSError, RuntimeError, smtplib.SMTPException, ValueError) as exc:
        raise SystemExit(f"live send failed: {exc}") from exc
    print(f"live seed complete; run_id={run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
