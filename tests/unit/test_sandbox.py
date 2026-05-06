"""Unit tests for sandbox config and environment building."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from hub.process.sandbox import (
    _WRAPPER_SCRIPT,
    SandboxConfig,
    build_dependency_install,
    build_sandbox_env,
)


class TestBuildSandboxEnv:
    def test_proxy_vars_set(self) -> None:
        env = build_sandbox_env(
            server_name="test",
            server_dir=Path("/srv/test"),
            extra_env={},
            proxy_port=8888,
        )
        assert env["HTTP_PROXY"] == "http://127.0.0.1:8888"
        assert env["HTTPS_PROXY"] == "http://127.0.0.1:8888"
        assert env["http_proxy"] == "http://127.0.0.1:8888"
        assert env["https_proxy"] == "http://127.0.0.1:8888"

    def test_pythonpath_set_to_server_dir(self) -> None:
        server_dir = Path("/srv/myserver")
        env = build_sandbox_env(
            server_name="myserver",
            server_dir=server_dir,
            extra_env={},
            proxy_port=8888,
        )
        # Use str(Path) so the test is OS-agnostic (backslashes on Windows)
        assert env["PYTHONPATH"] == str(server_dir)

    def test_server_name_injected(self) -> None:
        env = build_sandbox_env(
            server_name="my-cool-server",
            server_dir=Path("/srv/cool"),
            extra_env={},
            proxy_port=8888,
        )
        assert env["MCP_SERVER_NAME"] == "my-cool-server"

    def test_extra_env_merges_last(self) -> None:
        env = build_sandbox_env(
            server_name="s",
            server_dir=Path("/srv/s"),
            extra_env={"MY_TOKEN": "secret123", "PYTHONPATH": "/override"},
            proxy_port=8888,
        )
        assert env["MY_TOKEN"] == "secret123"
        # extra_env overrides base PYTHONPATH if set explicitly
        assert env["PYTHONPATH"] == "/override"

    def test_no_sensitive_hub_vars_leak(self) -> None:
        """Hub's own env vars must not bleed into the sandbox env."""
        import os
        os.environ["HUB_INTERNAL_SECRET"] = "should-not-leak"
        env = build_sandbox_env(
            server_name="s",
            server_dir=Path("/srv/s"),
            extra_env={},
            proxy_port=8888,
        )
        assert "HUB_INTERNAL_SECRET" not in env
        del os.environ["HUB_INTERNAL_SECRET"]

    def test_unbuffered_and_faulthandler_enabled(self) -> None:
        env = build_sandbox_env("s", Path("/srv/s"), {}, 8888)
        assert env.get("PYTHONUNBUFFERED") == "1"
        assert env.get("PYTHONFAULTHANDLER") == "1"


class TestSandboxConfig:
    def test_build_cmd_never_uses_shell(self) -> None:
        config = SandboxConfig(
            server_name="test",
            server_dir=Path("/srv/test"),
            entrypoint_module="main",
            venv_dir=Path("/srv/test/.venv"),
        )
        cmd = config.build_cmd()
        # Must be a list of strings, never a single shell string
        assert isinstance(cmd, list)
        assert all(isinstance(part, str) for part in cmd)
        # The executable must come from the venv, not system Python
        assert ".venv" in cmd[0]

    def test_wrapper_script_contains_excepthook(self) -> None:
        """The wrapper script must install sys.excepthook for traceback capture."""
        assert "sys.excepthook" in _WRAPPER_SCRIPT
        assert "traceback" in _WRAPPER_SCRIPT
        assert "warnings.simplefilter" in _WRAPPER_SCRIPT

    def test_wrapper_script_calls_entry_point(self) -> None:
        assert "{module}" in _WRAPPER_SCRIPT
        assert "import_module" in _WRAPPER_SCRIPT

    def test_python_executable_uses_venv(self) -> None:
        config = SandboxConfig(
            server_name="x",
            server_dir=Path("/srv/x"),
            entrypoint_module="mymod",
            venv_dir=Path("/srv/x/.venv"),
        )
        exe = config.python_executable
        assert ".venv" in exe
        if sys.platform == "win32":
            assert exe.endswith("python.exe")
        else:
            assert exe.endswith("python")


class TestDependencyInstall:
    def test_requirements_install_uses_venv_pip(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server"
        venv_dir = server_dir / ".venv"
        server_dir.mkdir()
        (server_dir / "requirements.txt").write_text("mcp\n", encoding="utf-8")

        install = build_dependency_install(server_dir, venv_dir)

        assert install is not None
        assert install.source == "requirements"
        assert install.command[-2:] == ["-r", str(server_dir / "requirements.txt")]
        assert ".venv" in install.command[0]
        assert install.env is None

    def test_pyproject_install_uses_uv_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        server_dir = tmp_path / "server"
        venv_dir = server_dir / ".venv"
        server_dir.mkdir()
        (server_dir / "pyproject.toml").write_text(
            "[project]\nname = \"server\"\nversion = \"1.0.0\"\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("hub.process.sandbox.shutil.which", lambda name: "/usr/bin/uv")

        install = build_dependency_install(server_dir, venv_dir)

        assert install is not None
        assert install.source == "pyproject"
        assert install.command[:3] == ["/usr/bin/uv", "sync", "--no-dev"]
        assert install.env is not None
        assert str(venv_dir) == install.env["UV_PROJECT_ENVIRONMENT"]

    def test_pyproject_install_requires_uv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        server_dir = tmp_path / "server"
        server_dir.mkdir()
        (server_dir / "pyproject.toml").write_text(
            "[project]\nname = \"server\"\nversion = \"1.0.0\"\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("hub.process.sandbox.shutil.which", lambda name: None)

        with pytest.raises(RuntimeError, match="uv is required"):
            build_dependency_install(server_dir, server_dir / ".venv")


class TestWrapperScript:
    def test_executes_main_function(self, tmp_path: Path) -> None:
        """The wrapper should call main() on the target module."""
        import subprocess

        # Write a simple MCP-like module
        server_dir = tmp_path / "testserver"
        server_dir.mkdir()
        (server_dir / "mymod.py").write_text(
            "def main():\n    import sys\n    print('hello from main', file=sys.stderr)\n"
        )

        wrapper = _WRAPPER_SCRIPT.format(module="mymod")
        result = subprocess.run(
            [sys.executable, "-u", "-c", wrapper],
            capture_output=True,
            text=True,
            cwd=str(server_dir),
            env={"PYTHONPATH": str(server_dir), "PATH": __import__("os").environ.get("PATH", "")},
        )
        assert "hello from main" in result.stderr

    def test_excepthook_captures_unhandled_exception(self, tmp_path: Path) -> None:
        """Unhandled exceptions must appear on stderr verbatim."""
        import subprocess

        server_dir = tmp_path / "crashmod"
        server_dir.mkdir()
        (server_dir / "crashmod.py").write_text(
            "def main():\n    raise ValueError('intentional crash for testing')\n"
        )

        wrapper = _WRAPPER_SCRIPT.format(module="crashmod")
        result = subprocess.run(
            [sys.executable, "-u", "-c", wrapper],
            capture_output=True,
            text=True,
            cwd=str(server_dir),
            env={"PYTHONPATH": str(server_dir), "PATH": __import__("os").environ.get("PATH", "")},
        )
        # Exit code must be non-zero
        assert result.returncode != 0
        # Full traceback must be on stderr
        assert "ValueError" in result.stderr
        assert "intentional crash for testing" in result.stderr
        assert "Traceback" in result.stderr
