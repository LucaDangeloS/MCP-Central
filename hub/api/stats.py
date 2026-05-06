"""Statistics endpoints for the dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.api.responses import ok
from hub.auth.admin import get_current_admin
from hub.database import get_db
from hub.models.log_entry import LogEntry, LogLevel
from hub.models.server import McpServer, ServerStatus

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/stats", tags=["stats"])

AdminDep = Annotated[str, Depends(get_current_admin)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("", summary="Dashboard statistics overview")
async def get_stats(
    _admin: AdminDep,
    db: DbDep,
) -> dict[str, Any]:
    # Server counts by status
    status_counts_result = await db.execute(
        select(McpServer.status, func.count().label("count"))
        
        .group_by(McpServer.status)
    )
    status_counts: dict[str, int] = {row.status: row.count for row in status_counts_result}

    total_servers = sum(status_counts.values())
    running_servers = status_counts.get(ServerStatus.running.value, 0)
    error_servers = status_counts.get(ServerStatus.error.value, 0)
    stopped_servers = status_counts.get(ServerStatus.stopped.value, 0)

    # Error log count in last hour
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    error_count_result = await db.execute(
        select(func.count())
        .select_from(LogEntry)
        .where(
            LogEntry.level == LogLevel.error.value,
            LogEntry.timestamp >= one_hour_ago,
        )
    )
    errors_last_hour = error_count_result.scalar_one()

    # Total log lines per server (last 24h)
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    log_activity_result = await db.execute(
        select(LogEntry.server_name, func.count().label("count"))
        .where(LogEntry.timestamp >= since_24h)
        .group_by(LogEntry.server_name)
    )
    log_activity = {row.server_name: row.count for row in log_activity_result}

    return ok(
        {
            "servers": {
                "total": total_servers,
                "running": running_servers,
                "error": error_servers,
                "stopped": stopped_servers,
                "by_status": status_counts,
            },
            "logs": {
                "errors_last_hour": errors_last_hour,
                "activity_last_24h": log_activity,
            },
        }
    )


@router.get("/health", summary="Hub health check (no auth required)", include_in_schema=True)
async def health_check() -> dict[str, Any]:
    """Lightweight health probe used by Docker's healthcheck and load balancers."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}
