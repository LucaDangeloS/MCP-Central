# MCP Central

MCP Central is a self-hosted hub for deploying, managing, and proxying MCP servers from one web UI and one unified MCP endpoint.

## Features

- FastAPI backend with JWT admin login and API key authentication.
- React/Vite admin UI for dashboard, servers, groups, API keys, logs, uploads, and endpoints.
- ZIP-based MCP server deployment using a `manifest.json` package format.
- Single-file Python MCP server creation from the browser.
- Per-server lifecycle controls: start, stop, and restart.
- Runtime environment variables per server, injected on next start or restart.
- SQLite persistence for configuration and logs.
- Docker Compose deployment with persistent `data/` and `servers/` volumes.
- Unified MCP proxy endpoints for routing requests to managed stdio MCP servers.

## Quick Start

1. Copy the example environment file:

```bash
cp .env.example .env
```

2. Edit `.env` and set at least these required values:

```env
SECRET_KEY=replace_with_a_long_random_value
ADMIN_PASSWORD=replace_with_a_strong_password
```

You can generate a secret key with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

3. Build and start the application:

```bash
docker compose build
docker compose up -d
```

4. Open the UI:

```text
http://localhost:8000
```

If you set `HUB_PORT` in `.env`, use that port instead.

5. Check health:

```bash
curl -f http://localhost:8000/api/health
```

## Docker Compose Options

Configuration is controlled through `.env`; there is only one `docker-compose.yml`.

| Variable | Default | Description |
| --- | --- | --- |
| `SECRET_KEY` | required | Secret used to sign admin JWT tokens. |
| `ADMIN_USERNAME` | `admin` | Admin login username. |
| `ADMIN_PASSWORD` | required | Admin login password. |
| `HUB_PORT` | `8000` | Host port mapped to the hub container's internal port `8000`. |
| `DEBUG` | `false` | Enables debug logging. |
| `TZ` | `Europe/Madrid` | Container timezone. |
| `PROXY_PORT` | `8888` | Internal tinyproxy port used for MCP server egress. |
| `BLOCKED_IP_RANGES` | private/link-local ranges | CIDR ranges documented for network filtering. |
| `BLOCKED_DOMAINS` | metadata domains | Domains blocked by tinyproxy filtering. |
| `SERVER_MAX_MEMORY_MB` | `512` | Memory limit per managed MCP server process. |
| `SERVER_RESTART_MAX_RETRIES` | `5` | Maximum automatic restart attempts. |
| `SERVER_RESTART_BACKOFF_SECONDS` | `5` | Initial restart backoff in seconds. |
| `SERVER_START_CONCURRENCY` | `4` | Maximum MCP server processes to start concurrently. |
| `SERVER_REQUEST_TIMEOUT_SECONDS` | `30` | Timeout for one JSON-RPC request forwarded to a managed server. |
| `SERVER_HEALTH_CHECK_INTERVAL` | `30` | Health check interval for managed servers. |
| `HUB_MEMORY_LIMIT` | `2g` | Docker resource memory limit for the hub service. |
| `HUB_CPU_LIMIT` | `2.0` | Docker resource CPU limit for the hub service. |

The Compose service is named `hub`, the container is named `mcp-central`, and the container always listens internally on port `8000`.

## Volumes

Docker Compose mounts two local runtime directories:

- `./data:/app/data` stores the SQLite database and logs.
- `./servers:/app/servers` stores deployed MCP server packages.

These directories are intentionally git-ignored except for `.gitkeep` placeholders.

## Development

Backend dependencies are managed with `uv`:

```bash
uv run pytest tests/ -v
uv run ruff check hub/
uv run mypy hub/
```

Frontend dependencies are managed with `pnpm` from `frontend/`:

```bash
pnpm install
pnpm test
pnpm build
```

Do not commit `.env`, database files, deployed server packages, virtual environments, `node_modules`, caches, or build artifacts.
