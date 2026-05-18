from __future__ import annotations

from contextvars import ContextVar, Token
from functools import lru_cache

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.starlette.async_handler import AsyncSlackRequestHandler
from slack_bolt.authorization.authorize_result import AuthorizeResult

from app.config import get_settings
from app.ingestion.slack_ingestor import enqueue_slack_ingestion_event
from app.slack.gateway import get_slack_gateway
from app.slack.service import enqueue_app_mention_event, handle_look_deeper_action, handle_show_sources_action

_request_headers_var: ContextVar[dict[str, str]] = ContextVar("slack_request_headers", default={})


def set_slack_request_headers(headers: dict[str, str]) -> Token[dict[str, str]]:
    normalized = {key.lower(): value for key, value in headers.items()}
    return _request_headers_var.set(normalized)


def reset_slack_request_headers(token: Token[dict[str, str]]) -> None:
    _request_headers_var.reset(token)


def get_current_slack_request_headers() -> dict[str, str]:
    return dict(_request_headers_var.get())


@lru_cache(maxsize=1)
def get_slack_app() -> AsyncApp:
    settings = get_settings()

    async def local_authorize(**kwargs) -> AuthorizeResult:
        return AuthorizeResult(
            enterprise_id=kwargs.get("enterprise_id"),
            team_id=kwargs.get("team_id"),
            bot_user_id="U_LOCAL_BOT",
            bot_id="B_LOCAL_BOT",
            bot_token=settings.slack_bot_token or "xoxb-local-placeholder",
        )

    slack_app = AsyncApp(
        process_before_response=True,
        signing_secret=settings.slack_signing_secret or "local-signing-secret",
        authorize=local_authorize,
    )

    @slack_app.event("app_mention")
    async def handle_app_mention(body: dict[str, object]) -> None:
        await enqueue_app_mention_event(body, get_current_slack_request_headers())

    @slack_app.event("message")
    async def handle_message_event(body: dict[str, object]) -> None:
        await enqueue_slack_ingestion_event(body, get_current_slack_request_headers())

    @slack_app.event("file_shared")
    async def handle_file_shared_event(body: dict[str, object]) -> None:
        await enqueue_slack_ingestion_event(body, get_current_slack_request_headers())

    @slack_app.action("show_sources")
    async def handle_show_sources(ack, body: dict[str, object], action: dict[str, object]) -> None:
        await ack()
        container = body.get("container", {}) if isinstance(body.get("container"), dict) else {}
        await handle_show_sources_action(
            query_id=str(action.get("value") or ""),
            channel_id=str(body.get("channel", {}).get("id") or ""),
            user_id=str(body.get("user", {}).get("id") or ""),
            thread_ts=str(container.get("thread_ts") or container.get("message_ts") or ""),
            slack_gateway=get_slack_gateway(),
        )

    @slack_app.action("look_deeper")
    async def handle_look_deeper(ack, body: dict[str, object], action: dict[str, object]) -> None:
        await ack()
        container = body.get("container", {}) if isinstance(body.get("container"), dict) else {}
        await handle_look_deeper_action(
            query_id=str(action.get("value") or ""),
            channel_id=str(body.get("channel", {}).get("id") or ""),
            user_id=str(body.get("user", {}).get("id") or ""),
            thread_ts=str(container.get("thread_ts") or container.get("message_ts") or ""),
            slack_gateway=get_slack_gateway(),
        )

    return slack_app


@lru_cache(maxsize=1)
def get_slack_handler() -> AsyncSlackRequestHandler:
    return AsyncSlackRequestHandler(get_slack_app())


__all__ = [
    "get_current_slack_request_headers",
    "get_slack_app",
    "get_slack_handler",
    "reset_slack_request_headers",
    "set_slack_request_headers",
]