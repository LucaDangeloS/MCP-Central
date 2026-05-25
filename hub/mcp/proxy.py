"""Unified /mcp endpoint — aggregates all MCP servers into one Streamable HTTP endpoint.

Implements the MCP 2025-03-26 specification over HTTP+JSON.

Endpoints mounted by this router:
  POST /mcp            — all servers aggregated
  POST /mcp/<group>    — servers in a specific group
  POST /mcp/server/<name> — single server passthrough

All requests share the same JSON-RPC 2.0 framing.
"""
from __future__ import annotations

import json
import traceback
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.auth.api_keys import hash_key
from hub.database import get_db
from hub.mcp.router import McpRouter, _jsonrpc_error
from hub.models.api_key import ApiKey
from hub.models.group import Group
from hub.models.server import McpServer
from hub.process.health import get_process_manager

logger = structlog.get_logger(__name__)

_CONTENT_TYPE_SSE = "text/event-stream"
_MCP_PROTOCOL_VERSION = "2025-03-26"


def create_mcp_discovery_router() -> APIRouter:
    """Factory for public, unauthenticated discovery endpoints."""
    router = APIRouter(tags=["mcp-discovery"])

    @router.get("/.well-known/mcp-central.json", summary="Public MCP Central discovery")
    async def well_known_discovery(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> dict[str, Any]:
        return await _build_discovery_document(request, db)

    return router


def create_mcp_router() -> APIRouter:
    """Factory that returns the FastAPI router for all /mcp endpoints."""
    router = APIRouter(prefix="/mcp", tags=["mcp"])

    # ------------------------------------------------------------------ #
    # Helper to get the McpRouter singleton from the process manager       #
    # ------------------------------------------------------------------ #
    def _get_mcp_router() -> McpRouter:
        pm = get_process_manager()
        if not hasattr(pm, "_mcp_router"):
            pm._mcp_router = McpRouter(pm)
        return pm._mcp_router

    async def _count_group_keys(db: AsyncSession, group_id: int) -> int:
        result = await db.execute(
            select(func.count()).select_from(ApiKey).where(ApiKey.group_id == group_id)
        )
        return result.scalar_one()

    async def _count_server_keys(db: AsyncSession, server_id: int) -> int:
        result = await db.execute(
            select(func.count()).select_from(ApiKey).where(ApiKey.server_id == server_id)
        )
        return result.scalar_one()

    async def _server_endpoint_requires_key(db: AsyncSession, server: McpServer) -> bool:
        if await _count_server_keys(db, server.id) > 0:
            return True
        if server.group_id is None:
            return False
        group = await db.get(Group, server.group_id)
        if group is None:
            return False
        return group.require_api_key or await _count_group_keys(db, group.id) > 0

    async def _validate_raw_key(db: AsyncSession, raw_key: str) -> ApiKey:
        key_hash = hash_key(raw_key)
        key_result = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
        api_key = key_result.scalar_one_or_none()
        if api_key is None:
            raise HTTPException(status_code=401, detail="Invalid or revoked API key")
        return api_key

    async def _validate_group_key(
        db: AsyncSession,
        request: Request,
        group: Group,
        required: bool,
    ) -> ApiKey | None:
        raw_key = _extract_api_key(request)
        if raw_key is None:
            if required:
                raise HTTPException(status_code=401, detail="API key required for this group")
            return None
        api_key = await _validate_raw_key(db, raw_key)
        if api_key.group_id != group.id:
            raise HTTPException(status_code=403, detail="API key not authorised for this group")
        return api_key

    async def _validate_server_key(
        db: AsyncSession,
        request: Request,
        server: McpServer,
        required: bool,
    ) -> ApiKey | None:
        raw_key = _extract_api_key(request)
        if raw_key is None:
            if required:
                raise HTTPException(status_code=401, detail="API key required for this server")
            return None
        api_key = await _validate_raw_key(db, raw_key)
        if api_key.server_id == server.id:
            return api_key
        if server.group_id is not None and api_key.group_id == server.group_id:
            return api_key
        raise HTTPException(status_code=403, detail="API key not authorised for this server")

    async def _public_or_authorized_server_names(
        db: AsyncSession,
        request: Request,
    ) -> list[str]:
        raw_key = _extract_api_key(request)
        api_key: ApiKey | None = None
        if raw_key is not None:
            api_key = await _validate_raw_key(db, raw_key)

        result = await db.execute(select(McpServer))
        servers = result.scalars().all()
        names: set[str] = set()
        for server in servers:
            if not await _server_endpoint_requires_key(db, server):
                names.add(server.name)
            if api_key is None:
                continue
            if api_key.server_id == server.id:
                names.add(server.name)
            if server.group_id is not None and api_key.group_id == server.group_id:
                names.add(server.name)
        return sorted(names)

    # ------------------------------------------------------------------ #
    # Shared JSON-RPC dispatch logic                                        #
    # ------------------------------------------------------------------ #

    async def _dispatch(
        body: dict[str, Any],
        server_names: list[str] | None,
        hidden_tools: list[str],
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Dispatch one JSON-RPC request.

        server_names: if set, only consider these servers (group/single mode).
        hidden_tools: namespaced tool names to exclude from listing.
        """
        import json as _json

        mcp_router = _get_mcp_router()
        method = body.get("method", "")
        req_id = body.get("id")
        params: dict[str, Any] = body.get("params") or {}

        if method == "tools/list":
            # Merge per-server disabled_tools (stored un-namespaced) into the
            # hidden_tools set, converting each to its namespaced form.
            all_hidden = list(hidden_tools)
            from hub.mcp.namespace import namespace_tool_name
            scope = (
                server_names if server_names is not None
                else list(mcp_router._tool_registry.keys())
            )
            srv_result = await db.execute(
                select(McpServer).where(McpServer.name.in_(scope))
            )
            for srv in srv_result.scalars().all():
                disabled: list[str] = _json.loads(srv.disabled_tools)
                for disabled_tool_name in disabled:
                    all_hidden.append(namespace_tool_name(srv.name, disabled_tool_name))

            tools = mcp_router.get_all_namespaced_tools(
                group_server_names=server_names,
                hidden_tools=all_hidden,
            )
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

        if method == "tools/call":
            tool_name: str = params.get("name", "")
            arguments: dict[str, Any] = params.get("arguments") or {}
            # If a group/single-server scope is set, verify the tool belongs to it
            if server_names is not None:
                from hub.mcp.namespace import extract_server_name

                parsed = extract_server_name(tool_name)
                if parsed is None or parsed[0] not in server_names:
                    return _jsonrpc_error(
                        req_id,
                        code=-32602,
                        message=f"Tool '{tool_name}' is not accessible on this endpoint.",
                    )
            return await mcp_router.route_tools_call(tool_name, arguments, req_id, db)

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": _MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "MCP Central Hub", "version": "0.1.0"},
                },
            }

        # Unknown method
        return _jsonrpc_error(
            req_id,
            code=-32601,
            message=f"Method '{method}' not found",
        )

    # ------------------------------------------------------------------ #
    # POST /mcp — global aggregated endpoint                               #
    # ------------------------------------------------------------------ #

    @router.post("", summary="Unified MCP endpoint — all servers")
    async def mcp_global(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> Response:
        _validate_origin(request)
        server_names = await _public_or_authorized_server_names(db, request)
        return await _handle_request(request, server_names=server_names, hidden_tools=[], db=db)

    @router.get("", summary="Unified MCP SSE stream")
    async def mcp_discovery(
        request: Request,
    ) -> Response:
        _validate_origin(request)
        return _handle_sse_get(request)

    # ------------------------------------------------------------------ #
    # POST /mcp/<group> — group-scoped endpoint                            #
    # ------------------------------------------------------------------ #

    @router.post("/{group_name}", summary="MCP endpoint scoped to a group")
    async def mcp_group(
        group_name: str,
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> Response:
        _validate_origin(request)
        # Load the group
        result = await db.execute(
            select(Group).where(Group.name == group_name)
        )
        group = result.scalar_one_or_none()
        if group is None:
            raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")

        api_key_required = group.require_api_key or await _count_group_keys(db, group.id) > 0
        await _validate_group_key(db, request, group, api_key_required)

        # Get server names in this group
        srv_result = await db.execute(
            select(McpServer).where(
                McpServer.group_id == group.id,
            )
        )
        server_names = [s.name for s in srv_result.scalars().all()]

        import json as _json
        hidden_tools: list[str] = _json.loads(group.hidden_tools)

        return await _handle_request(
            request, server_names=server_names, hidden_tools=hidden_tools, db=db
        )

    # ------------------------------------------------------------------ #
    # POST /mcp/server/<name> — single-server passthrough                  #
    # ------------------------------------------------------------------ #

    @router.post("/server/{server_name}", summary="MCP endpoint for a single server")
    async def mcp_single(
        server_name: str,
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> Response:
        _validate_origin(request)
        srv_result = await db.execute(
            select(McpServer).where(
                McpServer.name == server_name,
            )
        )
        server = srv_result.scalar_one_or_none()
        if server is None:
            raise HTTPException(status_code=404, detail=f"Server '{server_name}' not found")

        api_key_required = await _server_endpoint_requires_key(db, server)
        await _validate_server_key(db, request, server, api_key_required)

        return await _handle_request(
            request, server_names=[server_name], hidden_tools=[], db=db
        )

    @router.get("/{group_name}", summary="MCP SSE stream scoped to a group")
    async def mcp_group_stream(
        group_name: str,
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> Response:
        _validate_origin(request)
        result = await db.execute(select(Group).where(Group.name == group_name))
        group = result.scalar_one_or_none()
        if group is None:
            raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")

        api_key_required = group.require_api_key or await _count_group_keys(db, group.id) > 0
        await _validate_group_key(db, request, group, api_key_required)
        return _handle_sse_get(request)

    @router.get("/server/{server_name}", summary="MCP SSE stream for a single server")
    async def mcp_single_stream(
        server_name: str,
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> Response:
        _validate_origin(request)
        srv_result = await db.execute(select(McpServer).where(McpServer.name == server_name))
        server = srv_result.scalar_one_or_none()
        if server is None:
            raise HTTPException(status_code=404, detail=f"Server '{server_name}' not found")

        api_key_required = await _server_endpoint_requires_key(db, server)
        await _validate_server_key(db, request, server, api_key_required)
        return _handle_sse_get(request)

    # ------------------------------------------------------------------ #
    # Shared request handler                                               #
    # ------------------------------------------------------------------ #

    async def _handle_request(
        request: Request,
        server_names: list[str] | None,
        hidden_tools: list[str],
        db: AsyncSession,
    ) -> Response:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                status_code=400,
                content=_jsonrpc_error(
                    None, code=-32700, message="Parse error: request body is not valid JSON"
                ),
            )

        messages = body if isinstance(body, list) else [body]
        if not messages or not all(isinstance(message, dict) for message in messages):
            return JSONResponse(
                status_code=400,
                content=_jsonrpc_error(None, code=-32600, message="Invalid Request"),
            )

        requests = [message for message in messages if _is_jsonrpc_request(message)]
        if not requests:
            return Response(status_code=202)

        responses: list[dict[str, Any]] = []
        try:
            for message in requests:
                responses.append(await _dispatch(message, server_names, hidden_tools, db))
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error(
                "mcp_dispatch_error",
                error=str(exc),
                traceback=tb,
            )
            responses = [
                _jsonrpc_error(
                    None,
                    code=-32603,
                    message=f"Internal error: {exc}",
                    data={"traceback": tb},
                )
            ]

        payload: dict[str, Any] | list[dict[str, Any]]
        payload = responses if isinstance(body, list) else responses[0]
        if _client_accepts_sse(request):
            return _sse_response(payload)
        return JSONResponse(content=payload)

    return router


def _client_accepts_sse(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return _CONTENT_TYPE_SSE in accept.lower()


def _handle_sse_get(request: Request) -> Response:
    accept = request.headers.get("accept", "")
    if _CONTENT_TYPE_SSE not in accept.lower():
        return Response(status_code=405, headers={"Allow": "POST, GET"})
    return StreamingResponse(
        _empty_sse_stream(request),
        media_type=_CONTENT_TYPE_SSE,
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


async def _empty_sse_stream(request: Request) -> AsyncIterator[str]:
    if not await request.is_disconnected():
        yield ": connected\n\n"


def _sse_response(payload: dict[str, Any] | list[dict[str, Any]]) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        yield f"event: message\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"

    return StreamingResponse(
        stream(),
        media_type=_CONTENT_TYPE_SSE,
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


def _is_jsonrpc_request(message: dict[str, Any]) -> bool:
    return "method" in message and "id" in message


def _validate_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is None:
        return
    origin_host = urlparse(origin).netloc
    request_host = request.headers.get("host", "")
    if origin_host and origin_host.lower() == request_host.lower():
        return
    raise HTTPException(status_code=403, detail="Invalid Origin header")


def _extract_api_key(request: Request) -> str | None:
    header_val = request.headers.get("Authorization")
    if header_val:
        if header_val.lower().startswith("bearer "):
            return header_val[7:].strip()
        return header_val.strip()
    return None


async def _build_discovery_document(request: Request, db: AsyncSession) -> dict[str, Any]:
    """Return a public capability document designed for agent bootstrapping."""
    base_url = str(request.base_url).rstrip("/")
    mcp_router = _try_get_registered_mcp_router()
    server_result = await db.execute(select(McpServer))
    servers = server_result.scalars().all()
    group_result = await db.execute(select(Group))
    groups = group_result.scalars().all()

    group_key_counts = await _key_counts_by_scope(db, ApiKey.group_id)
    server_key_counts = await _key_counts_by_scope(db, ApiKey.server_id)

    groups_by_id = {group.id: group for group in groups}
    server_entries: list[dict[str, Any]] = []
    for server in servers:
        group = groups_by_id.get(server.group_id) if server.group_id is not None else None
        auth_required = _server_auth_required_from_counts(
            server=server,
            group=group,
            group_key_counts=group_key_counts,
            server_key_counts=server_key_counts,
        )
        server_entries.append(
            {
                "name": server.name,
                "description": server.description,
                "status": server.status,
                "group": group.name if group is not None else None,
                "endpoint": f"{base_url}/mcp/server/{server.name}",
                "auth_required": auth_required,
                "auth_reason": _auth_reason(
                    auth_required,
                    group,
                    server,
                    group_key_counts,
                    server_key_counts,
                ),
                "tools": _tools_for_discovery(mcp_router, [server], []),
            }
        )

    group_entries = [
        {
            "name": group.name,
            "description": group.description,
            "endpoint": f"{base_url}/mcp/{group.name}",
            "auth_required": group.require_api_key or group_key_counts.get(group.id, 0) > 0,
            "auth_reason": (
                "group requires an API key"
                if group.require_api_key
                else "group has API keys assigned"
                if group_key_counts.get(group.id, 0) > 0
                else "public"
            ),
            "hidden_tools": _parse_json_list(group.hidden_tools),
            "tools": _tools_for_discovery(
                mcp_router,
                [server for server in servers if server.group_id == group.id],
                _parse_json_list(group.hidden_tools),
            ),
        }
        for group in groups
    ]

    public_servers = [entry["name"] for entry in server_entries if not entry["auth_required"]]
    return {
        "name": "MCP Central",
        "description": "Public discovery document for connecting MCP clients and agents.",
        "protocol": {
            "name": "Model Context Protocol",
            "transport": "Streamable HTTP JSON-RPC",
            "jsonrpc": "2.0",
            "protocol_version": "2025-03-26",
            "methods": ["initialize", "ping", "tools/list", "tools/call"],
            "tool_namespacing": "Tools are exposed as '<server>__<tool>'.",
        },
        "auth": {
            "required_by_default": False,
            "accepted_methods": [
                "Authorization: Bearer <api_key>",
                "Authorization: <api_key>",
            ],
            "policy": (
                "Endpoints are public unless their group requires an API key, "
                "or API keys are assigned to the group or server."
            ),
        },
        "endpoints": {
            "discovery": f"{base_url}/.well-known/mcp-central.json",
            "mcp_discovery": f"{base_url}/mcp",
            "global": {
                "url": f"{base_url}/mcp",
                "method": "POST",
                "auth_required": False,
                "description": (
                    "Aggregated MCP JSON-RPC endpoint. Without an API key it exposes only "
                    "public servers; with a valid key it also exposes the key's authorized scope."
                ),
                "public_servers": public_servers,
            },
            "openapi": f"{base_url}/api/openapi.json",
            "docs": f"{base_url}/api/docs",
        },
        "examples": {
            "initialize": {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {},
            },
            "list_tools": {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            "call_tool": {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "server__tool", "arguments": {}},
            },
        },
        "groups": group_entries,
        "servers": server_entries,
    }


def _try_get_registered_mcp_router() -> McpRouter | None:
    try:
        pm = get_process_manager()
    except RuntimeError:
        return None
    if not hasattr(pm, "_mcp_router"):
        return None
    return pm._mcp_router


async def _key_counts_by_scope(db: AsyncSession, column: Any) -> dict[int, int]:
    result = await db.execute(
        select(column, func.count()).where(column.is_not(None)).group_by(column)
    )
    return {int(scope_id): int(count) for scope_id, count in result.all()}


def _server_auth_required_from_counts(
    server: McpServer,
    group: Group | None,
    group_key_counts: dict[int, int],
    server_key_counts: dict[int, int],
) -> bool:
    if server_key_counts.get(server.id, 0) > 0:
        return True
    if group is None:
        return False
    return group.require_api_key or group_key_counts.get(group.id, 0) > 0


def _auth_reason(
    auth_required: bool,
    group: Group | None,
    server: McpServer,
    group_key_counts: dict[int, int],
    server_key_counts: dict[int, int],
) -> str:
    if not auth_required:
        return "public"
    if server_key_counts.get(server.id, 0) > 0:
        return "server has API keys assigned"
    if group is not None and group.require_api_key:
        return "server belongs to a group that requires an API key"
    if group is not None and group_key_counts.get(group.id, 0) > 0:
        return "server belongs to a group with API keys assigned"
    return "API key required"


def _tools_for_discovery(
    mcp_router: McpRouter | None,
    servers: list[McpServer],
    hidden_tools: list[str] | None = None,
) -> list[dict[str, Any]]:
    from hub.mcp.namespace import namespace_tool_name

    server_names = [server.name for server in servers]
    hidden_set = set(hidden_tools or [])
    if mcp_router is not None:
        registered_tools = mcp_router.get_all_namespaced_tools(
            group_server_names=server_names,
            hidden_tools=hidden_tools or [],
        )
        if registered_tools:
            return registered_tools

    fallback_tools: list[dict[str, Any]] = []
    for server in servers:
        for tool in _parse_json_tools(server.manifest_tools):
            name = str(tool.get("name", ""))
            if not name:
                continue
            namespaced = namespace_tool_name(server.name, name)
            if namespaced in hidden_set:
                continue
            namespaced_tool = dict(tool)
            namespaced_tool["name"] = namespaced
            description = str(namespaced_tool.get("description", name))
            namespaced_tool["description"] = f"[{server.name}] {description}"
            namespaced_tool.setdefault("inputSchema", {"type": "object"})
            fallback_tools.append(namespaced_tool)
    return fallback_tools


def _parse_json_list(value: str) -> list[str]:
    import json as _json

    parsed = _json.loads(value)
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _parse_json_tools(value: str) -> list[dict[str, Any]]:
    import json as _json

    parsed = _json.loads(value)
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]
