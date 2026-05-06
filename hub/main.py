"""MCP Central hub — FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from hub.api import auth, groups, keys, logs, servers, stats, upload
from hub.config import get_settings
from hub.database import AsyncSessionLocal, init_db
from hub.logging_setup import configure_logging
from hub.mcp.proxy import create_mcp_discovery_router, create_mcp_router
from hub.process.manager import ProcessManager

logger = structlog.get_logger(__name__)

# Global process manager — initialised in lifespan, accessed via get_app_process_manager()
_process_manager: ProcessManager | None = None


def get_app_process_manager() -> ProcessManager:
    if _process_manager is None:
        raise RuntimeError("ProcessManager not initialised")
    return _process_manager


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — startup and shutdown hooks."""
    global _process_manager

    settings = get_settings()

    # Ensure required directories exist
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    settings.servers_dir.mkdir(parents=True, exist_ok=True)

    # Bootstrap DB tables (idempotent; Alembic handles migrations in prod)
    await init_db()

    # Initialise process manager and auto-start servers
    _process_manager = ProcessManager(AsyncSessionLocal)
    await _process_manager.start_all_auto_start()

    logger.info(
        "hub_started",
        port=settings.hub_port,
        debug=settings.debug,
        servers_dir=str(settings.servers_dir),
    )
    await logs.write_hub_log(
        "info",
        "hub_started",
        (
            f"hub_started port={settings.hub_port} debug={settings.debug} "
            f"servers_dir={settings.servers_dir}"
        ),
    )

    yield

    logger.info("hub_stopping")
    await logs.write_hub_log("info", "hub_stopping")
    if _process_manager:
        await _process_manager.stop_all()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(debug=settings.debug)

    app = FastAPI(
        title="MCP Central",
        description=(
            "A self-hosted MCP Server hub with management UI, sandboxing, "
            "and unified endpoint."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # ------------------------------------------------------------------ #
    # CORS — allow the React dev server during development                 #
    # ------------------------------------------------------------------ #
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------ #
    # Global exception handler — never swallow errors                      #
    # ------------------------------------------------------------------ #
    @app.exception_handler(Exception)
    async def _unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        import traceback

        tb = traceback.format_exc()
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=str(exc),
            traceback=tb,
        )
        await logs.write_hub_log(
            "error",
            f"unhandled_exception {request.method} {request.url.path}: {exc}",
            tb,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": 500,
                    "message": f"Internal server error: {exc}",
                    "details": {"traceback": tb},
                }
            },
        )

    # ------------------------------------------------------------------ #
    # Routers                                                              #
    # ------------------------------------------------------------------ #
    prefix = "/api/v1"
    app.include_router(stats.router, prefix=prefix)
    app.include_router(auth.router, prefix=prefix)
    app.include_router(servers.router, prefix=prefix)
    app.include_router(groups.router, prefix=prefix)
    app.include_router(keys.router, prefix=prefix)
    app.include_router(logs.router, prefix=prefix)
    app.include_router(upload.router, prefix=prefix)

    # MCP protocol endpoints (not versioned — follows MCP spec)
    app.include_router(create_mcp_discovery_router())
    app.include_router(create_mcp_router())

    # Health check at /api/health (unversioned, for Docker healthcheck)
    @app.get("/api/health", tags=["health"], include_in_schema=False)
    async def _health() -> dict[str, Any]:
        from datetime import UTC, datetime

        return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}

    # ------------------------------------------------------------------ #
    # Static frontend (served after all API routes)                        #
    # Will be mounted once the frontend is built                           #
    # ------------------------------------------------------------------ #
    import os

    _docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
    if os.path.isdir(_docs_dir):
        app.mount("/docs", StaticFiles(directory=_docs_dir), name="docs")

    _frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
    if os.path.isdir(_frontend_dist):
        from fastapi.responses import FileResponse

        # Serve static assets (JS, CSS, images, etc.)
        app.mount(
            "/assets",
            StaticFiles(directory=os.path.join(_frontend_dist, "assets")),
            name="assets",
        )

        # Serve any other static files at the root (like favicon) if they exist
        @app.get("/{file_path:path}", include_in_schema=False)
        async def _serve_spa(file_path: str):
            full_path = os.path.join(_frontend_dist, file_path)
            if os.path.isfile(full_path):
                return FileResponse(full_path)
            # Fallback to index.html for React Router
            return FileResponse(os.path.join(_frontend_dist, "index.html"))

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "hub.main:app",
        host="0.0.0.0",
        port=s.hub_port,
        reload=s.debug,
        log_config=None,  # structlog handles logging
    )
