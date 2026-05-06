"""Sandbox setup — venv creation, resource limits, env var isolation."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, NamedTuple

import structlog

logger = structlog.get_logger(__name__)

DependencySource = Literal["requirements", "pyproject"]


class DependencyInstall(NamedTuple):
    source: DependencySource
    command: list[str]
    env: dict[str, str] | None


# Wrapper script injected as -c argument to bootstrap each MCP server.
# It installs sys.excepthook BEFORE importing the server so any uncaught
# exception always lands on stderr verbatim (never swallowed).
_WRAPPER_SCRIPT = """\
import sys, warnings, traceback as _tb

warnings.simplefilter("always")

_orig_excepthook = sys.excepthook
def _mcp_excepthook(exc_type, exc_value, exc_tb):
    print(
        "\\n[MCP Central] Unhandled exception in MCP server process:",
        file=sys.stderr,
        flush=True,
    )
    _tb.print_exception(exc_type, exc_value, exc_tb, file=sys.stderr)
    sys.stderr.flush()
    _orig_excepthook(exc_type, exc_value, exc_tb)
sys.excepthook = _mcp_excepthook

import importlib as _imp
_mod = _imp.import_module("{module}")
if hasattr(_mod, "main"):
    _mod.main()
elif hasattr(_mod, "run"):
    _mod.run()
else:
    raise RuntimeError(
        f"MCP server module '{{_mod.__name__}}' has no callable 'main' or 'run' entry point."
    )
"""


@dataclass
class SandboxConfig:
    """All parameters needed to launch one sandboxed MCP server subprocess."""

    server_name: str
    server_dir: Path
    entrypoint_module: str
    venv_dir: Path
    env_vars: dict[str, str] = field(default_factory=dict)
    proxy_port: int = 8888
    max_memory_mb: int = 512

    @property
    def python_executable(self) -> str:
        if sys.platform == "win32":
            return str(self.venv_dir / "Scripts" / "python.exe")
        return str(self.venv_dir / "bin" / "python")

    def build_cmd(self) -> list[str]:
        """Return the argv list for subprocess.  Never uses shell=True."""
        wrapper = _WRAPPER_SCRIPT.format(module=self.entrypoint_module)
        return [self.python_executable, "-u", "-c", wrapper]

    def build_env(self) -> dict[str, str]:
        return build_sandbox_env(
            server_name=self.server_name,
            server_dir=self.server_dir,
            extra_env=self.env_vars,
            proxy_port=self.proxy_port,
        )


def build_sandbox_env(
    server_name: str,
    server_dir: Path,
    extra_env: dict[str, str],
    proxy_port: int,
) -> dict[str, str]:
    """Build the environment dict for an MCP server subprocess.

    - Forces all HTTP/HTTPS traffic through tinyproxy.
    - Sets PYTHONPATH to the server directory.
    - Inherits only the safe subset of the parent env (PATH, LANG, TZ).
    - Merges server-specific env vars last (highest priority).
    """
    proxy_url = f"http://127.0.0.1:{proxy_port}"

    safe_inherit = {
        k: v
        for k, v in os.environ.items()
        if k in {"PATH", "LANG", "LC_ALL", "TZ", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR"}
    }

    env: dict[str, str] = {
        **safe_inherit,
        # Force all outbound HTTP through tinyproxy
        "HTTP_PROXY": proxy_url,
        "HTTPS_PROXY": proxy_url,
        "http_proxy": proxy_url,
        "https_proxy": proxy_url,
        # Python configuration
        "PYTHONPATH": str(server_dir),
        "PYTHONUNBUFFERED": "1",
        "PYTHONFAULTHANDLER": "1",  # dump traceback on SIGSEGV / SIGBUS
        # Identity for logging
        "MCP_SERVER_NAME": server_name,
        # Merge server-specific vars (may override proxy etc. intentionally)
        **extra_env,
    }
    return env


async def create_server_venv(server_dir: Path, venv_dir: Path) -> None:
    """Create a Python venv inside *venv_dir* and install server dependencies.

    Supports legacy requirements.txt packages and uv/pyproject.toml projects.
    Raises RuntimeError with full installer output on failure — never truncates.
    """
    log = logger.bind(server_dir=str(server_dir), venv_dir=str(venv_dir))

    # Step 1 — create the venv
    log.info("creating_venv")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "venv", str(venv_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"venv creation failed for server at '{server_dir}'.\n"
            f"stdout:\n{stdout.decode()}\n"
            f"stderr:\n{stderr.decode()}"
        )

    # Step 2 — install dependencies
    install = build_dependency_install(server_dir, venv_dir)
    if install is not None:
        log.info("installing_server_dependencies", source=install.source)
        proc = await asyncio.create_subprocess_exec(
            *install.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(server_dir),
            env=install.env,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"Dependency install failed for server at '{server_dir}'.\n"
                f"Source: {install.source}\n"
                f"Command: {' '.join(install.command)}\n"
                f"Return code: {proc.returncode}\n"
                f"stdout:\n{stdout.decode()}\n"
                f"stderr:\n{stderr.decode()}"
            )
        log.info(
            "server_dependencies_installed",
            source=install.source,
            output_lines=stdout.decode().count("\n"),
        )
    else:
        log.info("no_dependency_metadata_skipping_install")


def build_dependency_install(server_dir: Path, venv_dir: Path) -> DependencyInstall | None:
    """Return the installer command for a server package, if dependency metadata exists."""
    requirements = server_dir / "requirements.txt"
    if requirements.exists():
        pip = _venv_executable(venv_dir, "pip")
        return DependencyInstall(
            source="requirements",
            command=[pip, "install", "-r", str(requirements)],
            env=None,
        )

    pyproject = server_dir / "pyproject.toml"
    if pyproject.exists():
        uv = shutil.which("uv")
        if uv is None:
            raise RuntimeError(
                "uv is required to install pyproject.toml-based MCP server packages, "
                "but no uv executable was found on PATH."
            )

        env = os.environ.copy()
        env["UV_PROJECT_ENVIRONMENT"] = str(venv_dir)
        return DependencyInstall(
            source="pyproject",
            command=[uv, "sync", "--no-dev", "--python", _venv_executable(venv_dir, "python")],
            env=env,
        )

    return None


def _venv_executable(venv_dir: Path, name: Literal["pip", "python"]) -> str:
    if sys.platform == "win32":
        suffix = ".exe"
        scripts_dir = "Scripts"
    else:
        suffix = ""
        scripts_dir = "bin"
    return str(venv_dir / scripts_dir / f"{name}{suffix}")
