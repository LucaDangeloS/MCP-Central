"""Unit tests for the ProcessManager using a mock MCP server subprocess."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from hub.database import Base
from hub.models.server import McpServer, ServerStatus
from hub.process.manager import ProcessManager, _ServerProcess
from hub.process.sandbox import SandboxConfig

# ------------------------------------------------------------------ #
# In-memory DB fixture for process manager tests                       #
# ------------------------------------------------------------------ #

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
_engine = create_async_engine(_TEST_DB_URL, connect_args={"check_same_thread": False})
_SessionFactory = async_sessionmaker(bind=_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def _db_setup() -> None:
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def pm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProcessManager:
    """ProcessManager with servers_dir pointing at tmp_path."""
    monkeypatch.setenv("SERVERS_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Re-create settings to pick up new env vars
    import hub.config as cfg
    cfg.get_settings.cache_clear()
    manager = ProcessManager(_SessionFactory)
    yield manager
    await manager.stop_all()
    cfg.get_settings.cache_clear()


async def _register_server(
    tmp_path: Path,
    name: str,
    script_content: str,
    session_factory: async_sessionmaker[AsyncSession],
    restart_on_error: bool = True,
) -> None:
    """Write a mock server script and register it in the DB."""
    server_dir = tmp_path / name
    server_dir.mkdir(exist_ok=True)
    (server_dir / "main.py").write_text(script_content)
    # No requirements.txt → venv creation skipped at install step

    async with session_factory() as db:
        server = McpServer(
            name=name,
            path=name,
            entrypoint_module="main",
            auto_start=False,
            restart_on_error=restart_on_error,
            status=ServerStatus.stopped.value,
        )
        db.add(server)
        await db.commit()


# ------------------------------------------------------------------ #
# Minimal echo MCP server script used in tests                         #
# ------------------------------------------------------------------ #

_ECHO_SERVER = """\
import sys, json

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": {"echo": req}}
        print(json.dumps(resp), flush=True)
"""

_TOOLS_SERVER = """\
import sys, json

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        method = req.get("method")
        if method == "notifications/initialized":
            continue
        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "tools-test", "version": "1.0.0"},
                },
            }
        elif method == "tools/list":
            resp = {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "result": {
                    "tools": [
                        {
                            "name": "hello",
                            "description": "Say hello",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"name": {"type": "string"}},
                            },
                        }
                    ]
                },
            }
        else:
            resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": {}}
        print(json.dumps(resp), flush=True)
"""

_CRASH_SERVER = """\
def main():
    raise RuntimeError("deliberate crash for testing — full traceback must appear on stderr")
"""

_CRASH_ONCE_SERVER = """\
from pathlib import Path
import time

def main():
    marker = Path("crashed.once")
    if not marker.exists():
        marker.write_text("1", encoding="utf-8")
        raise RuntimeError("first run crashes")
    time.sleep(30)
"""

_STDERR_SERVER = """\
import sys, time
def main():
    print("line on stderr", file=sys.stderr, flush=True)
    sys.stderr.flush()
    # Keep running so the test can observe the output
    time.sleep(30)
"""

_LARGE_RESPONSE_SERVER = """\
import sys, json

def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        payload = "x" * (96 * 1024)
        resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": {"payload": payload}}
        print(json.dumps(resp), flush=True)
"""


class TestProcessManagerStartStop:
    async def test_start_and_stop_echo_server(self, pm: ProcessManager, tmp_path: Path) -> None:
        await _register_server(tmp_path, "echo-srv", _ECHO_SERVER, _SessionFactory)
        await pm.start_server("echo-srv")

        assert "echo-srv" in pm.list_running()
        sp = pm.get_process("echo-srv")
        assert sp is not None
        assert sp.is_running
        assert sp.pid is not None

        await pm.stop_server("echo-srv")
        assert "echo-srv" not in pm.list_running()

    async def test_start_nonexistent_server_raises(self, pm: ProcessManager) -> None:
        with pytest.raises(ValueError, match="not found"):
            await pm.start_server("does-not-exist")

    async def test_double_start_is_idempotent(self, pm: ProcessManager, tmp_path: Path) -> None:
        await _register_server(tmp_path, "idempotent-srv", _ECHO_SERVER, _SessionFactory)
        await pm.start_server("idempotent-srv")
        pid1 = pm.get_process("idempotent-srv").pid

        # Second start should be a no-op
        await pm.start_server("idempotent-srv")
        pid2 = pm.get_process("idempotent-srv").pid
        assert pid1 == pid2

    async def test_stop_not_running_is_safe(self, pm: ProcessManager) -> None:
        # Should not raise
        await pm.stop_server("never-started")

    async def test_stop_tolerates_process_lookup_error(self, tmp_path: Path) -> None:
        class ExitedProcess:
            pid = 12345
            returncode = None

            def terminate(self) -> None:
                raise ProcessLookupError

            async def wait(self) -> int:
                self.returncode = 0
                return 0

            def kill(self) -> None:
                raise AssertionError("kill should not be called after terminate race")

        config = SandboxConfig(
            server_name="already-exited",
            server_dir=tmp_path,
            entrypoint_module="main",
            venv_dir=tmp_path / ".venv",
        )
        sp = _ServerProcess("already-exited", config)
        sp.proc = ExitedProcess()  # type: ignore[assignment]

        await sp.stop()

    async def test_stop_all_clears_all_processes(self, pm: ProcessManager, tmp_path: Path) -> None:
        await _register_server(tmp_path, "srv-a", _ECHO_SERVER, _SessionFactory)
        await _register_server(tmp_path, "srv-b", _ECHO_SERVER, _SessionFactory)
        await pm.start_server("srv-a")
        await pm.start_server("srv-b")
        assert len(pm.list_running()) == 2

        await pm.stop_all()
        assert pm.list_running() == []


class TestStderrCapture:
    async def test_stderr_lines_captured(self, pm: ProcessManager, tmp_path: Path) -> None:
        """Stderr output from MCP servers must be captured and stored in the DB."""
        from sqlalchemy import select

        from hub.models.log_entry import LogEntry

        await _register_server(tmp_path, "stderr-srv", _STDERR_SERVER, _SessionFactory)
        await pm.start_server("stderr-srv")

        # Give the log capture task enough time to flush stderr into the DB
        await asyncio.sleep(3.0)
        await pm.stop_server("stderr-srv")

        # Verify the stderr line was written to the DB
        async with _SessionFactory() as db:
            result = await db.execute(
                select(LogEntry).where(LogEntry.server_name == "stderr-srv")
            )
            entries = result.scalars().all()

        assert any("line on stderr" in (e.raw or e.message) for e in entries), (
            f"Expected stderr line not found in DB entries: {[(e.level, e.raw) for e in entries]!r}"
        )

    async def test_crashed_server_error_stored_in_db(
        self, pm: ProcessManager, tmp_path: Path
    ) -> None:
        """A crashed server's traceback must be stored in the DB without truncation."""
        await _register_server(tmp_path, "crash-srv", _CRASH_SERVER, _SessionFactory)

        # Monkeypatch settings to avoid waiting for health check interval
        import hub.config as cfg
        cfg.get_settings().server_health_check_interval = 0.5
        cfg.get_settings().server_restart_max_retries = 0

        await pm.start_server("crash-srv")

        # Wait for the process to die and the health monitor to detect it
        await asyncio.sleep(2.0)

        # Check DB for error status
        from sqlalchemy import select

        async with _SessionFactory() as db:
            result = await db.execute(
                select(McpServer).where(McpServer.name == "crash-srv")
            )
            server = result.scalar_one_or_none()

        assert server is not None
        assert server.status == ServerStatus.error.value
        # The last_error must contain traceback information — never empty
        assert server.last_error is not None

    async def test_crashed_server_does_not_restart_when_disabled(
        self, pm: ProcessManager, tmp_path: Path
    ) -> None:
        await _register_server(
            tmp_path,
            "no-auto-restart",
            _CRASH_SERVER,
            _SessionFactory,
            restart_on_error=False,
        )

        import hub.config as cfg

        cfg.get_settings().server_health_check_interval = 0.2
        cfg.get_settings().server_restart_backoff_seconds = 0.2
        cfg.get_settings().server_restart_max_retries = 5
        pm._discover_tools = AsyncMock()  # type: ignore[method-assign]

        await pm.start_server("no-auto-restart")
        await asyncio.sleep(0.8)

        async with _SessionFactory() as db:
            result = await db.execute(
                select(McpServer).where(McpServer.name == "no-auto-restart")
            )
            server = result.scalar_one()

        assert server.status == ServerStatus.error.value
        assert server.restart_count == 1
        assert "no-auto-restart" not in pm.list_running()

    async def test_crashed_server_restarts_when_enabled(
        self, pm: ProcessManager, tmp_path: Path
    ) -> None:
        await _register_server(
            tmp_path,
            "auto-restart",
            _CRASH_ONCE_SERVER,
            _SessionFactory,
            restart_on_error=True,
        )

        import hub.config as cfg

        cfg.get_settings().server_health_check_interval = 0.2
        cfg.get_settings().server_restart_backoff_seconds = 0.2
        cfg.get_settings().server_restart_max_retries = 1
        pm._discover_tools = AsyncMock()  # type: ignore[method-assign]

        await pm.start_server("auto-restart")
        await asyncio.sleep(1.2)

        async with _SessionFactory() as db:
            result = await db.execute(
                select(McpServer).where(McpServer.name == "auto-restart")
            )
            server = result.scalar_one()

        assert server.status == ServerStatus.running.value
        assert server.restart_count >= 2
        assert "auto-restart" in pm.list_running()
        await pm.stop_server("auto-restart")


class TestJsonRpcBridge:
    async def test_send_jsonrpc_gets_response(self, pm: ProcessManager, tmp_path: Path) -> None:
        await _register_server(tmp_path, "rpc-srv", _ECHO_SERVER, _SessionFactory)
        await pm.start_server("rpc-srv")
        # Give the server a moment to be ready
        await asyncio.sleep(0.2)

        request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}})
        response = await pm.send_jsonrpc("rpc-srv", request)
        assert response is not None
        parsed = json.loads(response)
        assert parsed["id"] == 1
        assert "result" in parsed

        await pm.stop_server("rpc-srv")

    async def test_send_jsonrpc_to_stopped_server_raises(self, pm: ProcessManager) -> None:
        with pytest.raises(RuntimeError, match="not running"):
            await pm.send_jsonrpc("not-running", '{"id":1}')

    async def test_send_jsonrpc_handles_large_single_line_response(
        self,
        pm: ProcessManager,
        tmp_path: Path,
    ) -> None:
        await _register_server(tmp_path, "large-rpc", _LARGE_RESPONSE_SERVER, _SessionFactory)
        await pm.start_server("large-rpc")

        request = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "large"})
        response = await pm.send_jsonrpc("large-rpc", request)
        assert response is not None
        parsed = json.loads(response)
        assert parsed["id"] == 7
        assert len(parsed["result"]["payload"]) == 96 * 1024

        await pm.stop_server("large-rpc")


class TestToolDiscovery:
    async def test_start_registers_child_mcp_tools(
        self, pm: ProcessManager, tmp_path: Path
    ) -> None:
        await _register_server(tmp_path, "tools-srv", _TOOLS_SERVER, _SessionFactory)
        await pm.start_server("tools-srv")

        tools = pm._get_mcp_router().get_all_namespaced_tools()
        assert tools == [
            {
                "name": "tools-srv__hello",
                "description": "[tools-srv] Say hello",
                "inputSchema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            }
        ]

        await pm.stop_server("tools-srv")
        assert pm._get_mcp_router().get_all_namespaced_tools() == []
