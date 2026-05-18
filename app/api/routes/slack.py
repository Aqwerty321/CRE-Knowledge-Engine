from __future__ import annotations

from fastapi import APIRouter, Request

from app.slack.runtime import get_slack_handler, reset_slack_request_headers, set_slack_request_headers


router = APIRouter(tags=["slack"])


async def _handle_slack_request(request: Request):
    token = set_slack_request_headers(dict(request.headers))
    try:
        handler = get_slack_handler()
        return await handler.handle(request)
    finally:
        reset_slack_request_headers(token)


@router.post("/events")
async def slack_events(request: Request):
    return await _handle_slack_request(request)


@router.post("/interactivity")
async def slack_interactivity(request: Request):
    return await _handle_slack_request(request)