from __future__ import annotations

import json
import mimetypes
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import get_settings


def _read_json(request: Request, *, timeout_seconds: float) -> dict[str, object]:
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - local configured service URL
        payload = response.read().decode("utf-8")
    parsed = json.loads(payload)
    return parsed if isinstance(parsed, dict) else {}


def _multipart_body(path: Path, fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"----cre-ocr-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")

    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    chunks.append(f"--{boundary}\r\n".encode("utf-8"))
    chunks.append(
        (
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    chunks.append(path.read_bytes())
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), boundary


def _extract_task_id(payload: dict[str, object]) -> str:
    data = payload.get("data")
    if isinstance(data, dict) and data.get("task_id"):
        return str(data["task_id"])
    raise RuntimeError(f"OCR backend did not return a task_id: {payload}")


def parse_document_with_ocr(path: Path) -> dict[str, object]:
    settings = get_settings()
    base_url = settings.ocr_backend_url.rstrip("/")
    body, boundary = _multipart_body(
        path,
        {
            "processing_mode": "pipeline",
            "priority": "3",
            "enable_touchup": "false",
            "output_format": "markdown",
        },
    )
    request = Request(
        f"{base_url}/api/v1/tasks/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        task_payload = _read_json(request, timeout_seconds=settings.ocr_timeout_seconds)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"OCR backend upload failed: {exc}") from exc

    task_id = _extract_task_id(task_payload)
    status_url = f"{base_url}/api/v1/tasks/{task_id}"
    deadline = time.monotonic() + settings.ocr_timeout_seconds
    while time.monotonic() < deadline:
        status_request = Request(status_url, method="GET")
        try:
            status_payload = _read_json(status_request, timeout_seconds=min(30.0, settings.ocr_timeout_seconds))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"OCR backend status check failed: {exc}") from exc

        data = status_payload.get("data") if isinstance(status_payload.get("data"), dict) else {}
        task_status = str(data.get("status") or "")
        if task_status == "completed":
            markdown = str(data.get("full_markdown") or data.get("raw_markdown") or data.get("export_markdown") or "")
            page_markdowns = data.get("page_markdowns") or data.get("raw_page_markdowns") or []
            return {
                "task_id": task_id,
                "markdown": markdown,
                "page_markdowns": page_markdowns if isinstance(page_markdowns, list) else [],
                "layout": data.get("layout"),
            }
        if task_status in {"failed", "cancelled"}:
            raise RuntimeError(str(data.get("error_message") or f"OCR task {task_id} {task_status}"))
        time.sleep(settings.ocr_poll_interval_seconds)

    raise TimeoutError(f"OCR task {task_id} did not complete within {settings.ocr_timeout_seconds} seconds")


__all__ = ["parse_document_with_ocr"]