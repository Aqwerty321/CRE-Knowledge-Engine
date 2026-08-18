from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from urllib.parse import urlparse


REQUIRED_KEYS = (
    "GMAIL_DEMO_PRIMARY_EMAIL",
    "GMAIL_DEMO_SECONDARY_EMAIL",
    "GMAIL_DEMO_MCP_TOKEN",
    "GMAIL_DEMO_PUBLIC_URL",
    "GMAIL_DEMO_SECONDARY_APP_PASSWORD",
    "TOOLHOUSE_API_KEY",
    "GMAIL_DEMO_TOOLHOUSE_CHAT_ID",
    "GMAIL_DEMO_SPREADSHEET_ID",
    "GMAIL_DEMO_SENDER_NAME",
)


def validate_environment(environ: Mapping[str, str]) -> list[str]:
    errors: list[str] = []
    values = {key: environ.get(key, "").strip() for key in REQUIRED_KEYS}
    for key, value in values.items():
        if not value or "CHANGE_ME" in value.upper():
            errors.append(f"{key}: missing or still contains CHANGE_ME")

    if values["GMAIL_DEMO_PRIMARY_EMAIL"] not in {"", "aaditya@toolhouse.ai"}:
        errors.append("GMAIL_DEMO_PRIMARY_EMAIL: must be aaditya@toolhouse.ai for this demo")
    if values["GMAIL_DEMO_SECONDARY_EMAIL"] not in {"", "aadityasoni2020@gmail.com"}:
        errors.append("GMAIL_DEMO_SECONDARY_EMAIL: must be aadityasoni2020@gmail.com for this demo")

    token = values["GMAIL_DEMO_MCP_TOKEN"]
    if token and "CHANGE_ME" not in token.upper() and len(token) < 32:
        errors.append("GMAIL_DEMO_MCP_TOKEN: use at least 32 random characters")

    public_url = values["GMAIL_DEMO_PUBLIC_URL"]
    if public_url and "CHANGE_ME" not in public_url.upper():
        parsed = urlparse(public_url)
        if parsed.scheme != "https" or not parsed.netloc:
            errors.append("GMAIL_DEMO_PUBLIC_URL: must be a public https:// origin")
        if parsed.path.rstrip("/"):
            errors.append("GMAIL_DEMO_PUBLIC_URL: enter only the origin, without /toolhouse/mcp")

    app_password = "".join(values["GMAIL_DEMO_SECONDARY_APP_PASSWORD"].split())
    if app_password and "CHANGE_ME" not in app_password.upper() and len(app_password) != 16:
        errors.append("GMAIL_DEMO_SECONDARY_APP_PASSWORD: Google App Password must contain 16 characters")

    return errors


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    errors = validate_environment(os.environ)
    if errors:
        print("Gmail demo environment is not ready:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Gmail demo environment is ready. All required values are present; no secrets were printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
