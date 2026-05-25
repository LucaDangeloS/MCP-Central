"""E2E tests for runtime configuration endpoints."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from httpx import AsyncClient


class TestRuntimeConfig:
    async def test_config_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/config")

        assert resp.status_code == 401

    async def test_config_returns_request_url_by_default(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = await client.get("/api/v1/config", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json()["data"]["service_url"] == "http://test"

    async def test_config_returns_configured_service_url(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        with patch(
            "hub.api.config.get_settings",
            return_value=SimpleNamespace(service_url="https://mcp.example.test"),
        ):
            resp = await client.get("/api/v1/config", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json()["data"]["service_url"] == "https://mcp.example.test"
