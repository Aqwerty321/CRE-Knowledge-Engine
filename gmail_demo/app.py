from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from gmail_demo.mcp_server import create_mcp_asgi_app


def create_app(*, token: str | None = None) -> FastAPI:
    mcp_app = create_mcp_asgi_app(token=token)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    application = FastAPI(
        title="Gmail CRE Demo Backend",
        description="Standalone Toolhouse MCP backend for the Google Sheets demo.",
        lifespan=lifespan,
    )
    application.mount("/toolhouse", mcp_app, name="gmail-demo-mcp")

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "database": "google_sheets", "orchestrator": "toolhouse"}

    @application.get("/")
    async def root() -> dict[str, str]:
        return {
            "app": "Gmail CRE Demo Backend",
            "mcp_endpoint": "/toolhouse/mcp",
            "health": "/health",
        }

    return application


app = create_app()
