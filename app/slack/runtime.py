from __future__ import annotations

from contextvars import ContextVar, Token
from functools import lru_cache

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.starlette.async_handler import AsyncSlackRequestHandler
from slack_bolt.authorization.authorize_result import AuthorizeResult

from app.config import get_settings
from app.ingestion.slack_ingestor import enqueue_slack_ingestion_event
from app.slack.gateway import get_slack_gateway
from app.slack.service import (
    FOLLOW_UP_MODAL_REFRESH_ACTION_ID,
    enqueue_app_mention_event,
    handle_follow_up_modal_submission,
    handle_force_agent_action,
    handle_force_agent_command,
    handle_force_agent_message_shortcut,
    handle_look_deeper_action,
    handle_open_follow_up_modal_action,
    handle_refresh_follow_up_suggestions_action,
    handle_show_sources_action,
    validate_follow_up_modal_submission,
)

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

    @slack_app.command("/force-agent")
    async def handle_force_agent(ack, body: dict[str, object]) -> None:
        await ack()
        await handle_force_agent_command(
            query_text=str(body.get("text") or ""),
            channel_id=str(body.get("channel_id") or ""),
            user_id=str(body.get("user_id") or ""),
            team_id=str(body.get("team_id") or "") or None,
            thread_ts=str(body.get("thread_ts") or body.get("message_ts") or "") or None,
            query_ts=str(body.get("message_ts") or "") or None,
            slack_gateway=get_slack_gateway(),
        )

    @slack_app.shortcut("follow_up_agent_message_shortcut")
    async def handle_follow_up_shortcut(ack, body: dict[str, object]) -> None:
        await ack()
        message = body.get("message", {}) if isinstance(body.get("message"), dict) else {}
        await handle_force_agent_message_shortcut(
            message_payload=message,
            channel_id=str(body.get("channel", {}).get("id") or ""),
            user_id=str(body.get("user", {}).get("id") or ""),
            team_id=str(body.get("team", {}).get("id") or body.get("team_id") or "") or None,
            trigger_id=str(body.get("trigger_id") or "") or None,
            slack_gateway=get_slack_gateway(),
        )

    @slack_app.shortcut("force_agent_message_shortcut")
    async def handle_force_agent_shortcut(ack, body: dict[str, object]) -> None:
        await ack()
        message = body.get("message", {}) if isinstance(body.get("message"), dict) else {}
        await handle_force_agent_message_shortcut(
            message_payload=message,
            channel_id=str(body.get("channel", {}).get("id") or ""),
            user_id=str(body.get("user", {}).get("id") or ""),
            team_id=str(body.get("team", {}).get("id") or body.get("team_id") or "") or None,
            trigger_id=str(body.get("trigger_id") or "") or None,
            slack_gateway=get_slack_gateway(),
        )

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

    @slack_app.action("open_follow_up_modal")
    async def handle_open_follow_up(ack, body: dict[str, object], action: dict[str, object]) -> None:
        await ack()
        container = body.get("container", {}) if isinstance(body.get("container"), dict) else {}
        await handle_open_follow_up_modal_action(
            query_id=str(action.get("value") or ""),
            channel_id=str(body.get("channel", {}).get("id") or ""),
            user_id=str(body.get("user", {}).get("id") or ""),
            team_id=str(body.get("team", {}).get("id") or body.get("team_id") or "") or None,
            thread_ts=str(container.get("thread_ts") or container.get("message_ts") or ""),
            trigger_id=str(body.get("trigger_id") or ""),
            slack_gateway=get_slack_gateway(),
        )

    @slack_app.action(FOLLOW_UP_MODAL_REFRESH_ACTION_ID)
    async def handle_refresh_follow_up_suggestions(ack, body: dict[str, object], action: dict[str, object]) -> None:
        await ack()
        view = body.get("view", {}) if isinstance(body.get("view"), dict) else {}
        await handle_refresh_follow_up_suggestions_action(
            view=view,
            slack_gateway=get_slack_gateway(),
        )

    @slack_app.action("force_agent_query")
    async def handle_force_agent_query(ack, body: dict[str, object], action: dict[str, object]) -> None:
        await ack()
        container = body.get("container", {}) if isinstance(body.get("container"), dict) else {}
        await handle_force_agent_action(
            query_id=str(action.get("value") or ""),
            channel_id=str(body.get("channel", {}).get("id") or ""),
            user_id=str(body.get("user", {}).get("id") or ""),
            thread_ts=str(container.get("thread_ts") or container.get("message_ts") or ""),
            slack_gateway=get_slack_gateway(),
        )

    @slack_app.view("follow_up_agent_modal")
    async def handle_follow_up_view(ack, body: dict[str, object], view: dict[str, object]) -> None:
        validation_errors = validate_follow_up_modal_submission(view)
        if validation_errors:
            await ack(response_action="errors", errors=validation_errors)
            return
        await ack()
        await handle_follow_up_modal_submission(
            view=view,
            user_id=str(body.get("user", {}).get("id") or ""),
            team_id=str(body.get("team", {}).get("id") or body.get("team_id") or "") or None,
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