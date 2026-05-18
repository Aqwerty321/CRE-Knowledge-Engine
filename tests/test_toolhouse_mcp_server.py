from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.toolhouse.mcp_server import create_cre_mcp_server, create_mcp_asgi_app


def test_cre_mcp_server_registers_expected_tools() -> None:
    async def collect_tool_names() -> set[str]:
        tools = await create_cre_mcp_server().list_tools()
        return {tool.name for tool in tools}

    tool_names = asyncio.run(collect_tool_names())

    assert tool_names == {
        "explain_evidence",
        "explain_query",
        "search_properties",
        "get_source_detail",
        "aggregate_properties",
        "search_source_chunks",
        "nearby_properties",
        "audit_data",
    }


def test_mcp_asgi_app_requires_configured_bearer_token() -> None:
    client = TestClient(create_mcp_asgi_app(bearer_token=""))

    response = client.post("/mcp", json={})

    assert response.status_code == 503
    assert response.json()["error"] == "mcp_auth_not_configured"


def test_mcp_asgi_app_rejects_missing_or_wrong_bearer_token() -> None:
    client = TestClient(create_mcp_asgi_app(bearer_token="secret-token"))

    missing_response = client.post("/mcp", json={})
    wrong_response = client.post("/mcp", headers={"Authorization": "Bearer wrong"}, json={})

    assert missing_response.status_code == 401
    assert wrong_response.status_code == 401


def test_mcp_asgi_app_accepts_url_token_for_url_only_clients() -> None:
    with TestClient(create_mcp_asgi_app(bearer_token="secret-token")) as client:
        response = client.post("/mcp?mcp_token=secret-token", json={})

    assert response.status_code not in {401, 503}


def test_mounted_mcp_app_initializes_session_manager(monkeypatch) -> None:
    monkeypatch.setenv("CRE_TOOLHOUSE_MCP_BEARER_TOKEN", "secret-token")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.post("/toolhouse/mcp?mcp_token=secret-token", headers={"host": "localhost:8020"}, json={})

    get_settings.cache_clear()
    assert response.status_code not in {401, 421, 500, 503}


def test_mounted_mcp_app_allows_configured_public_host(monkeypatch) -> None:
    monkeypatch.setenv("CRE_TOOLHOUSE_MCP_BEARER_TOKEN", "secret-token")
    monkeypatch.setenv("CLOUDFLARE_PUBLIC_CALLBACK_URL", "https://slack.aqwerty321.me")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.post(
            "/toolhouse/mcp?mcp_token=secret-token",
            headers={"host": "slack.aqwerty321.me"},
            json={},
        )

    get_settings.cache_clear()
    assert response.status_code not in {401, 421, 500, 503}