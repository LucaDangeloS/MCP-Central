"""MCP server process pool manager.

Responsibilities:
- Start / stop / restart MCP server subprocesses.
- Capture stdout (MCP JSON-RPC) and stderr (logs/errors) continuously.
- Store captured stderr in the DB + fan out to log subscribers.
- Track process health and auto-restart with exponential backoff.
- Maintain an in-memory registry of running processes for the MCP proxy layer.
"""

from __future__ import annotations

import asyncio
import json
import traceback
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hub.config import get_settings
from hub.models.log_entry import LogLevel, LogStream
from hub.models.server import McpServer, ServerStatus
from hub.process.sandbox import SandboxConfig, create_server_venv

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


class _ServerProcess:
    """Wraps a running asyncio subprocess for one MCP server."""

    def __init__(
        self,
        server_name: str,
        config: SandboxConfig,
    ) -> None:
        self.server_name = server_name
        self.config = config
        self.proc: asyncio.subprocess.Process | None = None
        # Queues for stdout lines (MCP protocol) and stderr lines (logs)
        self.stdout_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
        self.stderr_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
        self.request_lock = asyncio.Lock()
        self._tasks: list[asyncio.Task[None]] = []
        self.started_at: datetime | None = None

    @property
    def pid(self) -> int | None:
        if self.proc and self.proc.pid:
            return self.proc.pid
        return None

    @property
    def is_running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self) -> None:
        cmd = self.config.build_cmd()
        env = self.config.build_env()
        log = logger.bind(server_name=self.server_name)
        log.info("starting_process", cmd=cmd[0], module=self.config.entrypoint_module)

        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(self.config.server_dir),
            limit=get_settings().server_stdio_limit_mb * 1024 * 1024,
        )
        self.started_at = datetime.now(UTC)

        # Kick off background tasks to drain stdout and stderr pipes
        self._tasks = [
            asyncio.create_task(self._drain_pipe(self.proc.stdout, self.stdout_queue, "stdout")),
            asyncio.create_task(self._drain_pipe(self.proc.stderr, self.stderr_queue, "stderr")),
        ]
        log.info("process_started", pid=self.proc.pid)

    async def stop(self, timeout: float = 5.0) -> None:
        if self.proc is None:
            return
        log = logger.bind(server_name=self.server_name, pid=self.proc.pid)
        log.info("stopping_process")
        try:
            if self.proc.returncode is None:
                try:
                    self.proc.terminate()
                except ProcessLookupError:
                    log.info("process_already_exited_before_terminate")
                await asyncio.wait_for(self.proc.wait(), timeout=timeout)
        except TimeoutError:
            log.warning("process_did_not_stop_gracefully_killing")
            try:
                self.proc.kill()
            except ProcessLookupError:
                log.info("process_already_exited_before_kill")
            await self.proc.wait()
        finally:
            for task in self._tasks:
                task.cancel()
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
            log.info("process_stopped", exit_code=self.proc.returncode)

    async def _drain_pipe(
        self,
        pipe: asyncio.StreamReader | None,
        queue: asyncio.Queue[str],
        stream_name: str,
    ) -> None:
        if pipe is None:
            return
        try:
            while True:
                line_bytes = await pipe.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode(errors="replace").rstrip()
                if line:
                    try:
                        queue.put_nowait(line)
                    except asyncio.QueueFull:
                        # Drop oldest item and insert new one to avoid blocking
                        try:
                            queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        queue.put_nowait(line)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(
                "pipe_drain_error",
                server_name=self.server_name,
                stream=stream_name,
                error=str(exc),
                traceback=traceback.format_exc(),
            )


class ProcessManager:
    """Manages the lifecycle of all MCP server subprocesses.

    One singleton instance per hub; stored on the FastAPI app state.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._processes: dict[str, _ServerProcess] = {}
        self._health_tasks: dict[str, asyncio.Task[None]] = {}
        self._log_tasks: dict[str, asyncio.Task[None]] = {}
        self._settings = get_settings()

    # ------------------------------------------------------------------ #
    # Public lifecycle API                                                  #
    # ------------------------------------------------------------------ #

    async def start_all_auto_start(self) -> None:
        """Called at hub startup — start all servers with auto_start=True."""
        from sqlalchemy import select

        async with self._session_factory() as db:
            result = await db.execute(
                select(McpServer).where(
                    McpServer.auto_start.is_(True),
                )
            )
            servers = result.scalars().all()

        for server in servers:
            try:
                await self.start_server(server.name)
            except Exception as exc:
                logger.error(
                    "auto_start_failed",
                    server_name=server.name,
                    error=str(exc),
                    traceback=traceback.format_exc(),
                )

    async def start_server(self, server_name: str) -> None:
        """Start a registered MCP server by name."""
        if server_name in self._processes and self._processes[server_name].is_running:
            logger.warning("start_server_already_running", server_name=server_name)
            return

        server = await self._load_server(server_name)
        if server is None:
            raise ValueError(f"Server '{server_name}' not found in database")

        await self._update_status(server_name, ServerStatus.starting, pid=None, last_error=None)

        config = self._make_sandbox_config(server)

        # Ensure venv exists
        venv_dir = self._settings.servers_dir / server.path / ".venv"
        server_dir = self._settings.servers_dir / server.path
        if not venv_dir.exists():
            try:
                await create_server_venv(server_dir, venv_dir)
            except Exception as exc:
                tb = traceback.format_exc()
                logger.error(
                    "venv_creation_failed",
                    server_name=server_name,
                    error=str(exc),
                    traceback=tb,
                )
                await self._update_status(server_name, ServerStatus.error, last_error=tb)
                raise

        sp = _ServerProcess(server_name=server_name, config=config)
        try:
            await sp.start()
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error(
                "process_start_failed",
                server_name=server_name,
                error=str(exc),
                traceback=tb,
            )
            await self._update_status(server_name, ServerStatus.error, last_error=tb)
            raise

        self._processes[server_name] = sp
        await self._update_status(server_name, ServerStatus.running, pid=sp.pid)

        try:
            await self._discover_tools(server_name)
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error(
                "tool_discovery_failed",
                server_name=server_name,
                error=str(exc),
                traceback=tb,
            )
            await self._update_status(
                server_name,
                ServerStatus.running,
                last_error=f"Tool discovery failed: {exc}\n{tb}",
            )

        # Start background tasks: log capture, health monitoring
        self._log_tasks[server_name] = asyncio.create_task(self._capture_logs(server_name, sp))
        self._health_tasks[server_name] = asyncio.create_task(self._health_monitor(server_name, sp))

        logger.info("server_started", server_name=server_name, pid=sp.pid)

    async def stop_server(self, server_name: str) -> None:
        """Stop a running MCP server."""
        sp = self._processes.get(server_name)
        if sp is None:
            return

        # Cancel monitoring tasks first
        for task_dict in (self._health_tasks, self._log_tasks):
            task = task_dict.pop(server_name, None)
            if task:
                task.cancel()

        await sp.stop()
        del self._processes[server_name]
        self._get_mcp_router().unregister_server(server_name)
        await self._update_status(server_name, ServerStatus.stopped, pid=None)
        logger.info("server_stopped", server_name=server_name)

    async def restart_server(self, server_name: str) -> None:
        """Stop then start an MCP server."""
        await self.stop_server(server_name)
        await self._update_status(server_name, ServerStatus.restarting)
        await self.start_server(server_name)

    async def stop_all(self) -> None:
        """Gracefully stop all running servers — called at hub shutdown."""
        names = list(self._processes.keys())
        for name in names:
            try:
                await self.stop_server(name)
            except Exception as exc:
                logger.error("stop_server_error", server_name=name, error=str(exc))

    def get_process(self, server_name: str) -> _ServerProcess | None:
        return self._processes.get(server_name)

    def list_running(self) -> list[str]:
        return [name for name, sp in self._processes.items() if sp.is_running]

    # ------------------------------------------------------------------ #
    # MCP stdio bridge — send a JSON-RPC message to the server             #
    # ------------------------------------------------------------------ #

    async def send_jsonrpc(self, server_name: str, message: str) -> str | None:
        """Write *message* to the server's stdin and await a stdout line.

        Returns the raw JSON-RPC response string, or None on timeout/error.
        Raises RuntimeError with the full stderr traceback if the process died.
        """
        sp = self._processes.get(server_name)
        if sp is None or not sp.is_running:
            raise RuntimeError(f"Server '{server_name}' is not running")
        if sp.proc is None or sp.proc.stdin is None:
            raise RuntimeError(f"Server '{server_name}' stdin is not available")

        try:
            expected_id = json.loads(message).get("id")
        except json.JSONDecodeError:
            expected_id = None

        async with sp.request_lock:
            sp.proc.stdin.write((message + "\n").encode())
            await sp.proc.stdin.drain()

            try:
                loop = asyncio.get_running_loop()
                deadline = loop.time() + 30.0
                while True:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise TimeoutError
                    response = await asyncio.wait_for(sp.stdout_queue.get(), timeout=remaining)
                    if expected_id is None:
                        return response
                    try:
                        parsed = json.loads(response)
                    except json.JSONDecodeError:
                        logger.warning(
                            "discarding_non_json_stdout",
                            server_name=server_name,
                            raw=response,
                        )
                        continue
                    if parsed.get("id") == expected_id:
                        return response
                    logger.warning(
                        "discarding_unmatched_jsonrpc_response",
                        server_name=server_name,
                        expected_id=expected_id,
                        actual_id=parsed.get("id"),
                    )
            except TimeoutError as exc:
                raise RuntimeError(
                    f"Server '{server_name}' did not respond within 30 seconds. "
                    f"Check stderr logs for errors."
                ) from exc

    async def send_jsonrpc_notification(self, server_name: str, message: str) -> None:
        """Write a JSON-RPC notification to the server's stdin without awaiting a response."""
        sp = self._processes.get(server_name)
        if sp is None or not sp.is_running:
            raise RuntimeError(f"Server '{server_name}' is not running")
        if sp.proc is None or sp.proc.stdin is None:
            raise RuntimeError(f"Server '{server_name}' stdin is not available")

        async with sp.request_lock:
            sp.proc.stdin.write((message + "\n").encode())
            await sp.proc.stdin.drain()

    # ------------------------------------------------------------------ #
    # Background tasks                                                      #
    # ------------------------------------------------------------------ #

    async def _capture_logs(self, server_name: str, sp: _ServerProcess) -> None:
        """Continuously drain the stderr queue and persist entries to DB + fan out."""
        from hub.api.logs import publish_log_entry
        from hub.models.log_entry import LogEntry

        stderr_buffer: list[str] = []

        async def _flush_buffer() -> None:
            """Persist buffered stderr lines as a single traceback log entry."""
            if not stderr_buffer:
                return
            raw = "\n".join(stderr_buffer)
            level = LogLevel.error.value if any(
                kw in raw for kw in ("Error", "Exception", "Traceback", "CRITICAL")
            ) else LogLevel.info.value
            message = stderr_buffer[0] if stderr_buffer else ""

            async with self._session_factory() as db:
                entry = LogEntry(
                    server_name=server_name,
                    stream=LogStream.stderr.value,
                    level=level,
                    message=message,
                    raw=raw,
                )
                db.add(entry)
                await db.commit()
                await db.refresh(entry)

            publish_log_entry(entry)
            stderr_buffer.clear()

        try:
            while True:
                try:
                    line = await asyncio.wait_for(sp.stderr_queue.get(), timeout=1.0)
                    stderr_buffer.append(line)
                    # Flush on traceback end markers
                    if any(
                        line.startswith(kw) for kw in
                        ("Traceback", "Error:", "Exception:", "KeyboardInterrupt")
                    ):
                        # Collect the rest of the traceback (up to 100 more lines)
                        for _ in range(100):
                            try:
                                next_line = await asyncio.wait_for(
                                    sp.stderr_queue.get(), timeout=0.1
                                )
                                stderr_buffer.append(next_line)
                            except TimeoutError:
                                break
                        await _flush_buffer()
                    elif len(stderr_buffer) >= 50:
                        await _flush_buffer()
                except TimeoutError:
                    if stderr_buffer:
                        await _flush_buffer()
        except asyncio.CancelledError:
            await _flush_buffer()

    async def _health_monitor(self, server_name: str, sp: _ServerProcess) -> None:
        """Monitor process liveness and auto-restart with exponential backoff."""
        settings = get_settings()
        retry_count = 0
        backoff = settings.server_restart_backoff_seconds

        try:
            while True:
                await asyncio.sleep(settings.server_health_check_interval)

                if not sp.is_running:
                    exit_code = sp.proc.returncode if sp.proc else None
                    # Collect any remaining stderr for the error report
                    stderr_lines: list[str] = []
                    while not sp.stderr_queue.empty():
                        try:
                            stderr_lines.append(sp.stderr_queue.get_nowait())
                        except asyncio.QueueEmpty:
                            break
                    last_error = (
                        f"Process exited with code {exit_code}\n" + "\n".join(stderr_lines)
                    )

                    logger.error(
                        "server_process_died",
                        server_name=server_name,
                        exit_code=exit_code,
                        restart_attempt=retry_count + 1,
                        last_stderr_tail="\n".join(stderr_lines[-20:]),
                    )

                    await self._update_status(
                        server_name, ServerStatus.error, last_error=last_error
                    )

                    server = await self._load_server(server_name)
                    if server is None or not server.restart_on_error:
                        logger.info(
                            "server_restart_on_error_disabled",
                            server_name=server_name,
                        )
                        return

                    if retry_count >= settings.server_restart_max_retries:
                        logger.error(
                            "server_max_retries_exceeded",
                            server_name=server_name,
                            max_retries=settings.server_restart_max_retries,
                        )
                        return

                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 120.0)  # cap at 2 minutes
                    retry_count += 1

                    try:
                        await self.start_server(server_name)
                        # Reset backoff on successful restart
                        backoff = settings.server_restart_backoff_seconds
                    except Exception as exc:
                        logger.error(
                            "server_restart_failed",
                            server_name=server_name,
                            attempt=retry_count,
                            error=str(exc),
                            traceback=traceback.format_exc(),
                        )
                    return  # health monitor for the old sp ends; new one started by start_server

        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------ #
    # Helpers                                                               #
    # ------------------------------------------------------------------ #

    def _make_sandbox_config(self, server: McpServer) -> SandboxConfig:
        settings = self._settings
        server_dir = settings.servers_dir / server.path
        venv_dir = server_dir / ".venv"
        try:
            env_vars: dict[str, str] = json.loads(server.env_vars) if server.env_vars else {}
        except Exception:
            env_vars = {}

        return SandboxConfig(
            server_name=server.name,
            server_dir=server_dir,
            entrypoint_module=server.entrypoint_module,
            venv_dir=venv_dir,
            env_vars=env_vars,
            proxy_port=settings.proxy_port,
            max_memory_mb=settings.server_max_memory_mb,
        )

    def _get_mcp_router(self) -> Any:
        from hub.mcp.router import McpRouter

        if not hasattr(self, "_mcp_router"):
            self._mcp_router = McpRouter(self)
        return self._mcp_router

    async def _discover_tools(self, server_name: str) -> None:
        """Initialize a child MCP server and register its tool definitions."""
        initialize_request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "mcp-central-initialize",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "MCP Central", "version": "0.1.0"},
                },
            }
        )
        initialize_raw = await self.send_jsonrpc(server_name, initialize_request)
        if initialize_raw is None:
            raise RuntimeError("initialize returned no response")
        initialize_response = json.loads(initialize_raw)
        if "error" in initialize_response:
            raise RuntimeError(f"initialize failed: {initialize_response['error']}")

        await self.send_jsonrpc_notification(
            server_name,
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        )

        list_request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "mcp-central-tools-list",
                "method": "tools/list",
                "params": {},
            }
        )
        tools_raw = await self.send_jsonrpc(server_name, list_request)
        if tools_raw is None:
            raise RuntimeError("tools/list returned no response")
        tools_response = json.loads(tools_raw)
        if "error" in tools_response:
            raise RuntimeError(f"tools/list failed: {tools_response['error']}")

        tools = tools_response.get("result", {}).get("tools", [])
        if not isinstance(tools, list):
            raise RuntimeError("tools/list response did not contain a tools array")
        self._get_mcp_router().register_tools(server_name, tools)

    async def _load_server(self, server_name: str) -> McpServer | None:
        from sqlalchemy import select

        async with self._session_factory() as db:
            result = await db.execute(
                select(McpServer).where(
                    McpServer.name == server_name,
                )
            )
            return result.scalar_one_or_none()

    async def _update_status(
        self,
        server_name: str,
        status: ServerStatus,
        pid: int | None = ...,  # type: ignore[assignment]
        last_error: str | None = ...,  # type: ignore[assignment]
    ) -> None:
        from sqlalchemy import select

        async with self._session_factory() as db:
            result = await db.execute(
                select(McpServer).where(McpServer.name == server_name)
            )
            server = result.scalar_one_or_none()
            if server is None:
                return

            server.status = status.value
            if pid is not ...:  # type: ignore[comparison-overlap]
                server.pid = pid
            if last_error is not ...:  # type: ignore[comparison-overlap]
                server.last_error = last_error
                server.last_error_at = datetime.now(UTC) if last_error else None
            if status == ServerStatus.running:
                server.restart_count += 1

            await db.commit()
