"""ApiKey ORM model + Pydantic schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hub.database import Base
from hub.models.base import TimestampMixin


class ApiKey(Base, TimestampMixin):
    """An API key granting access to one group or one MCP server endpoint."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Human-readable label set by the admin
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    # SHA-256 hex digest of the plaintext key — the plaintext is NEVER stored
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    # First 8 chars of the plaintext key shown in UI as a hint (safe to store)
    key_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    # Optional description
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    group_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("groups.id", name="fk_api_keys_groups"),
        nullable=True,
        index=True,
    )
    group: Mapped[Group | None] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Group", back_populates="api_keys"
    )
    server_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("mcp_servers.id", name="fk_api_keys_mcp_servers"),
        nullable=True,
        index=True,
    )
    server: Mapped[McpServer | None] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "McpServer", back_populates="api_keys"
    )


# ------------------------------------------------------------------ #
# Pydantic schemas                                                     #
# ------------------------------------------------------------------ #


class ApiKeyCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=500)
    group_id: int | None = None
    server_id: int | None = None

    @model_validator(mode="after")
    def validate_single_scope(self) -> ApiKeyCreate:
        if (self.group_id is None) == (self.server_id is None):
            raise ValueError("Exactly one of group_id or server_id is required")
        return self


class ApiKeyRead(BaseModel):
    """Returned for all operations EXCEPT creation (which also returns `plaintext_key`)."""

    model_config = {"from_attributes": True}

    id: int
    label: str
    description: str
    key_prefix: str
    group_id: int | None
    server_id: int | None
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    """Returned only on creation — includes the plaintext key shown exactly once."""

    plaintext_key: str
