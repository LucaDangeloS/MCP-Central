"""Runtime configuration exposed to the admin UI."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from hub.api.responses import ok
from hub.auth.admin import get_current_admin
from hub.config import get_settings

router = APIRouter(prefix="/config", tags=["config"])

AdminDep = Annotated[str, Depends(get_current_admin)]


@router.get("", summary="Runtime UI configuration")
async def get_runtime_config(
    _admin: AdminDep,
    request: Request,
) -> dict[str, Any]:
    settings = get_settings()
    service_url = settings.service_url or str(request.base_url).rstrip("/")
    return ok({"service_url": service_url})
