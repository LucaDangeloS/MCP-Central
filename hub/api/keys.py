"""API key management endpoints."""

from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.api.responses import ok, paginated
from hub.auth.admin import get_current_admin
from hub.auth.api_keys import generate_api_key
from hub.database import get_db
from hub.models.api_key import ApiKey, ApiKeyCreate, ApiKeyCreated, ApiKeyRead
from hub.models.group import Group
from hub.models.server import McpServer

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/keys", tags=["api-keys"])

AdminDep = Annotated[str, Depends(get_current_admin)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("", summary="List API keys (metadata only, no plaintext)")
async def list_keys(
    _admin: AdminDep,
    db: DbDep,
    group_id: int | None = None,
    server_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    q = select(ApiKey)
    if group_id is not None:
        q = q.where(ApiKey.group_id == group_id)
    if server_id is not None:
        q = q.where(ApiKey.server_id == server_id)

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar_one()

    result = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    keys = result.scalars().all()
    return paginated(
        [ApiKeyRead.model_validate(k) for k in keys],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a new API key")
async def create_key(
    payload: ApiKeyCreate,
    _admin: AdminDep,
    db: DbDep,
) -> dict[str, Any]:
    if payload.group_id is not None:
        group_result = await db.execute(
            select(Group).where(Group.id == payload.group_id)
        )
        if group_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    if payload.server_id is not None:
        server_result = await db.execute(
            select(McpServer).where(
                McpServer.id == payload.server_id,
            )
        )
        if server_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="MCP server not found",
            )

    plaintext, key_hash, key_prefix = generate_api_key()

    api_key = ApiKey(
        label=payload.label,
        description=payload.description,
        key_hash=key_hash,
        key_prefix=key_prefix,
        group_id=payload.group_id,
        server_id=payload.server_id,
    )
    db.add(api_key)
    await db.flush()
    await db.refresh(api_key)

    logger.info(
        "api_key_created",
        label=api_key.label,
        group_id=api_key.group_id,
        server_id=api_key.server_id,
        prefix=key_prefix,
    )
    # Build response manually — plaintext_key is never stored, only returned once here
    response = ApiKeyCreated(
        id=api_key.id,
        label=api_key.label,
        description=api_key.description,
        key_prefix=api_key.key_prefix,
        group_id=api_key.group_id,
        server_id=api_key.server_id,
        created_at=api_key.created_at,
        plaintext_key=plaintext,
    )
    return ok(response)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke an API key")
async def revoke_key(
    key_id: int,
    _admin: AdminDep,
    db: DbDep,
) -> None:
    from datetime import UTC, datetime

    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

    await db.delete(api_key)
    logger.info("api_key_revoked", key_id=key_id, label=api_key.label)
