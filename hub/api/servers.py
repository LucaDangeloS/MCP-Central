"""MCP server CRUD + lifecycle action endpoints."""

from __future__ import annotations

import json
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.api.responses import ok, paginated
from hub.auth.admin import get_current_admin
from hub.database import get_db
from hub.models.server import McpServer, ServerCreate, ServerRead, ServerStatus, ServerUpdate
from hub.models.tool_call import ToolCallCount
from hub.process.health import get_process_manager

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/servers", tags=["servers"])

AdminDep = Annotated[str, Depends(get_current_admin)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


async def _get_server_or_404(db: AsyncSession, name: str) -> McpServer:
    result = await db.execute(
        select(McpServer).where(McpServer.name == name)
    )
    server = result.scalar_one_or_none()
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server '{name}' not found",
        )
    return server


@router.get("", summary="List all MCP servers")
async def list_servers(
    _admin: AdminDep,
    db: DbDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    group_id: int | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
) -> dict[str, Any]:
    q = select(McpServer)
    if group_id is not None:
        q = q.where(McpServer.group_id == group_id)
    if status_filter is not None:
        q = q.where(McpServer.status == status_filter)

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar_one()

    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    servers = result.scalars().all()

    return paginated(
        [ServerRead.model_validate(s) for s in servers],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Register a new MCP server")
async def create_server(
    payload: ServerCreate,
    _admin: AdminDep,
    db: DbDep,
) -> dict[str, Any]:
    # Check for duplicate name
    existing = await db.execute(
        select(McpServer).where(McpServer.name == payload.name)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Server named '{payload.name}' already exists",
        )

    server = McpServer(
        name=payload.name,
        description=payload.description,
        path=payload.path,
        entrypoint_module=payload.entrypoint_module,
        language=payload.language.value,
        launch_command=payload.launch_command,
        launch_args=json.dumps(payload.launch_args),
        env_vars=json.dumps(payload.env_vars),
        disabled_tools=json.dumps(payload.disabled_tools),
        manifest_tools=json.dumps(payload.manifest_tools),
        python_version_constraint=payload.python_version_constraint,
        source_type=payload.source_type,
        install_on_start=payload.install_on_start,
        auto_start=payload.auto_start,
        restart_on_error=payload.restart_on_error,
        group_id=payload.group_id,
        status=ServerStatus.stopped.value,
    )
    db.add(server)
    await db.flush()
    await db.refresh(server)
    logger.info("server_registered", server_name=server.name)
    return ok(ServerRead.model_validate(server))


@router.get("/{name}", summary="Get a single MCP server")
async def get_server(
    name: str,
    _admin: AdminDep,
    db: DbDep,
) -> dict[str, Any]:
    server = await _get_server_or_404(db, name)
    return ok(ServerRead.model_validate(server))


@router.patch("/{name}", summary="Update MCP server metadata")
async def update_server(
    name: str,
    payload: ServerUpdate,
    _admin: AdminDep,
    db: DbDep,
) -> dict[str, Any]:
    server = await _get_server_or_404(db, name)

    if payload.description is not None:
        server.description = payload.description
    if payload.entrypoint_module is not None:
        server.entrypoint_module = payload.entrypoint_module
    if payload.language is not None:
        server.language = payload.language.value
    if payload.launch_command is not None:
        server.launch_command = payload.launch_command
    if payload.launch_args is not None:
        server.launch_args = json.dumps(payload.launch_args)
    if payload.env_vars is not None:
        server.env_vars = json.dumps(payload.env_vars)
    if payload.disabled_tools is not None:
        server.disabled_tools = json.dumps(payload.disabled_tools)
    if payload.manifest_tools is not None:
        server.manifest_tools = json.dumps(payload.manifest_tools)
    if payload.install_on_start is not None:
        server.install_on_start = payload.install_on_start
    if payload.auto_start is not None:
        server.auto_start = payload.auto_start
    if payload.restart_on_error is not None:
        server.restart_on_error = payload.restart_on_error
    if "group_id" in payload.model_fields_set:
        server.group_id = payload.group_id

    await db.flush()
    await db.refresh(server)
    logger.info("server_updated", server_name=server.name)
    return ok(ServerRead.model_validate(server))


@router.get("/{name}/tools", summary="List tools exposed by a running MCP server")
async def list_server_tools(
    name: str,
    _admin: AdminDep,
    db: DbDep,
) -> dict[str, Any]:
    """Return the raw tool list from the MCP server's in-memory registry.

    Works only while the server is running; returns an empty list otherwise.
    """
    await _get_server_or_404(db, name)
    pm = get_process_manager()
    if not hasattr(pm, "_mcp_router"):
        return ok([])
    mcp_router = pm._mcp_router
    # Return un-namespaced tools so the UI sees original names + descriptions
    tools: list[dict[str, Any]] = [dict(tool) for tool in mcp_router._tool_registry.get(name, [])]
    counts_result = await db.execute(
        select(ToolCallCount).where(ToolCallCount.server_name == name)
    )
    counts = {row.tool_name: row.call_count for row in counts_result.scalars().all()}
    for tool in tools:
        tool["call_count"] = counts.get(str(tool.get("name", "")), 0)
    return ok(tools)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an MCP server")
async def delete_server(
    name: str,
    _admin: AdminDep,
    db: DbDep,
) -> None:
    server = await _get_server_or_404(db, name)
    try:
        pm = get_process_manager()
        await pm.stop_server(name)
    except RuntimeError:
        logger.warning("delete_server_process_manager_unavailable", server_name=name)
    except Exception as exc:
        import traceback

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": f"Failed to stop server '{name}' before deletion: {exc}",
                "traceback": traceback.format_exc(),
            },
        ) from exc
    await db.delete(server)
    logger.info("server_deleted", server_name=server.name)


# ------------------------------------------------------------------ #
# Lifecycle action endpoints                                           #
# ------------------------------------------------------------------ #


@router.post("/{name}/start", summary="Start an MCP server process")
async def start_server(
    name: str,
    _admin: AdminDep,
    db: DbDep,
) -> dict[str, Any]:
    await _get_server_or_404(db, name)
    pm = get_process_manager()
    try:
        await pm.start_server(name)
    except Exception as exc:
        import traceback
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": f"Failed to start server '{name}': {exc}",
                "traceback": traceback.format_exc(),
            },
        ) from exc
    server = await _get_server_or_404(db, name)
    return ok(ServerRead.model_validate(server))


@router.post("/{name}/stop", summary="Stop an MCP server process")
async def stop_server(
    name: str,
    _admin: AdminDep,
    db: DbDep,
) -> dict[str, Any]:
    await _get_server_or_404(db, name)
    pm = get_process_manager()
    await pm.stop_server(name)
    server = await _get_server_or_404(db, name)
    return ok(ServerRead.model_validate(server))


@router.post("/{name}/restart", summary="Restart an MCP server process")
async def restart_server(
    name: str,
    _admin: AdminDep,
    db: DbDep,
) -> dict[str, Any]:
    await _get_server_or_404(db, name)
    pm = get_process_manager()
    try:
        await pm.restart_server(name)
    except Exception as exc:
        import traceback
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": f"Failed to restart server '{name}': {exc}",
                "traceback": traceback.format_exc(),
            },
        ) from exc
    server = await _get_server_or_404(db, name)
    return ok(ServerRead.model_validate(server))
