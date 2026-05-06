"""E2E tests for API key authentication on MCP group endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from httpx import AsyncClient

from hub.auth.api_keys import generate_api_key, hash_key
from hub.mcp.router import McpRouter


class TestApiKeyCreationAndUsage:
    async def _setup_group_with_key(
        self, client: AsyncClient, admin_headers: dict[str, str], group_name: str
    ) -> tuple[int, str]:
        """Create a group and return (group_id, plaintext_key)."""
        resp = await client.post(
            "/api/v1/groups",
            json={"name": group_name, "require_api_key": True},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        group_id = resp.json()["data"]["id"]

        key_resp = await client.post(
            "/api/v1/keys",
            json={"label": "test key", "group_id": group_id},
            headers=admin_headers,
        )
        assert key_resp.status_code == 201
        plaintext = key_resp.json()["data"]["plaintext_key"]
        return group_id, plaintext

    async def test_valid_api_key_in_bearer_header(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        _group_id, plaintext = await self._setup_group_with_key(client, auth_headers, "bearer-grp")

        mock_pm = MagicMock()
        mock_pm.list_running.return_value = []
        mock_pm._mcp_router = McpRouter(mock_pm)
        with patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm):
            resp = await client.post(
                "/mcp/bearer-grp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers={"Authorization": f"Bearer {plaintext}"},
            )
        assert resp.status_code == 200

    async def test_valid_api_key_in_query_param(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        _group_id, plaintext = await self._setup_group_with_key(client, auth_headers, "query-grp")

        mock_pm = MagicMock()
        mock_pm.list_running.return_value = []
        mock_pm._mcp_router = McpRouter(mock_pm)
        with patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm):
            resp = await client.post(
                f"/mcp/query-grp?api_key={plaintext}",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
        assert resp.status_code == 200

    async def test_invalid_api_key_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await self._setup_group_with_key(client, auth_headers, "reject-grp")

        mock_pm = MagicMock()
        mock_pm.list_running.return_value = []
        mock_pm._mcp_router = McpRouter(mock_pm)
        with patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm):
            resp = await client.post(
                "/mcp/reject-grp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers={"Authorization": "Bearer totally-wrong-key"},
            )
        assert resp.status_code == 401

    async def test_revoked_key_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        _group_id, plaintext = await self._setup_group_with_key(
            client,
            auth_headers,
            "revoke-test-grp",
        )

        # Get the key id
        keys_resp = await client.get("/api/v1/keys", headers=auth_headers)
        key_id = keys_resp.json()["data"][0]["id"]

        # Revoke it
        await client.delete(f"/api/v1/keys/{key_id}", headers=auth_headers)

        mock_pm = MagicMock()
        mock_pm.list_running.return_value = []
        mock_pm._mcp_router = McpRouter(mock_pm)
        with patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm):
            resp = await client.post(
                "/mcp/revoke-test-grp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers={"Authorization": f"Bearer {plaintext}"},
            )
        assert resp.status_code == 401

    async def test_no_auth_required_for_open_group(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Groups without require_api_key should be accessible without a key."""
        await client.post(
            "/api/v1/groups",
            json={"name": "open-grp", "require_api_key": False},
            headers=auth_headers,
        )

        mock_pm = MagicMock()
        mock_pm.list_running.return_value = []
        mock_pm._mcp_router = McpRouter(mock_pm)
        with patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm):
            resp = await client.post(
                "/mcp/open-grp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
        assert resp.status_code == 200

    async def test_group_with_assigned_key_requires_auth_even_when_flag_false(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        group_resp = await client.post(
            "/api/v1/groups",
            json={"name": "keyed-open-grp", "require_api_key": False},
            headers=auth_headers,
        )
        assert group_resp.status_code == 201
        group_id = group_resp.json()["data"]["id"]
        key_resp = await client.post(
            "/api/v1/keys",
            json={"label": "group key", "group_id": group_id},
            headers=auth_headers,
        )
        assert key_resp.status_code == 201
        plaintext = key_resp.json()["data"]["plaintext_key"]

        mock_pm = MagicMock()
        mock_pm.list_running.return_value = []
        mock_pm._mcp_router = McpRouter(mock_pm)
        with patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm):
            no_key = await client.post(
                "/mcp/keyed-open-grp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            valid_key = await client.post(
                "/mcp/keyed-open-grp",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                headers={"Authorization": f"Bearer {plaintext}"},
            )
        assert no_key.status_code == 401
        assert valid_key.status_code == 200

    async def test_server_scoped_api_key_authorises_single_server_endpoint(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        server_resp = await client.post(
            "/api/v1/servers",
            json={"name": "keyed-server", "path": "keyed-server"},
            headers=auth_headers,
        )
        assert server_resp.status_code == 201
        server_id = server_resp.json()["data"]["id"]

        key_resp = await client.post(
            "/api/v1/keys",
            json={"label": "server key", "server_id": server_id},
            headers=auth_headers,
        )
        assert key_resp.status_code == 201
        plaintext = key_resp.json()["data"]["plaintext_key"]
        assert key_resp.json()["data"]["server_id"] == server_id
        assert key_resp.json()["data"]["group_id"] is None

        mock_pm = MagicMock()
        mock_pm.list_running.return_value = []
        mock_pm._mcp_router = McpRouter(mock_pm)
        with patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm):
            resp = await client.post(
                "/mcp/server/keyed-server",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers={"Authorization": f"Bearer {plaintext}"},
            )
        assert resp.status_code == 200

    async def test_server_with_assigned_key_requires_auth(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        server_resp = await client.post(
            "/api/v1/servers",
            json={"name": "server-key-required", "path": "server-key-required"},
            headers=auth_headers,
        )
        assert server_resp.status_code == 201
        server_id = server_resp.json()["data"]["id"]
        key_resp = await client.post(
            "/api/v1/keys",
            json={"label": "server key", "server_id": server_id},
            headers=auth_headers,
        )
        assert key_resp.status_code == 201
        plaintext = key_resp.json()["data"]["plaintext_key"]

        mock_pm = MagicMock()
        mock_pm.list_running.return_value = []
        mock_pm._mcp_router = McpRouter(mock_pm)
        with patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm):
            no_key = await client.post(
                "/mcp/server/server-key-required",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            valid_key = await client.post(
                "/mcp/server/server-key-required",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                headers={"Authorization": f"Bearer {plaintext}"},
            )
        assert no_key.status_code == 401
        assert valid_key.status_code == 200

    async def test_group_key_is_rejected_for_single_server_endpoint(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await client.post(
            "/api/v1/servers",
            json={"name": "server-key-reject", "path": "server-key-reject"},
            headers=auth_headers,
        )
        _group_id, plaintext = await self._setup_group_with_key(
            client,
            auth_headers,
            "server-reject-grp",
        )

        mock_pm = MagicMock()
        mock_pm.list_running.return_value = []
        mock_pm._mcp_router = McpRouter(mock_pm)
        with patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm):
            resp = await client.post(
                "/mcp/server/server-key-reject",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers={"Authorization": f"Bearer {plaintext}"},
            )
        assert resp.status_code == 403


class TestApiKeyHashSecurity:
    def test_plaintext_never_equal_to_stored_hash(self) -> None:
        plaintext, key_hash, _ = generate_api_key()
        assert plaintext != key_hash

    def test_hash_is_sha256_length(self) -> None:
        _, key_hash, _ = generate_api_key()
        assert len(key_hash) == 64

    def test_verification_uses_hash(self) -> None:
        plaintext, expected_hash, _ = generate_api_key()
        assert hash_key(plaintext) == expected_hash
        assert hash_key("wrong") != expected_hash
