"""API key authentication for MCP group endpoints."""

from __future__ import annotations

import hashlib
import secrets
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.database import get_db
from hub.models.api_key import ApiKey

logger = structlog.get_logger(__name__)

_KEY_LENGTH = 32  # bytes → 64 hex chars

_header_scheme = APIKeyHeader(name="Authorization", auto_error=False)


def generate_api_key() -> tuple[str, str, str]:
    """Return (plaintext_key, key_hash, key_prefix).

    The plaintext is shown once to the user and never persisted.
    Only key_hash (SHA-256) and key_prefix are stored.
    """
    plaintext = secrets.token_hex(_KEY_LENGTH)
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    key_prefix = plaintext[:8]
    return plaintext, key_hash, key_prefix


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


async def verify_api_key(
    header_value: Annotated[str | None, Security(_header_scheme)] = None,
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    """Resolve and validate an API key from the request.

    Accepts:
    - ``Authorization: Bearer <key>`` header
    """
    raw: str | None = None

    if header_value:
        if header_value.lower().startswith("bearer "):
            raw = header_value[7:].strip()
        else:
            raw = header_value.strip()

    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
        )

    key_hash = hash_key(raw)

    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash)
    )
    api_key = result.scalar_one_or_none()

    if api_key is None:
        logger.warning("invalid_api_key_attempt", key_prefix=raw[:8])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key",
        )

    return api_key


class ApiKeyAuth:
    """Callable dependency that checks an API key belongs to a specific group."""

    def __init__(self, group_name: str) -> None:
        self.group_name = group_name

    async def __call__(
        self,
        api_key: Annotated[ApiKey, Depends(verify_api_key)],
    ) -> ApiKey:
        if api_key.group is None or api_key.group.name != self.group_name:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key is not authorised for group '{self.group_name}'",
            )
        return api_key
