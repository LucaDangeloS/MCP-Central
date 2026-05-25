"""McpRouter — routes namespaced JSON-RPC tool calls to the correct MCP server process."""

from __future__ import annotations

import json
import traceback
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.mcp.namespace import extract_server_name, namespace_tool_name
from hub.models.tool_call import ToolCallCount
from hub.process.manager import ProcessManager

logger = structlog.get_logger(__name__)


class McpRouter:
    """Routes a ``tools/call`` JSON-RPC request to the owning MCP server.

    Maintains an in-memory snapshot of each server's tool list so it can
    resolve namespaced names without hitting the subprocess on every request.
    """

    def __init__(self, process_manager: ProcessManager) -> None:
        self._pm = process_manager
        # server_name -> original tool definitions as returned by the child MCP server.
        self._tool_registry: dict[str, list[dict[str, Any]]] = {}

    # ------------------------------------------------------------------ #
    # Registry management                                                  #
    # ------------------------------------------------------------------ #

    def register_tools(self, server_name: str, tools: list[dict[str, Any]]) -> None:
        """Record the tool list for a server (called after server starts)."""
        self._tool_registry[server_name] = tools
        logger.info(
            "tools_registered",
            server_name=server_name,
            count=len(tools),
        )

    def unregister_server(self, server_name: str) -> None:
        self._tool_registry.pop(server_name, None)

    def get_all_namespaced_tools(
        self,
        group_server_names: list[str] | None = None,
        hidden_tools: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return all tools from all (or filtered) servers, namespaced.

        Args:
            group_server_names: If set, only include tools from these servers.
            hidden_tools: List of namespaced tool names to exclude.
        """
        result: list[dict[str, Any]] = []
        hidden_set = set(hidden_tools or [])

        for server_name, tools in self._tool_registry.items():
            if group_server_names is not None and server_name not in group_server_names:
                continue
            if server_name not in self._pm.list_running():
                continue
            for tool in tools:
                tool_name = str(tool.get("name", ""))
                if not tool_name:
                    continue
                namespaced = namespace_tool_name(server_name, tool_name)
                if namespaced in hidden_set:
                    continue
                namespaced_tool = dict(tool)
                namespaced_tool["name"] = namespaced
                if "description" in namespaced_tool:
                    description = namespaced_tool["description"]
                    namespaced_tool["description"] = f"[{server_name}] {description}"
                else:
                    namespaced_tool["description"] = f"[{server_name}] {tool_name}"
                namespaced_tool.setdefault("inputSchema", {"type": "object"})
                result.append(namespaced_tool)
        return result

    # ------------------------------------------------------------------ #
    # Request routing                                                       #
    # ------------------------------------------------------------------ #

    async def route_tools_call(
        self,
        namespaced_tool: str,
        arguments: dict[str, Any],
        request_id: int | str | None,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Route a ``tools/call`` request to the appropriate server.

        Returns a full JSON-RPC response dict (success or error).
        Never swallows exceptions — always returns a structured error with
        the full traceback when something goes wrong.
        """
        parsed = extract_server_name(namespaced_tool)
        if parsed is None:
            return _jsonrpc_error(
                request_id,
                code=-32602,
                message=f"Tool name '{namespaced_tool}' is not namespaced. "
                        f"Expected format: '<server>__{namespaced_tool}'.",
            )

        server_name, original_tool = parsed

        if server_name not in self._pm.list_running():
            return _jsonrpc_error(
                request_id,
                code=-32001,
                message=f"Server '{server_name}' is not running.",
                data={"server": server_name},
            )

        # Build a JSON-RPC request to forward to the sub-server
        sub_request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": original_tool, "arguments": arguments},
            }
        )

        try:
            await record_tool_call(db, server_name, original_tool)
            raw_response = await self._pm.send_jsonrpc(server_name, sub_request)
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error(
                "tools_call_error",
                server_name=server_name,
                tool=original_tool,
                error=str(exc),
                traceback=tb,
            )
            return _jsonrpc_error(
                request_id,
                code=-32603,
                message=(
                    f"Server '{server_name}' raised an unhandled exception while executing "
                    f"'{original_tool}'"
                ),
                data={
                    "server": server_name,
                    "tool": original_tool,
                    "traceback": tb,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

        if raw_response is None:
            return _jsonrpc_error(
                request_id,
                code=-32603,
                message=f"Server '{server_name}' returned no response for tool '{original_tool}'",
                data={"server": server_name, "tool": original_tool},
            )

        try:
            return json.loads(raw_response)  # type: ignore[no-any-return]
        except json.JSONDecodeError as exc:
            return _jsonrpc_error(
                request_id,
                code=-32700,
                message=f"Server '{server_name}' returned invalid JSON: {exc}",
                data={"server": server_name, "raw_response": raw_response},
            )


async def record_tool_call(db: AsyncSession, server_name: str, tool_name: str) -> None:
    """Increment the aggregate counter for one routed tool call."""
    result = await db.execute(
        select(ToolCallCount).where(
            ToolCallCount.server_name == server_name,
            ToolCallCount.tool_name == tool_name,
        )
    )
    counter = result.scalar_one_or_none()
    now = datetime.now(UTC)
    if counter is None:
        counter = ToolCallCount(
            server_name=server_name,
            tool_name=tool_name,
            call_count=1,
            last_called_at=now,
        )
        db.add(counter)
        return
    counter.call_count += 1
    counter.last_called_at = now


def _jsonrpc_error(
    request_id: int | str | None,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = data
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": error,
    }
