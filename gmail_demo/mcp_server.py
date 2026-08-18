from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from gmail_demo.service import (
    compose_property_query_reply as compose_property_query_reply_service,
    compose_requirement_reply as compose_requirement_reply_service,
    describe_demo_contract as describe_demo_contract_service,
    get_seed_properties as get_seed_properties_service,
    match_requirement as match_requirement_service,
    search_property_knowledge as search_property_knowledge_service,
    validate_listing_event as validate_listing_event_service,
    validate_property_delete as validate_property_delete_service,
    validate_requirement_event as validate_requirement_event_service,
)


MCP_INSTRUCTIONS = """
This is the narrow deterministic backend for the Gmail CRE demo.
Google Sheets is the demo database. The Toolhouse Worker reads Gmail and Google Sheets with its connected tools.
Use get_seed_properties once when the Properties worksheet has zero data rows. Otherwise use this MCP to validate extracted listing/requirement/delete data, retrieve BM25-ranked evidence from rows already read from the Properties worksheet, match a requirement, and compose grounded Gmail reply payloads.
Always call validate_listing_event with an explicit create/update operation and the current Properties rows before writing listing rows. Use its returned full sheet_headers, sheet_rows, and sheet_key_column. Never upsert a listing by property_name.
Always call validate_property_delete before deleting. Delete only the one exact property_id returned by that tool.
Always call validate_requirement_event, then match_requirement, then compose_requirement_reply for a tenant requirement.
Use search_property_knowledge and then compose_property_query_reply for ad hoc property questions. Search uses BM25 lexical retrieval and exact CRE aliases; it does not use embeddings or a reranker.
Use gmail_message_id as the idempotency key in the ProcessedEmails worksheet.
Ignore signatures, disclaimers, quoted history, unsubscribe text, and tracking content during extraction.
UNKNOWN is not FIT. An automatic reply is authorized only when compose_requirement_reply returns ok=true and send_automatically=true. The authorized demo recipient is aadityasoni2020@gmail.com in the original [CRE-DEMO] thread.
""".strip()


def _transport_security() -> TransportSecuritySettings:
    allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", "testserver"]
    allowed_origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    public_url = os.getenv("GMAIL_DEMO_PUBLIC_URL", "").strip()
    if public_url:
        parsed = urlparse(public_url)
        if parsed.hostname:
            allowed_hosts.extend([parsed.hostname, f"{parsed.hostname}:*"])
            if parsed.scheme:
                origin = f"{parsed.scheme}://{parsed.hostname}"
                allowed_origins.extend([origin, f"{origin}:*"])
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


class TokenAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, token: str | None) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if not self._token:
            return JSONResponse(
                status_code=503,
                content={"error": "mcp_auth_not_configured", "detail": "Set GMAIL_DEMO_MCP_TOKEN."},
            )
        supplied = request.query_params.get("token") or request.query_params.get("mcp_token")
        authorization = request.headers.get("authorization")
        if supplied != self._token and authorization != f"Bearer {self._token}":
            return JSONResponse(status_code=401, content={"error": "unauthorized"})
        return await call_next(request)


def create_demo_mcp_server() -> FastMCP:
    mcp = FastMCP(
        name="Gmail CRE Demo MCP",
        instructions=MCP_INSTRUCTIONS,
        stateless_http=True,
        json_response=True,
        transport_security=_transport_security(),
    )

    @mcp.tool()
    def describe_demo_contract() -> dict[str, Any]:
        """Return the required worksheet names, columns, event types, keys, and workflow rules."""
        return describe_demo_contract_service()

    @mcp.tool()
    def get_seed_properties() -> dict[str, Any]:
        """Return the 30 deterministic demo rows; write them only when Properties is empty."""
        return get_seed_properties_service()

    @mcp.tool()
    def validate_listing_event(
        event: dict[str, Any],
        existing_properties: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Resolve stable IDs and normalize listing email data into complete Sheet upsert rows."""
        return validate_listing_event_service(event, existing_properties=existing_properties)

    @mcp.tool()
    def validate_property_delete(
        event: dict[str, Any],
        existing_properties: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Resolve one explicit delete command to exactly one stable property_id."""
        return validate_property_delete_service(event, existing_properties=existing_properties)

    @mcp.tool()
    def validate_requirement_event(event: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalize one tenant-requirement email before matching."""
        return validate_requirement_event_service(event)

    @mcp.tool()
    def search_property_knowledge(
        query: str,
        properties: list[dict[str, Any]],
        limit: int = 10,
    ) -> dict[str, Any]:
        """BM25-search supplied Sheet rows and return source-backed property evidence cards."""
        return search_property_knowledge_service(query, properties, limit=limit)

    @mcp.tool()
    def match_requirement(
        requirement: dict[str, Any],
        properties: list[dict[str, Any]],
        limit: int = 5,
        query: str = "",
    ) -> dict[str, Any]:
        """BM25-retrieve and deterministically rank Sheet rows as FIT, UNKNOWN, or NO_FIT."""
        return match_requirement_service(requirement, properties, limit=limit, query=query)

    @mcp.tool()
    def compose_requirement_reply(
        requirement: dict[str, Any],
        matches: list[dict[str, Any]],
        sender_name: str = "",
    ) -> dict[str, Any]:
        """Create an authorized grounded reply payload; the Toolhouse Gmail tool performs the send."""
        return compose_requirement_reply_service(requirement, matches, sender_name=sender_name)

    @mcp.tool()
    def compose_property_query_reply(
        query: str,
        source_message_id: str,
        source_thread_id: str,
        source_subject: str,
        requester_email: str,
        results: list[dict[str, Any]],
        sender_name: str = "",
        exact_property_name: str = "",
        exact_suite: str = "",
    ) -> dict[str, Any]:
        """Create an authorized evidence-only reply, optionally scoped to one exact property/suite."""
        return compose_property_query_reply_service(
            query=query,
            source_message_id=source_message_id,
            source_thread_id=source_thread_id,
            source_subject=source_subject,
            requester_email=requester_email,
            results=results,
            sender_name=sender_name,
            exact_property_name=exact_property_name,
            exact_suite=exact_suite,
        )

    return mcp


def create_mcp_asgi_app(*, token: str | None = None) -> Starlette:
    configured_token = token if token is not None else os.getenv("GMAIL_DEMO_MCP_TOKEN")
    mcp_app = create_demo_mcp_server().streamable_http_app()
    mcp_app.add_middleware(TokenAuthMiddleware, token=configured_token)
    return mcp_app


__all__ = ["MCP_INSTRUCTIONS", "TokenAuthMiddleware", "create_demo_mcp_server", "create_mcp_asgi_app"]
