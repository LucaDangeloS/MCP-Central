"""Shared response envelope helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Meta(BaseModel):
    timestamp: str
    total: int | None = None
    page: int | None = None
    page_size: int | None = None


def ok(data: Any, **meta_kwargs: Any) -> dict[str, Any]:
    """Wrap a payload in the standard success envelope."""
    return {
        "data": data,
        "meta": Meta(timestamp=_now_iso(), **meta_kwargs).model_dump(exclude_none=True),
    }


def paginated(
    data: Any,
    total: int,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    return {
        "data": data,
        "meta": Meta(
            timestamp=_now_iso(), total=total, page=page, page_size=page_size
        ).model_dump(),
    }
