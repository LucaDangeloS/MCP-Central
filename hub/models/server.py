"""McpServer ORM model + Pydantic schemas."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hub.database import Base
from hub.models.base import TimestampMixin

_NAME_PATTERN = r"^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$"


class ServerStatus(enum.StrEnum):
    stopped = "stopped"
    starting = "starting"
    running = "running"
    error = "error"
    restarting = "restarting"


class McpServer(Base, TimestampMixin):
    """A registered MCP server managed by this hub."""

    __tablename__ = "mcp_servers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Filesystem path relative to servers_dir
    path: Mapped[str] = mapped_column(String(256), nullable=False)
    # Python module entrypoint, e.g. "main" or "mypackage.server"
    entrypoint_module: Mapped[str] = mapped_column(String(256), nullable=False, default="main")
    # JSON-encoded env vars to inject (non-secret metadata only; secrets come from .env)
    env_vars: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # JSON-encoded list of tool names (un-namespaced) that are disabled for this server
    disabled_tools: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # Python version constraint string, e.g. ">=3.10"
    python_version_constraint: Mapped[str] = mapped_column(
        String(32), nullable=False, default=""
    )

    # Lifecycle
    auto_start: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    restart_on_error: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ServerStatus.stopped.value
    )
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    restart_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Last error traceback (full, never truncated)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    last_error_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)

    # Group membership (nullable = no group)
    group_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("groups.id", name="fk_mcp_servers_groups"),
        nullable=True,
        default=None,
    )
    group: Mapped[Group | None] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Group", back_populates="servers"
    )
    api_keys: Mapped[list[ApiKey]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "ApiKey", back_populates="server", lazy="selectin"
    )


# ------------------------------------------------------------------ #
# Pydantic schemas                                                     #
# ------------------------------------------------------------------ #


class ServerCreate(BaseModel):
    name: str = Field(..., pattern=_NAME_PATTERN)
    description: str = Field(default="", max_length=500)
    path: str
    entrypoint_module: str = "main"
    env_vars: dict[str, str] = Field(default_factory=dict)
    disabled_tools: list[str] = Field(default_factory=list)
    python_version_constraint: str = ""
    auto_start: bool = True
    restart_on_error: bool = True
    group_id: int | None = None


class ServerUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    entrypoint_module: str | None = None
    env_vars: dict[str, str] | None = None
    disabled_tools: list[str] | None = None
    auto_start: bool | None = None
    restart_on_error: bool | None = None
    group_id: int | None = None


class ServerRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    description: str
    path: str
    entrypoint_module: str
    env_vars: dict[str, Any]
    disabled_tools: list[str]
    python_version_constraint: str
    auto_start: bool
    restart_on_error: bool
    status: str
    pid: int | None
    restart_count: int
    last_error: str | None
    last_error_at: datetime | None
    group_id: int | None
    created_at: datetime
    updated_at: datetime

    @field_validator("env_vars", mode="before")
    @classmethod
    def parse_env_vars(cls, v: object) -> dict[str, Any]:
        import json

        if isinstance(v, str):
            return json.loads(v)  # type: ignore[no-any-return]
        return v  # type: ignore[return-value]

    @field_validator("disabled_tools", mode="before")
    @classmethod
    def parse_disabled_tools(cls, v: object) -> list[str]:
        import json

        if isinstance(v, str):
            return json.loads(v)  # type: ignore[no-any-return]
        return v  # type: ignore[return-value]
