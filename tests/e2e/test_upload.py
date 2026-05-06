"""E2E tests for the ZIP upload and deployment endpoint."""

from __future__ import annotations

import io
import json
import zipfile

from httpx import AsyncClient


def _make_zip(
    *,
    manifest: dict | None = None,
    include_requirements: bool = True,
    include_pyproject: bool = False,
    include_entrypoint: bool = True,
    extra_files: dict[str, str] | None = None,
    dangerous_path: str | None = None,
) -> bytes:
    """Build an in-memory ZIP for testing."""
    if manifest is None:
        manifest = {
            "name": "test-server",
            "version": "1.0.0",
            "description": "A test server",
            "entrypoint": "main.py",
            "module": "main",
        }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        if include_requirements:
            zf.writestr("requirements.txt", "# no requirements\n")
        if include_pyproject:
            zf.writestr(
                "pyproject.toml",
                "[project]\nname = \"test-server\"\nversion = \"1.0.0\"\ndependencies = []\n",
            )
        if include_entrypoint:
            zf.writestr("main.py", "def main(): pass\n")
        if extra_files:
            for name, content in extra_files.items():
                zf.writestr(name, content)
        if dangerous_path:
            zf.writestr(dangerous_path, "malicious content")
    return buf.getvalue()


class TestUploadHappyPath:
    async def test_upload_valid_zip(
        self, client: AsyncClient, auth_headers: dict[str, str], tmp_path
    ) -> None:
        import os
        os.environ["SERVERS_DIR"] = str(tmp_path)
        import hub.config as cfg
        cfg.get_settings.cache_clear()

        data = _make_zip()
        resp = await client.post(
            "/api/v1/upload",
            files={"file": ("server.zip", data, "application/zip")},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        body = resp.json()["data"]
        assert body["server"]["name"] == "test-server"
        assert body["manifest"]["version"] == "1.0.0"
        assert "deployed successfully" in body["message"]

        cfg.get_settings.cache_clear()

    async def test_upload_creates_server_in_db(
        self, client: AsyncClient, auth_headers: dict[str, str], tmp_path
    ) -> None:
        import os

        import hub.config as cfg

        os.environ["SERVERS_DIR"] = str(tmp_path)
        cfg.get_settings.cache_clear()

        data = _make_zip(manifest={
            "name": "db-check-srv",
            "version": "2.0.0",
            "entrypoint": "main.py",
        })
        await client.post(
            "/api/v1/upload",
            files={"file": ("server.zip", data, "application/zip")},
            headers=auth_headers,
        )

        resp = await client.get("/api/v1/servers/db-check-srv", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "db-check-srv"

        cfg.get_settings.cache_clear()

    async def test_upload_accepts_pyproject_without_requirements(
        self, client: AsyncClient, auth_headers: dict[str, str], tmp_path
    ) -> None:
        import os

        import hub.config as cfg

        os.environ["SERVERS_DIR"] = str(tmp_path)
        cfg.get_settings.cache_clear()

        data = _make_zip(include_requirements=False, include_pyproject=True)
        resp = await client.post(
            "/api/v1/upload",
            files={"file": ("server.zip", data, "application/zip")},
            headers=auth_headers,
        )

        assert resp.status_code == 201
        body = resp.json()["data"]
        assert body["server"]["name"] == "test-server"
        assert (tmp_path / "test-server" / "pyproject.toml").exists()

        cfg.get_settings.cache_clear()


class TestSingleFileServerCreation:
    async def test_create_single_file_server(
        self, client: AsyncClient, auth_headers: dict[str, str], tmp_path
    ) -> None:
        import os

        import hub.config as cfg

        os.environ["SERVERS_DIR"] = str(tmp_path)
        cfg.get_settings.cache_clear()

        resp = await client.post(
            "/api/v1/upload/single-file",
            json={
                "name": "editor-srv",
                "description": "Created from editor",
                "code": "def main():\n    pass\n",
                "requirements": "mcp\n",
                "env_vars": {"MAX_RESULTS": "10"},
                "auto_start": False,
            },
            headers=auth_headers,
        )

        assert resp.status_code == 201
        body = resp.json()["data"]
        assert body["server"]["name"] == "editor-srv"
        assert body["server"]["description"] == "Created from editor"
        assert body["server"]["env_vars"] == {"MAX_RESULTS": "10"}
        assert body["server"]["auto_start"] is False
        assert body["manifest"]["entrypoint"] == "main.py"
        assert (
            (tmp_path / "editor-srv" / "main.py").read_text(encoding="utf-8")
            == "def main():\n    pass\n"
        )
        assert (
            (tmp_path / "editor-srv" / "requirements.txt").read_text(encoding="utf-8")
            == "mcp\n"
        )

        cfg.get_settings.cache_clear()

    async def test_create_single_file_rejects_duplicate_name(
        self, client: AsyncClient, auth_headers: dict[str, str], tmp_path
    ) -> None:
        import os

        import hub.config as cfg

        os.environ["SERVERS_DIR"] = str(tmp_path)
        cfg.get_settings.cache_clear()

        payload = {
            "name": "dupe-editor",
            "code": "def main():\n    pass\n",
            "auto_start": False,
        }
        first = await client.post("/api/v1/upload/single-file", json=payload, headers=auth_headers)
        assert first.status_code == 201

        second = await client.post("/api/v1/upload/single-file", json=payload, headers=auth_headers)
        assert second.status_code == 409

        cfg.get_settings.cache_clear()

    async def test_create_single_file_rejects_invalid_env_name(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/upload/single-file",
            json={
                "name": "invalid-env-srv",
                "code": "def main():\n    pass\n",
                "env_vars": {"BAD-NAME": "value"},
                "auto_start": False,
            },
            headers=auth_headers,
        )

        assert resp.status_code == 422


class TestUploadValidation:
    async def test_missing_manifest_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("main.py", "def main(): pass")
        resp = await client.post(
            "/api/v1/upload",
            files={"file": ("server.zip", buf.getvalue(), "application/zip")},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert "manifest.json" in resp.json()["detail"]

    async def test_invalid_server_name_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        data = _make_zip(manifest={
            "name": "INVALID NAME WITH SPACES",
            "version": "1.0.0",
            "entrypoint": "main.py",
        })
        resp = await client.post(
            "/api/v1/upload",
            files={"file": ("server.zip", data, "application/zip")},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_missing_entrypoint_file_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        data = _make_zip(include_entrypoint=False)
        resp = await client.post(
            "/api/v1/upload",
            files={"file": ("server.zip", data, "application/zip")},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert "main.py" in resp.json()["detail"] or "entrypoint" in resp.json()["detail"].lower()

    async def test_missing_dependency_metadata_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        data = _make_zip(include_requirements=False)
        resp = await client.post(
            "/api/v1/upload",
            files={"file": ("server.zip", data, "application/zip")},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert "requirements.txt or pyproject.toml" in resp.json()["detail"]

    async def test_zip_slip_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        data = _make_zip(dangerous_path="../../etc/passwd")
        resp = await client.post(
            "/api/v1/upload",
            files={"file": ("server.zip", data, "application/zip")},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "traversal" in str(detail).lower() or "zip slip" in str(detail).lower()

    async def test_not_a_zip_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.post(
            "/api/v1/upload",
            files={"file": ("notazip.zip", b"this is not a zip file", "application/zip")},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    async def test_duplicate_name_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str], tmp_path
    ) -> None:
        import os
        os.environ["SERVERS_DIR"] = str(tmp_path)
        import hub.config as cfg
        cfg.get_settings.cache_clear()

        data = _make_zip()
        await client.post(
            "/api/v1/upload",
            files={"file": ("server.zip", data, "application/zip")},
            headers=auth_headers,
        )
        # Second upload with same name
        resp = await client.post(
            "/api/v1/upload",
            files={"file": ("server.zip", data, "application/zip")},
            headers=auth_headers,
        )
        assert resp.status_code == 409

        cfg.get_settings.cache_clear()

    async def test_upload_requires_auth(self, client: AsyncClient) -> None:
        data = _make_zip()
        resp = await client.post(
            "/api/v1/upload",
            files={"file": ("server.zip", data, "application/zip")},
        )
        assert resp.status_code == 401


class TestApiKeyEndpointProtection:
    """Test that group endpoints with require_api_key=True enforce authentication."""

    async def test_group_endpoint_without_key_returns_401(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # Create a group with API key enforcement
        resp = await client.post(
            "/api/v1/groups",
            json={"name": "locked-grp", "require_api_key": True},
            headers=auth_headers,
        )
        assert resp.status_code == 201

        # Access without API key — should fail
        from unittest.mock import MagicMock, patch

        from hub.mcp.router import McpRouter

        mock_pm = MagicMock()
        mock_pm.list_running.return_value = []
        mock_pm._mcp_router = McpRouter(mock_pm)
        with patch("hub.mcp.proxy.get_process_manager", return_value=mock_pm):
            resp = await client.post(
                "/mcp/locked-grp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
        # Should 401 since no API key provided
        assert resp.status_code == 401
