"""Tool/resource namespacing to prevent conflicts between MCP servers.

Convention: ``<server_name>__<original_tool_name>``
Two underscores are used as the separator because server names allow hyphens
and underscores, but double-underscores are very unlikely in real tool names.
"""

from __future__ import annotations

_SEP = "__"


def namespace_tool_name(server_name: str, tool_name: str) -> str:
    """Return ``server__tool`` namespaced tool name."""
    return f"{server_name}{_SEP}{tool_name}"


def extract_server_name(namespaced_name: str) -> tuple[str, str] | None:
    """Split a namespaced tool name into (server_name, original_tool_name).

    Returns None if the name is not namespaced.
    """
    if _SEP not in namespaced_name:
        return None
    server_name, _, tool_name = namespaced_name.partition(_SEP)
    return server_name, tool_name


def is_namespaced(name: str) -> bool:
    return _SEP in name
