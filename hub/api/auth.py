"""Admin authentication endpoints."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from hub.auth.admin import create_access_token, create_refresh_token, verify_admin_credentials

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@router.post("/token", response_model=TokenResponse, summary="Obtain admin JWT tokens")
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> TokenResponse:
    """Exchange admin username + password for access + refresh JWT tokens."""
    if not verify_admin_credentials(form.username, form.password):
        logger.warning("failed_admin_login", username=form.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    logger.info("admin_login_success", username=form.username)
    return TokenResponse(
        access_token=create_access_token(form.username),
        refresh_token=create_refresh_token(form.username),
    )
