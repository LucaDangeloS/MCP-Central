"""E2E tests for log streaming endpoints."""

from __future__ import annotations

import asyncio
import json

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from hub.api import logs
from hub.models.log_entry import LogEntry, LogLevel, LogStream


class TestLogStreaming:
    async def test_stream_logs_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/logs/stream?server_name=test-srv")

        assert resp.status_code == 401

    async def test_published_stream_payload_contains_log_entry_fields(
        self, db_session: AsyncSession
    ) -> None:
        entry = LogEntry(
            server_name="test-srv",
            stream=LogStream.stderr.value,
            level=LogLevel.error.value,
            message="first line",
            raw="first line\nsecond line",
        )
        db_session.add(entry)
        await db_session.commit()
        await db_session.refresh(entry)

        q: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        logs._log_subscribers.setdefault("*", []).append(q)
        try:
            logs.publish_log_entry(entry)
            payload = json.loads(await asyncio.wait_for(q.get(), timeout=1.0))
        finally:
            logs._log_subscribers["*"].remove(q)

        assert payload["id"] == entry.id
        assert payload["server_name"] == "test-srv"
        assert payload["stream"] == "stderr"
        assert payload["level"] == "error"
        assert payload["message"] == "first line"
        assert payload["raw"] == "first line\nsecond line"
        assert payload["line"] == "first line\nsecond line"
        assert isinstance(payload["timestamp"], str)

    async def test_query_logs_returns_recent_entries(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        db_session.add(
            LogEntry(
                server_name="hub",
                stream=LogStream.hub.value,
                level=LogLevel.info.value,
                message="hub_started",
                raw="hub_started port=8000",
            )
        )
        await db_session.commit()

        resp = await client.get("/api/v1/logs?server_name=hub", headers=auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"][0]["server_name"] == "hub"
        assert body["data"][0]["message"] == "hub_started"
