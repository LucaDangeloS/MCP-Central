"""Health check utilities for MCP server processes."""

from __future__ import annotations

from hub.process.manager import ProcessManager


def get_process_manager() -> ProcessManager:
    """FastAPI dependency to access the global ProcessManager instance."""
    from hub.main import get_app_process_manager
    return get_app_process_manager()
