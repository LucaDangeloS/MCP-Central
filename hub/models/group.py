"""Group ORM model + Pydantic schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hub.database import Base
from hub.models.base import TimestampMixin

_NAME_PATTERN = r"^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$"


class Group(Base, TimestampMixin):
    """A logical container for MCP servers sharing auth + visibility rules."""

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    require_api_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # JSON-encoded list of tool names to hide, e.g. '["server__tool_name"]'
    hidden_tools: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # requests per minute; 0 = unlimited
    rate_limit_rpm: Mapped[int] = mapped_column(nullable=False, default=0)

    # Relationships
    servers: Mapped[list["McpServer"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "McpServer", back_populates="group", lazy="selectin"
    )
    api_keys: Mapped[list["ApiKey"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "ApiKey", back_populates="group", lazy="selectin"
    )


# ------------------------------------------------------------------ #
# Pydantic schemas                                                     #
# ------------------------------------------------------------------ #


class GroupCreate(BaseModel):
    name: str = Field(..., pattern=_NAME_PATTERN)
    description: str = Field(default="", max_length=500)
    require_api_key: bool = False
    hidden_tools: list[str] = Field(default_factory=list)
    rate_limit_rpm: int = Field(default=0, ge=0)


class GroupUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    require_api_key: bool | None = None
    hidden_tools: list[str] | None = None
    rate_limit_rpm: int | None = Field(default=None, ge=0)


class GroupRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    description: str
    require_api_key: bool
    hidden_tools: list[str]
    rate_limit_rpm: int
    created_at: datetime
    updated_at: datetime

    @field_validator("hidden_tools", mode="before")
    @classmethod
    def parse_hidden_tools(cls, v: object) -> list[str]:
        import json

        if isinstance(v, str):
            return json.loads(v)  # type: ignore[no-any-return]
        return v  # type: ignore[return-value]
