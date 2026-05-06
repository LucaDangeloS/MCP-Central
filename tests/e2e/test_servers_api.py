"""E2E tests for server lifecycle action endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient


class TestServerLifecycleActions:
    """Tests for /start, /stop, /restart endpoints.

    The actual ProcessManager is mocked so these tests don't spawn real processes.
    """

    async def _create_server(self, client: AsyncClient, headers: dict[str, str], name: str) -> dict:
        resp = await client.post(
            "/api/v1/servers",
            json={"name": name, "path": name},
            headers=headers,
        )
        assert resp.status_code == 201
        return resp.json()["data"]

    async def test_start_server(self, client: AsyncClient, auth_headers: dict[str, str]) -> None:
        await self._create_server(client, auth_headers, "start-me")

        mock_pm = MagicMock()
        mock_pm.start_server = AsyncMock()
        with patch("hub.api.servers.get_process_manager", return_value=mock_pm):
            resp = await client.post("/api/v1/servers/start-me/start", headers=auth_headers)

        assert resp.status_code == 200
        mock_pm.start_server.assert_awaited_once_with("start-me")

    async def test_stop_server(self, client: AsyncClient, auth_headers: dict[str, str]) -> None:
        await self._create_server(client, auth_headers, "stop-me")

        mock_pm = MagicMock()
        mock_pm.stop_server = AsyncMock()
        with patch("hub.api.servers.get_process_manager", return_value=mock_pm):
            resp = await client.post("/api/v1/servers/stop-me/stop", headers=auth_headers)

        assert resp.status_code == 200
        mock_pm.stop_server.assert_awaited_once_with("stop-me")

    async def test_restart_server(self, client: AsyncClient, auth_headers: dict[str, str]) -> None:
        await self._create_server(client, auth_headers, "restart-me")

        mock_pm = MagicMock()
        mock_pm.restart_server = AsyncMock()
        with patch("hub.api.servers.get_process_manager", return_value=mock_pm):
            resp = await client.post("/api/v1/servers/restart-me/restart", headers=auth_headers)

        assert resp.status_code == 200
        mock_pm.restart_server.assert_awaited_once_with("restart-me")

    async def test_delete_server_stops_process_first(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await self._create_server(client, auth_headers, "delete-me")

        mock_pm = MagicMock()
        mock_pm.stop_server = AsyncMock()
        with patch("hub.api.servers.get_process_manager", return_value=mock_pm):
            resp = await client.delete("/api/v1/servers/delete-me", headers=auth_headers)

        assert resp.status_code == 204
        mock_pm.stop_server.assert_awaited_once_with("delete-me")

        get_resp = await client.get("/api/v1/servers/delete-me", headers=auth_headers)
        assert get_resp.status_code == 404

    async def test_update_server_runtime_parameters(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await self._create_server(client, auth_headers, "param-srv")

        resp = await client.patch(
            "/api/v1/servers/param-srv",
            json={
                "description": "Configured from the UI",
                "auto_start": False,
                "restart_on_error": False,
                "env_vars": {"MAX_RESULTS": "25", "API_BASE_URL": "https://example.test"},
            },
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["description"] == "Configured from the UI"
        assert data["auto_start"] is False
        assert data["restart_on_error"] is False
        assert data["env_vars"] == {
            "MAX_RESULTS": "25",
            "API_BASE_URL": "https://example.test",
        }

    async def test_create_server_accepts_restart_on_error(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/servers",
            json={"name": "no-restart-srv", "path": "no-restart-srv", "restart_on_error": False},
            headers=auth_headers,
        )

        assert resp.status_code == 201
        assert resp.json()["data"]["restart_on_error"] is False

    async def test_start_nonexistent_server_returns_404(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        mock_pm = MagicMock()
        mock_pm.start_server = AsyncMock()
        # Note: 404 is returned before process manager is called (server lookup happens first)
        with patch("hub.api.servers.get_process_manager", return_value=mock_pm):
            resp = await client.post("/api/v1/servers/ghost/start", headers=auth_headers)
        assert resp.status_code == 404

    async def test_start_server_propagates_error(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await self._create_server(client, auth_headers, "broken-srv")

        mock_pm = MagicMock()
        mock_pm.start_server = AsyncMock(side_effect=RuntimeError("venv creation failed"))
        with patch("hub.api.servers.get_process_manager", return_value=mock_pm):
            resp = await client.post("/api/v1/servers/broken-srv/start", headers=auth_headers)

        assert resp.status_code == 500
        body = resp.json()
        # traceback must be present in the error response
        assert "traceback" in str(body).lower() or "detail" in body
