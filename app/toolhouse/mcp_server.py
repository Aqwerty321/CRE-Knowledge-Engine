from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

from mcp.server.transport_security import TransportSecuritySettings
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.config import get_settings
from app.toolhouse.tools import (
    aggregate_properties_tool,
    audit_data_tool,
    explain_evidence_tool,
    explain_query_tool,
    get_source_detail_tool,
    nearby_properties_tool,
    search_properties_tool,
    search_source_chunks_tool,
)


MCP_INSTRUCTIONS = """
CRE Backend MCP is the read-only evidence and retrieval surface for the CRE MCP Look Deeper Analyst.
Use these tools for all CRE facts, source details, query explanation, aggregation, chunk search, proximity, audit state, and citation grounding.
Never treat Toolhouse memory, Slack search, web search, scraping, downloaded files, or vision output as final CRE evidence unless backend MCP evidence also supports it.
""".strip()


def _mcp_transport_security() -> TransportSecuritySettings:
    allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    allowed_origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]

    settings = get_settings()
    if settings.public_callback_url:
        parsed_url = urlparse(settings.public_callback_url)
        if parsed_url.hostname:
            allowed_hosts.extend([parsed_url.hostname, f"{parsed_url.hostname}:*"])
            if parsed_url.scheme:
                origin = f"{parsed_url.scheme}://{parsed_url.hostname}"
                allowed_origins.extend([origin, f"{origin}:*"])

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, bearer_token: str | None) -> None:
        super().__init__(app)
        self._bearer_token = bearer_token

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if not self._bearer_token:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "mcp_auth_not_configured",
                    "detail": "Set CRE_TOOLHOUSE_MCP_BEARER_TOKEN before exposing the MCP endpoint.",
                },
            )

        authorization = request.headers.get("authorization")
        expected = f"Bearer {self._bearer_token}"
        url_token = request.query_params.get("mcp_token") or request.query_params.get("token")
        if authorization != expected and url_token != self._bearer_token:
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        return await call_next(request)


def create_cre_mcp_server() -> FastMCP:
    mcp = FastMCP(
        name="CRE Backend MCP",
        instructions=MCP_INSTRUCTIONS,
        stateless_http=True,
        json_response=True,
        transport_security=_mcp_transport_security(),
    )

    @mcp.tool()
    async def explain_evidence(query_id: str) -> dict[str, Any]:
        """Return the stored query package, allowed evidence IDs, evidence bundle, and decision summary."""
        return await explain_evidence_tool(query_id)

    @mcp.tool()
    async def explain_query(query_id: str) -> dict[str, Any]:
        """Explain route mode, reason codes, filters, answer snapshot, evidence, and missing-data state."""
        return await explain_query_tool(query_id)

    @mcp.tool()
    async def search_properties(filters: dict[str, Any]) -> dict[str, Any]:
        """Search normalized property records with structured filters and source provenance."""
        return await search_properties_tool(filters)

    @mcp.tool()
    async def get_source_detail(source_id: str) -> dict[str, Any]:
        """Return source metadata, chunks, and property records for one source document."""
        return await get_source_detail_tool(source_id)

    @mcp.tool()
    async def aggregate_properties(
        filters: dict[str, Any],
        group_by: str | None = None,
        metrics: list[str] | None = None,
    ) -> dict[str, Any]:
        """Compute backend-owned counts, square-footage totals, rent averages, and rent ranges."""
        return await aggregate_properties_tool(filters, group_by=group_by, metrics=metrics)

    @mcp.tool()
    async def search_source_chunks(query: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Search source chunks, raw source text, file names, and joined property context with keyword matching."""
        return await search_source_chunks_tool(query, filters=filters)

    @mcp.tool()
    async def nearby_properties(origin: dict[str, Any] | str, radius_miles: float, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Rank properties near coordinates or a known property address using backend distance calculations."""
        return await nearby_properties_tool(origin, radius_miles=radius_miles, filters=filters)

    @mcp.tool()
    async def audit_data() -> dict[str, Any]:
        """Return corpus completeness, missing fields, conflict groups, and bounded Toolhouse readiness state."""
        return await audit_data_tool()

    return mcp


def create_mcp_asgi_app(*, bearer_token: str | None = None) -> Starlette:
    settings = get_settings()
    token = bearer_token if bearer_token is not None else settings.toolhouse_mcp_bearer_token
    mcp_app = create_cre_mcp_server().streamable_http_app()
    mcp_app.add_middleware(BearerAuthMiddleware, bearer_token=token)
    return mcp_app


__all__ = ["BearerAuthMiddleware", "create_cre_mcp_server", "create_mcp_asgi_app"]