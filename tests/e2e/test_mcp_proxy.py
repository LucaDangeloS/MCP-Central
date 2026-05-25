"""E2E tests for the unified /mcp endpoint."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from hub.mcp.namespace import extract_server_name, namespace_tool_name
from hub.mcp.router import McpRouter

# ------------------------------------------------------------------ #
# Namespace unit tests                                                 #
# ------------------------------------------------------------------ #


class TestNamespacing:
    def test_namespace_tool_name(self) -> None:
        assert namespace_tool_name("my-server", "search") == "my-server__search"

    def test_extract_server_name(self) -> None:
        result = extract_server_name("my-server__search")
        assert result == ("my-server", "search")

    def test_extract_server_name_not_namespaced(self) -> None:
        assert extract_server_name("plain_tool") is None

    def test_extract_with_underscores_in_tool(self) -> None:
        result = extract_server_name("srv__get_user_info")
        assert result == ("srv", "get_user_info")

    def test_namespace_then_extract_roundtrip(self) -> None:
        server = "my-server"
        tool = "do_something_useful"
        namespaced = namespace_tool_name(server, tool)
        parsed = extract_server_name(namespaced)
        assert parsed == (server, tool)


# ------------------------------------------------------------------ #
# McpRouter unit tests                                                 #
# ------------------------------------------------------------------ #


class TestMcpRouter:
    def _make_router(self) -> tuple[McpRouter, MagicMock]:
        pm = MagicMock()
        pm.list_running.return_value = ["server-a", "server-b"]
        router = McpRouter(pm)
        return router, pm

    def test_register_and_list_tools(self) -> None:
        router, _ = self._make_router()
        router.register_tools("server-a", [{"name": "search"}, {"name": "fetch"}])
        router.register_tools("server-b", [{"name": "query"}])

        tools = router.get_all_namespaced_tools()
        names = [t["name"] for t in tools]
        assert "server-a__search" in names
        assert "server-a__fetch" in names
        assert "server-b__query" in names

    def test_hidden_tools_excluded(self) -> None:
        router, _ = self._make_router()
        router.register_tools("server-a", [{"name": "search"}, {"name": "internal"}])

        tools = router.get_all_namespaced_tools(hidden_tools=["server-a__internal"])
        names = [t["name"] for t in tools]
        assert "server-a__search" in names
        assert "server-a__internal" not in names

    def test_group_filter(self) -> None:
        router, _ = self._make_router()
        router.register_tools("server-a", [{"name": "tool1"}])
        router.register_tools("server-b", [{"name": "tool2"}])

        tools = router.get_all_namespaced_tools(group_server_names=["server-a"])
        names = [t["name"] for t in tools]
        assert "server-a__tool1" in names
        assert "server-b__tool2" not in names

    def test_stopped_server_tools_excluded(self) -> None:
        pm = MagicMock()
        pm.list_running.return_value = ["server-a"]  # server-b not running
        router = McpRouter(pm)
        router.register_tools("server-a", [{"name": "alive"}])
        router.register_tools("server-b", [{"name": "dead"}])

        tools = router.get_all_namespaced_tools()
        names = [t["name"] for t in tools]
        assert "server-a__alive" in names
        assert "server-b__dead" not in names

    async def test_route_tools_call_server_not_running(self) -> None:
        pm = MagicMock()
        pm.list_running.return_value = []
        router = McpRouter(pm)

        result = await router.route_tools_call("server-a__search", {}, 1, MagicMock())
        assert "error" in result
        assert result["error"]["code"] == -32001

    async def test_route_tools_call_not_namespaced(self) -> None:
        pm = MagicMock()
        router = McpRouter(pm)

        result = await router.route_tools_call("plain_tool", {}, 1, MagicMock())
        assert "error" in result
        assert result["error"]["code"] == -32602

    async def test_route_tools_call_error_includes_traceback(self) -> None:
        """When a server raises, the error response must include the full traceback."""
        from unittest.mock import AsyncMock
        pm = MagicMock()
        pm.list_running.return_value = ["server-a"]
        pm.send_jsonrpc = AsyncMock(side_effect=RuntimeError("server exploded"))
        router = McpRouter(pm)

        with patch("hub.mcp.router.record_tool_call") as record:
            result = await router.route_tools_call("server-a__tool", {}, 1, MagicMock())
        record.assert_awaited_once()
        assert "error" in result
        assert "traceback" in result["error"]["data"]
        assert "RuntimeError" in result["error"]["data"]["traceback"]
        # Traceback must name the server
        assert "server-a" in result["error"]["message"]


# ------------------------------------------------------------------ #
# E2E HTTP endpoint tests                                              #
# ------------------------------------------------------------------ #


class TestMcpHttpEndpoints:
    def _mock_pm_with_tools(self) -> MagicMock:
        pm = MagicMock()
        pm.list_running.return_value = ["srv-one"]
        pm._mcp_router = McpRouter(pm)
        pm._mcp_router.register_tools("srv-one", [{"name": "greet"}, {"name": "farewell"}])
        return pm

    async def test_initialize(self, client: AsyncClient) -> None:
        mock_pm = self._mock_pm_with_tools()
        with (
            patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm),
            patch("hub.api.servers.get_process_manager", return_value=mock_pm),
        ):
            resp = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["result"]["protocolVersion"] == "2025-03-26"
        assert body["result"]["serverInfo"]["name"] == "MCP Central Hub"

    async def test_streamable_http_post_can_return_sse(self, client: AsyncClient) -> None:
        mock_pm = self._mock_pm_with_tools()
        with (
            patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm),
            patch("hub.api.servers.get_process_manager", return_value=mock_pm),
        ):
            resp = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                headers={"Accept": "application/json, text/event-stream"},
            )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert "event: message" in resp.text
        assert '"protocolVersion":"2025-03-26"' in resp.text

    async def test_streamable_http_get_opens_sse(self, client: AsyncClient) -> None:
        resp = await client.get("/mcp", headers={"Accept": "text/event-stream"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert ": connected" in resp.text

    async def test_streamable_http_get_without_sse_accept_returns_405(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get("/mcp", headers={"Accept": "application/json"})
        assert resp.status_code == 405

    async def test_notifications_are_accepted_without_response(
        self,
        client: AsyncClient,
    ) -> None:
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        assert resp.status_code == 202
        assert resp.content == b""

    async def test_cross_origin_mcp_request_is_rejected(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Origin": "https://attacker.example"},
        )
        assert resp.status_code == 403

    async def test_ping(self, client: AsyncClient) -> None:
        mock_pm = self._mock_pm_with_tools()
        with (
            patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm),
            patch("hub.api.servers.get_process_manager", return_value=mock_pm),
        ):
            resp = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            )
        assert resp.status_code == 200
        assert resp.json()["result"] == {}

    async def test_tools_list_returns_namespaced_tools(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        await client.post(
            "/api/v1/servers",
            json={"name": "srv-one", "path": "srv-one"},
            headers=auth_headers,
        )
        mock_pm = self._mock_pm_with_tools()
        with patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm):
            resp = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
            )
        assert resp.status_code == 200
        tools = resp.json()["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "srv-one__greet" in names
        assert "srv-one__farewell" in names

    async def test_public_discovery_lists_protocol_and_endpoints(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        await client.post(
            "/api/v1/servers",
            json={"name": "discover-srv", "path": "discover-srv"},
            headers=auth_headers,
        )
        mock_pm = MagicMock()
        mock_pm.list_running.return_value = ["discover-srv"]
        mock_pm._mcp_router = McpRouter(mock_pm)
        mock_pm._mcp_router.register_tools("discover-srv", [{"name": "search"}])

        with patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm):
            resp = await client.get("/.well-known/mcp-central.json")
            mcp_resp = await client.get("/mcp", headers={"Accept": "text/event-stream"})

        assert resp.status_code == 200
        assert mcp_resp.status_code == 200
        body = resp.json()
        assert body["protocol"]["jsonrpc"] == "2.0"
        assert "tools/list" in body["protocol"]["methods"]
        assert body["endpoints"]["global"]["url"] == "http://test/mcp"
        assert body["servers"][0]["name"] == "discover-srv"
        assert body["servers"][0]["auth_required"] is False
        assert body["servers"][0]["tools"][0]["name"] == "discover-srv__search"

    async def test_global_endpoint_filters_keyed_servers_without_key(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        public_resp = await client.post(
            "/api/v1/servers",
            json={"name": "public-srv", "path": "public-srv"},
            headers=auth_headers,
        )
        assert public_resp.status_code == 201
        private_resp = await client.post(
            "/api/v1/servers",
            json={"name": "private-srv", "path": "private-srv"},
            headers=auth_headers,
        )
        assert private_resp.status_code == 201
        private_id = private_resp.json()["data"]["id"]
        key_resp = await client.post(
            "/api/v1/keys",
            json={"label": "private", "server_id": private_id},
            headers=auth_headers,
        )
        plaintext = key_resp.json()["data"]["plaintext_key"]

        mock_pm = MagicMock()
        mock_pm.list_running.return_value = ["public-srv", "private-srv"]
        mock_pm._mcp_router = McpRouter(mock_pm)
        mock_pm._mcp_router.register_tools("public-srv", [{"name": "search"}])
        mock_pm._mcp_router.register_tools("private-srv", [{"name": "search"}])

        with patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm):
            public_only = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            with_key = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                headers={"Authorization": f"Bearer {plaintext}"},
            )

        assert public_only.status_code == 200
        public_names = [t["name"] for t in public_only.json()["result"]["tools"]]
        assert "public-srv__search" in public_names
        assert "private-srv__search" not in public_names

        keyed_names = [t["name"] for t in with_key.json()["result"]["tools"]]
        assert "public-srv__search" in keyed_names
        assert "private-srv__search" in keyed_names

    async def test_tools_call_unknown_method_returns_error(self, client: AsyncClient) -> None:
        mock_pm = self._mock_pm_with_tools()
        with patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm):
            resp = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 4, "method": "unknown/method"},
            )
        assert resp.status_code == 200
        assert "error" in resp.json()
        assert resp.json()["error"]["code"] == -32601

    async def test_tools_call_records_usage_counts(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        await client.post(
            "/api/v1/servers",
            json={"name": "usage-srv", "path": "usage-srv"},
            headers=auth_headers,
        )
        mock_pm = MagicMock()
        mock_pm.list_running.return_value = ["usage-srv"]
        mock_pm.send_jsonrpc = AsyncMock(
            return_value=json.dumps({"jsonrpc": "2.0", "id": 7, "result": {"content": []}})
        )
        mock_pm._mcp_router = McpRouter(mock_pm)
        mock_pm._mcp_router.register_tools("usage-srv", [{"name": "search"}])

        with (
            patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm),
            patch("hub.api.servers.get_process_manager", return_value=mock_pm),
        ):
            first = await client.post(
                "/mcp/server/usage-srv",
                json={
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {"name": "usage-srv__search", "arguments": {"q": "one"}},
                },
            )
            second = await client.post(
                "/mcp/server/usage-srv",
                json={
                    "jsonrpc": "2.0",
                    "id": 8,
                    "method": "tools/call",
                    "params": {"name": "usage-srv__search", "arguments": {"q": "two"}},
                },
            )
            tools = await client.get("/api/v1/servers/usage-srv/tools", headers=auth_headers)

        stats = await client.get("/api/v1/stats", headers=auth_headers)

        assert first.status_code == 200
        assert second.status_code == 200
        assert tools.json()["data"][0]["call_count"] == 2
        assert stats.json()["data"]["tools"]["calls_by_server"] == {"usage-srv": 2}
        assert stats.json()["data"]["tools"]["total_calls"] == 2

    async def test_invalid_json_body_returns_parse_error(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/mcp",
            content=b"this is not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == -32700

    async def test_group_endpoint_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        mock_pm = self._mock_pm_with_tools()
        with patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm):
            resp = await client.post(
                "/mcp/nonexistent-group",
                json={"jsonrpc": "2.0", "id": 5, "method": "tools/list"},
            )
        assert resp.status_code == 404

    async def test_single_server_endpoint(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Register a server first
        await client.post(
            "/api/v1/servers",
            json={"name": "test-srv", "path": "test-srv"},
            headers=auth_headers,
        )
        mock_pm = self._mock_pm_with_tools()
        # Add test-srv to the mock
        mock_pm.list_running.return_value = ["test-srv", "srv-one"]
        mock_pm._mcp_router.register_tools("test-srv", [{"name": "do_thing"}])

        with patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm):
            resp = await client.post(
                "/mcp/server/test-srv",
                json={"jsonrpc": "2.0", "id": 6, "method": "tools/list"},
            )
        assert resp.status_code == 200
        names = [t["name"] for t in resp.json()["result"]["tools"]]
        assert "test-srv__do_thing" in names
        # Should NOT include srv-one tools (wrong scope)
        assert "srv-one__greet" not in names
