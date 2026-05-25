"""Hub configuration — all values sourced from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # Core                                                                 #
    # ------------------------------------------------------------------ #
    hub_port: int = Field(default=8000, description="Port the hub listens on")
    debug: bool = Field(default=False, description="Enable debug mode (verbose logging)")
    secret_key: str = Field(
        default="CHANGE_ME_IN_PRODUCTION_USE_A_LONG_RANDOM_STRING",
        description="Secret key used to sign JWT tokens",
    )

    # ------------------------------------------------------------------ #
    # Admin credentials                                                    #
    # ------------------------------------------------------------------ #
    admin_username: str = Field(default="admin", description="Admin UI username")
    admin_password: str = Field(
        default="CHANGE_ME",
        description="Admin UI password (hashed at first start)",
    )
    jwt_algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=60 * 24)      # 24 h
    refresh_token_expire_minutes: int = Field(default=60 * 24 * 7)  # 7 days

    # ------------------------------------------------------------------ #
    # Paths                                                                #
    # ------------------------------------------------------------------ #
    data_dir: Path = Field(default=Path("/app/data"), description="Persistent data directory")
    servers_dir: Path = Field(default=Path("/app/servers"), description="MCP server packages")
    logs_dir: Path = Field(default=Path("/app/data/logs"), description="Log file directory")

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.data_dir / 'central.db'}"

    # ------------------------------------------------------------------ #
    # Network filtering / proxy                                            #
    # ------------------------------------------------------------------ #
    proxy_port: int = Field(default=8888, description="tinyproxy listen port")
    blocked_ip_ranges: str = Field(
        default="10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8,169.254.0.0/16,100.64.0.0/10",
        description="Comma-separated CIDR ranges MCP servers are blocked from reaching",
    )
    blocked_domains: str = Field(
        default="metadata.google.internal,169.254.169.254",
        description="Comma-separated domains/hostnames MCP servers are blocked from reaching",
    )

    @property
    def blocked_ip_ranges_list(self) -> list[str]:
        return [item.strip() for item in self.blocked_ip_ranges.split(",") if item.strip()]

    @property
    def blocked_domains_list(self) -> list[str]:
        return [item.strip() for item in self.blocked_domains.split(",") if item.strip()]

    # ------------------------------------------------------------------ #
    # MCP server process defaults                                          #
    # ------------------------------------------------------------------ #
    server_max_memory_mb: int = Field(
        default=512,
        description="Max RSS memory per MCP server process (MB)",
    )
    server_max_cpu_seconds: int = Field(
        default=0,
        description="Max CPU seconds per MCP server process (0 = unlimited)",
    )
    server_restart_max_retries: int = Field(
        default=5,
        description="Max automatic restart attempts before marking server as failed",
    )
    server_restart_backoff_seconds: float = Field(
        default=5.0,
        description="Initial backoff between restart attempts (doubles each time)",
    )
    server_start_concurrency: int = Field(
        default=4,
        ge=1,
        le=32,
        description="Maximum MCP server processes to start concurrently",
    )
    server_request_timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Timeout for one MCP JSON-RPC request forwarded to a child server",
    )
    server_health_check_interval: float = Field(
        default=30.0,
        description="Seconds between health checks for each running MCP server",
    )
    server_stdio_limit_mb: int = Field(
        default=16,
        ge=1,
        le=128,
        description="Maximum size of one stdout/stderr line from an MCP server process (MB)",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()
