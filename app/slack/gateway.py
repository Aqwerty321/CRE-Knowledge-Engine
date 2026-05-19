from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from slack_sdk.web.async_client import AsyncWebClient

from app.config import get_settings


@dataclass
class SlackGateway:
    client: AsyncWebClient | None = None

    async def post_thread_reply(
        self,
        *,
        channel_id: str,
        thread_ts: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if self.client is None:
            return {"ok": False, "delivery": "skipped", "ts": thread_ts}

        response = await self.client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=text,
            blocks=blocks,
        )
        return dict(response.data)

    async def post_channel_message(
        self,
        *,
        channel_id: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if self.client is None:
            return {"ok": False, "delivery": "skipped", "ts": ""}

        response = await self.client.chat_postMessage(
            channel=channel_id,
            text=text,
            blocks=blocks,
        )
        return dict(response.data)

    async def post_ephemeral(
        self,
        *,
        channel_id: str,
        user_id: str,
        thread_ts: str | None = None,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if self.client is None:
            return {"ok": False, "delivery": "skipped"}

        response = await self.client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            thread_ts=thread_ts,
            text=text,
            blocks=blocks,
        )
        return dict(response.data)

    async def update_message(
        self,
        *,
        channel_id: str,
        message_ts: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if self.client is None:
            return {"ok": False, "delivery": "skipped", "ts": message_ts}

        response = await self.client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=text,
            blocks=blocks,
        )
        return dict(response.data)


@dataclass
class RecordingSlackGateway(SlackGateway):
    thread_replies: list[dict[str, Any]] = field(default_factory=list)
    ephemeral_replies: list[dict[str, Any]] = field(default_factory=list)
    updated_messages: list[dict[str, Any]] = field(default_factory=list)

    async def post_thread_reply(
        self,
        *,
        channel_id: str,
        thread_ts: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        message_ts = f"{thread_ts}-reply-{len(self.thread_replies) + 1}"
        payload = {
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "text": text,
            "blocks": blocks or [],
            "ts": message_ts,
        }
        self.thread_replies.append(payload)
        return {"ok": True, **payload}

    async def post_channel_message(
        self,
        *,
        channel_id: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        message_ts = f"channel-reply-{len(self.thread_replies) + 1}"
        payload = {
            "channel_id": channel_id,
            "thread_ts": "",
            "text": text,
            "blocks": blocks or [],
            "ts": message_ts,
        }
        self.thread_replies.append(payload)
        return {"ok": True, **payload}

    async def post_ephemeral(
        self,
        *,
        channel_id: str,
        user_id: str,
        thread_ts: str | None = None,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "channel_id": channel_id,
            "user_id": user_id,
            "thread_ts": thread_ts,
            "text": text,
            "blocks": blocks or [],
        }
        self.ephemeral_replies.append(payload)
        return {"ok": True, **payload}

    async def update_message(
        self,
        *,
        channel_id: str,
        message_ts: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        for payload in self.thread_replies:
            if payload["channel_id"] == channel_id and payload["ts"] == message_ts:
                payload["text"] = text
                payload["blocks"] = blocks or []
                self.updated_messages.append({"channel_id": channel_id, "ts": message_ts, "text": text, "blocks": blocks or []})
                return {"ok": True, **payload}
        raise ValueError(f"message not found for update: {channel_id} {message_ts}")


@lru_cache(maxsize=1)
def get_slack_gateway() -> SlackGateway:
    settings = get_settings()
    if settings.slack_bot_token:
        return SlackGateway(client=AsyncWebClient(token=settings.slack_bot_token))
    return SlackGateway(client=None)


__all__ = ["RecordingSlackGateway", "SlackGateway", "get_slack_gateway"]