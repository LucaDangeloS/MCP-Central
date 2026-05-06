"""Unit tests for ORM models — round-trip CRUD for every model."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from hub.models.api_key import ApiKey
from hub.models.group import Group
from hub.models.log_entry import LogEntry, LogLevel, LogStream
from hub.models.server import McpServer, ServerStatus


class TestGroupModel:
    async def test_create_and_read(self, db_session: AsyncSession) -> None:
        group = Group(name="test-group", description="A test group")
        db_session.add(group)
        await db_session.flush()
        await db_session.refresh(group)

        assert group.id is not None
        assert group.name == "test-group"
        assert group.require_api_key is False
        assert group.hidden_tools == "[]"

    async def test_update(self, db_session: AsyncSession) -> None:
        group = Group(name="updatable", rate_limit_rpm=60)
        db_session.add(group)
        await db_session.flush()

        group.rate_limit_rpm = 120
        group.description = "updated"
        await db_session.flush()
        await db_session.refresh(group)

        assert group.rate_limit_rpm == 120
        assert group.description == "updated"


class TestMcpServerModel:
    async def test_create_and_read(self, db_session: AsyncSession) -> None:
        server = McpServer(
            name="my-server",
            path="my-server",
            entrypoint_module="main",
            env_vars=json.dumps({"FOO": "bar"}),
        )
        db_session.add(server)
        await db_session.flush()
        await db_session.refresh(server)

        assert server.id is not None
        assert server.name == "my-server"
        assert server.status == ServerStatus.stopped.value
        assert server.pid is None
        assert server.restart_count == 0

    async def test_error_fields_stored_fully(self, db_session: AsyncSession) -> None:
        """last_error must store the full traceback without truncation."""
        long_traceback = "Traceback (most recent call last):\n" + ("  File 'module.py', line 42, in some_function\n" * 100) + "ValueError: bad"

        server = McpServer(name="errored", path="errored")
        db_session.add(server)
        await db_session.flush()

        server.last_error = long_traceback
        server.last_error_at = datetime.now(timezone.utc)
        server.status = ServerStatus.error.value
        await db_session.flush()
        await db_session.refresh(server)

        assert server.last_error == long_traceback
        assert len(server.last_error) > 1000

    async def test_group_association(self, db_session: AsyncSession) -> None:
        group = Group(name="my-group")
        db_session.add(group)
        await db_session.flush()

        server = McpServer(name="grouped-server", path="grouped-server", group_id=group.id)
        db_session.add(server)
        await db_session.flush()
        await db_session.refresh(server)

        assert server.group_id == group.id


class TestApiKeyModel:
    async def test_create_and_read(self, db_session: AsyncSession) -> None:
        group = Group(name="key-group")
        db_session.add(group)
        await db_session.flush()

        key = ApiKey(
            label="My Key",
            key_hash="a" * 64,
            key_prefix="abcd1234",
            group_id=group.id,
        )
        db_session.add(key)
        await db_session.flush()
        await db_session.refresh(key)

        assert key.id is not None
        assert key.label == "My Key"
        assert key.key_hash == "a" * 64


class TestLogEntryModel:
    async def test_create_log_entry(self, db_session: AsyncSession) -> None:
        entry = LogEntry(
            server_name="my-server",
            stream=LogStream.stderr.value,
            level=LogLevel.error.value,
            message="Something failed",
            raw="Traceback...\nValueError: oops",
        )
        db_session.add(entry)
        await db_session.flush()
        await db_session.refresh(entry)

        assert entry.id is not None
        assert entry.stream == "stderr"
        assert entry.level == "error"

    async def test_full_traceback_preserved(self, db_session: AsyncSession) -> None:
        """Tracebacks must be stored verbatim — no truncation."""
        tb = "\n".join([f"  File 'module.py', line {i}, in func" for i in range(200)])
        entry = LogEntry(
            server_name="crashy",
            stream=LogStream.stderr.value,
            level=LogLevel.error.value,
            message="Unhandled exception",
            raw=tb,
        )
        db_session.add(entry)
        await db_session.flush()
        await db_session.refresh(entry)

        assert entry.raw == tb
