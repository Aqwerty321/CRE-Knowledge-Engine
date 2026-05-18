from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.config import get_settings
from app.toolhouse.mcp_server import create_mcp_asgi_app
from app.workers import run_query_worker_loop


def create_app(
    *,
    enable_background_worker: bool = False,
    worker_poll_interval_seconds: float | None = None,
    worker_batch_limit: int | None = None,
) -> FastAPI:
    settings = get_settings()
    should_start_worker = bool(enable_background_worker and settings.slack_bot_token and settings.slack_ingest_channels)
    poll_interval = worker_poll_interval_seconds or settings.slack_worker_poll_interval_seconds
    batch_limit = worker_batch_limit or settings.slack_worker_batch_limit
    mcp_app = create_mcp_asgi_app()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        async with mcp_app.router.lifespan_context(mcp_app):
            if not should_start_worker:
                yield
                return

            stop_event = asyncio.Event()
            worker_task = asyncio.create_task(
                run_query_worker_loop(
                    stop_event=stop_event,
                    poll_interval_seconds=poll_interval,
                    batch_limit=batch_limit,
                )
            )
            application.state.slack_query_worker_task = worker_task
            application.state.slack_query_worker_enabled = True

            try:
                yield
            finally:
                stop_event.set()
                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass

    application = FastAPI(title=settings.app_name, lifespan=lifespan)
    application.include_router(api_router)
    application.mount("/toolhouse", mcp_app, name="toolhouse-mcp")

    @application.get("/", tags=["meta"])
    async def root() -> dict[str, str]:
        return {
            "app": settings.app_name,
            "env": settings.app_env,
        }

    return application


app = create_app(enable_background_worker=True)
