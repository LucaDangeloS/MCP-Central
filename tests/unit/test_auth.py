"""Unit tests for authentication helpers."""

from __future__ import annotations

import time

from jose import jwt

from hub.auth.admin import (
    TOKEN_TYPE_ACCESS,
    TOKEN_TYPE_REFRESH,
    create_access_token,
    create_refresh_token,
    get_current_admin_from_request,
    hash_password,
    verify_admin_credentials,
    verify_password,
)
from hub.auth.api_keys import generate_api_key, hash_key
from hub.config import get_settings


class TestPasswordHashing:
    def test_hash_and_verify(self) -> None:
        hashed = hash_password("mysecret")
        assert verify_password("mysecret", hashed) is True
        assert verify_password("wrongpassword", hashed) is False

    def test_different_hashes_for_same_password(self) -> None:
        # bcrypt uses a random salt — each hash call produces a unique digest
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2

    def test_hash_output_is_string(self) -> None:
        hashed = hash_password("test")
        assert isinstance(hashed, str)
        assert hashed.startswith("$2b$")


class TestAdminCredentials:
    def test_valid_credentials(self) -> None:
        assert verify_admin_credentials("admin", "testpassword") is True

    def test_wrong_password(self) -> None:
        assert verify_admin_credentials("admin", "wrong") is False

    def test_wrong_username(self) -> None:
        assert verify_admin_credentials("notadmin", "testpassword") is False


class TestJwtTokens:
    def test_access_token_claims(self) -> None:
        settings = get_settings()
        token = create_access_token("admin")
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["sub"] == "admin"
        assert payload["type"] == TOKEN_TYPE_ACCESS
        assert payload["exp"] > time.time()

    def test_refresh_token_claims(self) -> None:
        settings = get_settings()
        token = create_refresh_token("admin")
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["type"] == TOKEN_TYPE_REFRESH

    def test_access_token_expires_after_refresh(self) -> None:
        settings = get_settings()
        access = create_access_token("admin")
        refresh = create_refresh_token("admin")
        access_payload = jwt.decode(
            access, settings.secret_key, algorithms=[settings.jwt_algorithm]
        )
        refresh_payload = jwt.decode(
            refresh, settings.secret_key, algorithms=[settings.jwt_algorithm]
        )
        # Refresh token lives longer than access token
        assert refresh_payload["exp"] > access_payload["exp"]

    async def test_query_token_auth_for_eventsource(self) -> None:
        from starlette.requests import Request

        token = create_access_token("admin")
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/logs/stream",
                "headers": [],
                "query_string": f"token={token}".encode(),
            }
        )

        assert await get_current_admin_from_request(request) == "admin"


class TestApiKeyGeneration:
    def test_generate_returns_three_parts(self) -> None:
        plaintext, key_hash, key_prefix = generate_api_key()
        assert len(plaintext) == 64  # 32 bytes → 64 hex chars
        assert len(key_hash) == 64  # SHA-256 → 64 hex chars
        assert len(key_prefix) == 8
        assert plaintext.startswith(key_prefix)

    def test_hash_is_deterministic(self) -> None:
        plaintext, key_hash, _ = generate_api_key()
        assert hash_key(plaintext) == key_hash

    def test_different_keys_each_call(self) -> None:
        k1, _, _ = generate_api_key()
        k2, _, _ = generate_api_key()
        assert k1 != k2

    def test_hash_key_sha256(self) -> None:
        import hashlib

        plaintext = "deadbeef" * 8
        expected = hashlib.sha256(plaintext.encode()).hexdigest()
        assert hash_key(plaintext) == expected
