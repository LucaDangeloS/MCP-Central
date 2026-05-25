"""Tool call counters for MCP usage telemetry."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from hub.database import Base
from hub.models.base import TimestampMixin


class ToolCallCount(Base, TimestampMixin):
    """Aggregated call count for one tool on one MCP server."""

    __tablename__ = "tool_call_counts"
    __table_args__ = (
        UniqueConstraint("server_name", "tool_name", name="uq_tool_call_counts_server_tool"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    server_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(256), nullable=False)
    call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ToolCallCountRead(BaseModel):
    model_config = {"from_attributes": True}

    server_name: str
    tool_name: str
    call_count: int
    last_called_at: datetime | None


class ServerToolCallTotal(BaseModel):
    server_name: str
    call_count: int
