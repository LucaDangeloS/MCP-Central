"""Log retrieval and SSE streaming endpoints."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.api.responses import paginated
from hub.auth.admin import get_current_admin, get_current_admin_from_request
from hub.database import get_db
from hub.models.log_entry import LogEntry, LogEntryRead, LogStream

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/logs", tags=["logs"])

AdminDep = Annotated[str, Depends(get_current_admin)]
DbDep = Annotated[AsyncSession, Depends(get_db)]

# Module-level queue registry: server_name → list of subscriber queues
# Populated by the process manager when new log lines arrive.
_log_subscribers: dict[str, list[asyncio.Queue[str]]] = {}
_ALL_LOGS_KEY = "*"


def _serialize_log_entry(entry: LogEntry) -> dict[str, Any]:
    """Serialize a persisted log entry for SSE clients."""
    return LogEntryRead.model_validate(entry).model_dump(mode="json") | {"line": entry.raw}


def _publish_log_payload(server_name: str, payload: str) -> None:
    """Fan-out an already serialized log payload to matching SSE subscribers."""
    for subscriber_key in (server_name, _ALL_LOGS_KEY):
        subscribers = _log_subscribers.get(subscriber_key)
        if subscribers is None:
            continue

        dead: list[asyncio.Queue[str]] = []
        for q in subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            subscribers.remove(q)


def publish_log_entry(entry: LogEntry) -> None:
    """Publish a persisted log entry to all SSE subscribers."""
    _publish_log_payload(entry.server_name, json.dumps(_serialize_log_entry(entry)))


def publish_log_line(server_name: str, line: str) -> None:
    """Publish a raw log line for callers that do not have a persisted LogEntry."""
    _publish_log_payload(server_name, json.dumps({"server": server_name, "line": line}))


async def write_hub_log(level: str, message: str, raw: str | None = None) -> None:
    """Persist and publish a hub-level application log entry."""
    from hub.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        entry = LogEntry(
            server_name="hub",
            stream=LogStream.hub.value,
            level=level,
            message=message,
            raw=raw or message,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)

    publish_log_entry(entry)


@router.get("", summary="Query recent log entries from DB")
async def query_logs(
    _admin: AdminDep,
    db: DbDep,
    server_name: str | None = None,
    level: str | None = None,
    stream: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    from sqlalchemy import func

    q = select(LogEntry).order_by(LogEntry.timestamp.desc())
    if server_name:
        q = q.where(LogEntry.server_name == server_name)
    if level:
        q = q.where(LogEntry.level == level)
    if stream:
        q = q.where(LogEntry.stream == stream)

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar_one()

    result = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    entries = result.scalars().all()
    return paginated(
        [LogEntryRead.model_validate(e) for e in entries],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/stream", summary="SSE stream of live log lines")
async def stream_logs(
    _admin: Annotated[str, Depends(get_current_admin_from_request)],
    server_name: str | None = None,
) -> StreamingResponse:
    """Open an SSE connection to receive live log output, optionally filtered by server."""

    async def _event_gen() -> AsyncGenerator[str, None]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=500)
        subscriber_key = server_name or _ALL_LOGS_KEY
        _log_subscribers.setdefault(subscriber_key, []).append(q)
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=25.0)
                    yield f"data: {payload}\n\n"
                except TimeoutError:
                    # Send a keep-alive comment
                    yield ": keep-alive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            subs = _log_subscribers.get(subscriber_key, [])
            if q in subs:
                subs.remove(q)

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
