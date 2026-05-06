"""LogEntry ORM model + Pydantic schemas."""

from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from hub.database import Base


class LogLevel(str, enum.Enum):
    debug = "debug"
    info = "info"
    warning = "warning"
    error = "error"
    critical = "critical"


class LogStream(str, enum.Enum):
    stdout = "stdout"
    stderr = "stderr"
    hub = "hub"


class LogEntry(Base):
    """A single log line captured from an MCP server subprocess or from the hub itself."""

    __tablename__ = "log_entries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    server_name: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # "hub" for hub-level logs
    stream: Mapped[str] = mapped_column(
        String(8), nullable=False, default=LogStream.stdout.value
    )
    level: Mapped[str] = mapped_column(String(8), nullable=False, default=LogLevel.info.value)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # For stderr tracebacks this is the full multi-line string
    raw: Mapped[str] = mapped_column(Text, nullable=False, default="")
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # Index for efficient per-server + time-range queries
    __table_args__ = (
        # Composite index for the most common query pattern
        # (server_name, timestamp DESC)
        # SQLAlchemy doesn't support inline __table_args__ on Mapped columns;
        # defined below as a class attribute
    )


from sqlalchemy import Index  # noqa: E402 (placed after class for readability)

Index("ix_log_entries_server_ts", LogEntry.server_name, LogEntry.timestamp.desc())


# ------------------------------------------------------------------ #
# Pydantic schemas                                                     #
# ------------------------------------------------------------------ #


class LogEntryRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    server_name: str
    stream: str
    level: str
    message: str
    raw: str
    timestamp: datetime
