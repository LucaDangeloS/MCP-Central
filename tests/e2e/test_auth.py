"""E2E tests for admin authentication endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


class TestTokenEndpoint:
    async def test_login_happy_path(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/token",
            data={"username": "admin", "password": "testpassword"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["token_type"] == "bearer"

    async def test_login_wrong_password(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/token",
            data={"username": "admin", "password": "wrong"},
        )
        assert resp.status_code == 401
        assert "detail" in resp.json()

    async def test_login_wrong_username(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/token",
            data={"username": "hacker", "password": "testpassword"},
        )
        assert resp.status_code == 401

    async def test_protected_endpoint_without_token(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/servers")
        assert resp.status_code == 401

    async def test_protected_endpoint_with_token(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get("/api/v1/servers", headers=auth_headers)
        assert resp.status_code == 200

    async def test_protected_endpoint_with_invalid_token(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/servers",
            headers={"Authorization": "Bearer this.is.not.valid"},
        )
        assert resp.status_code == 401

    async def test_health_check_no_auth(self, client: AsyncClient) -> None:
        """Health endpoint must be accessible without authentication."""
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestServersCrud:
    async def test_list_servers_empty(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get("/api/v1/servers", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == []
        assert body["meta"]["total"] == 0

    async def test_create_server(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/servers",
            json={
                "name": "my-server",
                "path": "my-server",
                "description": "Test server",
                "entrypoint_module": "main",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["name"] == "my-server"
        assert data["status"] == "stopped"

    async def test_create_duplicate_server_fails(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        payload = {"name": "dup-server", "path": "dup-server"}
        await client.post("/api/v1/servers", json=payload, headers=auth_headers)
        resp = await client.post("/api/v1/servers", json=payload, headers=auth_headers)
        assert resp.status_code == 409

    async def test_get_server(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await client.post(
            "/api/v1/servers",
            json={"name": "get-me", "path": "get-me"},
            headers=auth_headers,
        )
        resp = await client.get("/api/v1/servers/get-me", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "get-me"

    async def test_get_nonexistent_server(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get("/api/v1/servers/ghost", headers=auth_headers)
        assert resp.status_code == 404

    async def test_update_server(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await client.post(
            "/api/v1/servers",
            json={"name": "patch-me", "path": "patch-me"},
            headers=auth_headers,
        )
        resp = await client.patch(
            "/api/v1/servers/patch-me",
            json={"description": "updated description"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["description"] == "updated description"

    async def test_delete_server(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await client.post(
            "/api/v1/servers",
            json={"name": "delete-me", "path": "delete-me"},
            headers=auth_headers,
        )
        from unittest.mock import patch, MagicMock
        mock_pm = MagicMock()
        with patch("hub.process.health.get_process_manager", return_value=mock_pm):
            resp = await client.delete("/api/v1/servers/delete-me", headers=auth_headers)
        assert resp.status_code == 204

        # Verify it's gone
        resp = await client.get("/api/v1/servers/delete-me", headers=auth_headers)
        assert resp.status_code == 404

    async def test_invalid_server_name_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/servers",
            json={"name": "UPPERCASE_INVALID", "path": "x"},
            headers=auth_headers,
        )
        assert resp.status_code == 422


class TestGroupsCrud:
    async def test_create_and_list_group(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/groups",
            json={"name": "my-group", "description": "A test group"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["name"] == "my-group"

        resp = await client.get("/api/v1/groups", headers=auth_headers)
        assert resp.json()["meta"]["total"] == 1

    async def test_group_require_api_key_flag(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/groups",
            json={"name": "locked-group", "require_api_key": True},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["require_api_key"] is True

    async def test_delete_group(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await client.post(
            "/api/v1/groups",
            json={"name": "bye-group"},
            headers=auth_headers,
        )
        resp = await client.delete("/api/v1/groups/bye-group", headers=auth_headers)
        assert resp.status_code == 204
        resp = await client.get("/api/v1/groups/bye-group", headers=auth_headers)
        assert resp.status_code == 404


class TestApiKeysCrud:
    async def _create_group(self, client: AsyncClient, headers: dict[str, str], name: str) -> int:
        resp = await client.post("/api/v1/groups", json={"name": name}, headers=headers)
        return resp.json()["data"]["id"]

    async def test_create_key_returns_plaintext_once(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        group_id = await self._create_group(client, auth_headers, "key-group")
        resp = await client.post(
            "/api/v1/keys",
            json={"label": "My Key", "group_id": group_id},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert "plaintext_key" in data
        assert len(data["plaintext_key"]) == 64

    async def test_list_keys_no_plaintext(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        group_id = await self._create_group(client, auth_headers, "list-key-group")
        await client.post(
            "/api/v1/keys",
            json={"label": "Listed Key", "group_id": group_id},
            headers=auth_headers,
        )
        resp = await client.get("/api/v1/keys", headers=auth_headers)
        assert resp.status_code == 200
        key = resp.json()["data"][0]
        assert "plaintext_key" not in key
        assert "key_prefix" in key

    async def test_revoke_key(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        group_id = await self._create_group(client, auth_headers, "revoke-key-group")
        create_resp = await client.post(
            "/api/v1/keys",
            json={"label": "Revokable", "group_id": group_id},
            headers=auth_headers,
        )
        key_id = create_resp.json()["data"]["id"]

        resp = await client.delete(f"/api/v1/keys/{key_id}", headers=auth_headers)
        assert resp.status_code == 204

    async def test_revoke_nonexistent_key(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.delete("/api/v1/keys/99999", headers=auth_headers)
        assert resp.status_code == 404
