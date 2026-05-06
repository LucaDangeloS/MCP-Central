"""Admin JWT authentication."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from hub.config import get_settings

logger = structlog.get_logger(__name__)

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def verify_admin_credentials(username: str, password: str) -> bool:
    """Verify username/password against configured admin credentials."""
    settings = get_settings()
    if username != settings.admin_username:
        return False
    # Compare against the raw password from settings.
    # In production the user sets ADMIN_PASSWORD in .env.
    return verify_password(password, hash_password(settings.admin_password))


def _make_token(sub: str, token_type: str, expire_minutes: int) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=expire_minutes)
    payload = {
        "sub": sub,
        "type": token_type,
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(username: str) -> str:
    settings = get_settings()
    return _make_token(username, TOKEN_TYPE_ACCESS, settings.access_token_expire_minutes)


def create_refresh_token(username: str) -> str:
    settings = get_settings()
    return _make_token(username, TOKEN_TYPE_REFRESH, settings.refresh_token_expire_minutes)


async def get_current_admin(
    token: Annotated[str, Depends(_oauth2_scheme)],
) -> str:
    """FastAPI dependency — validates JWT and returns the admin username."""
    return _validate_access_token(token)


async def get_current_admin_from_request(request: Request) -> str:
    """Validate admin auth from a bearer header or `token` query parameter.

    Browser EventSource cannot set Authorization headers, so SSE endpoints use this dependency.
    """
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return _validate_access_token(auth_header[7:].strip())

    token = request.query_params.get("token")
    if token:
        return _validate_access_token(token)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _validate_access_token(token: str) -> str:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        username: str | None = payload.get("sub")
        token_type: str | None = payload.get("type")
        if username is None or token_type != TOKEN_TYPE_ACCESS:
            raise credentials_exc
    except JWTError as exc:
        logger.warning("jwt_validation_failed", error=str(exc))
        raise credentials_exc from exc
    return username
