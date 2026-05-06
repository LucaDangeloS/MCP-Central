"""Group CRUD endpoints."""

from __future__ import annotations

import json
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.api.responses import ok, paginated
from hub.auth.admin import get_current_admin
from hub.database import get_db
from hub.models.group import Group, GroupCreate, GroupRead, GroupUpdate

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/groups", tags=["groups"])

AdminDep = Annotated[str, Depends(get_current_admin)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


async def _get_group_or_404(db: AsyncSession, name: str) -> Group:
    result = await db.execute(
        select(Group).where(Group.name == name)
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Group '{name}' not found")
    return group


@router.get("", summary="List all groups")
async def list_groups(
    _admin: AdminDep,
    db: DbDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    total_result = await db.execute(
        select(func.count()).select_from(
            select(Group).subquery()
        )
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(Group)
        
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    groups = result.scalars().all()
    return paginated([GroupRead.model_validate(g) for g in groups], total=total, page=page, page_size=page_size)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a group")
async def create_group(
    payload: GroupCreate,
    _admin: AdminDep,
    db: DbDep,
) -> dict[str, Any]:
    existing = await db.execute(
        select(Group).where(Group.name == payload.name)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Group '{payload.name}' already exists")

    group = Group(
        name=payload.name,
        description=payload.description,
        require_api_key=payload.require_api_key,
        hidden_tools=json.dumps(payload.hidden_tools),
        rate_limit_rpm=payload.rate_limit_rpm,
    )
    db.add(group)
    await db.flush()
    await db.refresh(group)
    logger.info("group_created", group_name=group.name)
    return ok(GroupRead.model_validate(group))


@router.get("/{name}", summary="Get a group")
async def get_group(name: str, _admin: AdminDep, db: DbDep) -> dict[str, Any]:
    group = await _get_group_or_404(db, name)
    return ok(GroupRead.model_validate(group))


@router.patch("/{name}", summary="Update a group")
async def update_group(
    name: str,
    payload: GroupUpdate,
    _admin: AdminDep,
    db: DbDep,
) -> dict[str, Any]:
    group = await _get_group_or_404(db, name)

    if payload.description is not None:
        group.description = payload.description
    if payload.require_api_key is not None:
        group.require_api_key = payload.require_api_key
    if payload.hidden_tools is not None:
        group.hidden_tools = json.dumps(payload.hidden_tools)
    if payload.rate_limit_rpm is not None:
        group.rate_limit_rpm = payload.rate_limit_rpm

    await db.flush()
    await db.refresh(group)
    logger.info("group_updated", group_name=group.name)
    return ok(GroupRead.model_validate(group))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a group")
async def delete_group(name: str, _admin: AdminDep, db: DbDep) -> None:
    from datetime import datetime, timezone

    group = await _get_group_or_404(db, name)
    await db.delete(group)
    logger.info("group_deleted", group_name=group.name)
