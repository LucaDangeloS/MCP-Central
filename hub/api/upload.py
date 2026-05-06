"""ZIP upload and MCP server deployment endpoint."""

from __future__ import annotations

import asyncio
import io
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.api.responses import ok
from hub.auth.admin import get_current_admin
from hub.config import get_settings
from hub.database import get_db
from hub.models.server import McpServer, ServerRead, ServerStatus

logger = structlog.get_logger(__name__)
_DEPLOY_TASKS: set[asyncio.Task[None]] = set()

router = APIRouter(prefix="/upload", tags=["upload"])

AdminDep = Annotated[str, Depends(get_current_admin)]
DbDep = Annotated[AsyncSession, Depends(get_db)]

# Server name validation pattern (same as in the model)
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

REQUIRED_MANIFEST_FIELDS = {"name", "version", "entrypoint"}
ALLOWED_MANIFEST_FIELDS = {
    "name", "version", "description", "entrypoint", "module",
    "python_version", "env", "capabilities", "tags",
}


class SingleFileServerCreate(BaseModel):
    name: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$")
    description: str = Field(default="", max_length=500)
    code: str = Field(..., min_length=1, max_length=200_000)
    requirements: str = Field(default="# no requirements\n", max_length=50_000)
    env_vars: dict[str, str] = Field(default_factory=dict)
    auto_start: bool = True

    @field_validator("env_vars")
    @classmethod
    def validate_env_vars(cls, value: dict[str, str]) -> dict[str, str]:
        invalid = [key for key in value if not _ENV_NAME_RE.match(key)]
        if invalid:
            raise ValueError(f"Invalid environment variable names: {invalid}")
        return value


def _validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return a list of validation error strings (empty = valid)."""
    errors: list[str] = []

    missing = REQUIRED_MANIFEST_FIELDS - manifest.keys()
    if missing:
        errors.append(f"manifest.json is missing required fields: {sorted(missing)}")

    name = manifest.get("name", "")
    if not _NAME_RE.match(str(name)):
        errors.append(
            f"Server name '{name}' is invalid. "
            f"Must match /^[a-z0-9][a-z0-9_-]{{1,62}}[a-z0-9]$/"
        )

    return errors


def _check_zip_slip(zip_ref: zipfile.ZipFile, target_dir: Path) -> list[str]:
    """Return a list of dangerous paths (Zip Slip attack prevention).

    Any entry whose resolved path escapes target_dir is flagged.
    """
    dangerous: list[str] = []
    for member in zip_ref.namelist():
        member_path = (target_dir / member).resolve()
        if not str(member_path).startswith(str(target_dir.resolve())):
            dangerous.append(member)
    return dangerous


async def _target_dir_exists(target_dir: Path) -> bool:
    return await asyncio.to_thread(target_dir.exists)


async def _write_single_file_package(
    target_dir: Path,
    code: str,
    requirements: str,
) -> None:
    def _write() -> None:
        target_dir.mkdir(parents=True, exist_ok=False)
        (target_dir / "main.py").write_text(code, encoding="utf-8")
        (target_dir / "requirements.txt").write_text(requirements, encoding="utf-8")

    try:
        await asyncio.to_thread(_write)
    except Exception:
        await asyncio.to_thread(shutil.rmtree, target_dir, True)
        raise


async def _start_deployed_server(server_name: str) -> None:
    from hub.process.health import get_process_manager

    async def _deploy() -> None:
        try:
            pm = get_process_manager()
            await pm.start_server(server_name)
        except RuntimeError:
            # ProcessManager not initialised (e.g., in tests) — skip
            pass
        except Exception as exc:
            import traceback
            logger.error(
                "auto_start_after_deploy_failed",
                server_name=server_name,
                error=str(exc),
                traceback=traceback.format_exc(),
            )

    task = asyncio.create_task(_deploy())
    _DEPLOY_TASKS.add(task)
    task.add_done_callback(_DEPLOY_TASKS.discard)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a ZIP package to deploy an MCP server",
)
async def upload_server(
    file: Annotated[UploadFile, File(description="ZIP file containing the MCP server package")],
    _admin: AdminDep,
    db: DbDep,
) -> dict[str, Any]:
    """Upload a `.zip` MCP server package.

    The ZIP must contain:
    - `manifest.json` at the root
    - `requirements.txt` or `pyproject.toml` at the root
    - The entrypoint file named in `manifest.entrypoint`

    See `docs/server-manifest.md` for the full format specification.
    """
    settings = get_settings()

    # ------------------------------------------------------------------ #
    # Step 1 — read and validate the zip                                   #
    # ------------------------------------------------------------------ #
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        zip_bytes = io.BytesIO(content)
        zip_ref = zipfile.ZipFile(zip_bytes, "r")
    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=400, detail=f"Uploaded file is not a valid ZIP archive: {exc}"
        ) from exc

    names_in_zip = zip_ref.namelist()

    # ------------------------------------------------------------------ #
    # Step 2 — read and validate manifest.json                             #
    # ------------------------------------------------------------------ #
    if "manifest.json" not in names_in_zip:
        raise HTTPException(
            status_code=422,
            detail="manifest.json is missing from the ZIP root. See docs/server-manifest.md.",
        )

    try:
        manifest_bytes = zip_ref.read("manifest.json")
        manifest: dict[str, Any] = json.loads(manifest_bytes.decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=422, detail=f"manifest.json is not valid JSON: {exc}"
        ) from exc

    validation_errors = _validate_manifest(manifest)
    if validation_errors:
        raise HTTPException(status_code=422, detail={"errors": validation_errors})

    server_name: str = manifest["name"]
    entrypoint_file: str = manifest["entrypoint"]
    module_name: str = manifest.get("module", entrypoint_file.removesuffix(".py").replace("/", "."))
    description: str = manifest.get("description", "")
    env_spec: dict[str, Any] = manifest.get("env", {})

    # ------------------------------------------------------------------ #
    # Step 3 — check entrypoint and dependency metadata exist in ZIP        #
    # ------------------------------------------------------------------ #
    if entrypoint_file not in names_in_zip:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Entrypoint '{entrypoint_file}' listed in manifest.json was not found in the ZIP."
            ),
        )

    if "requirements.txt" not in names_in_zip and "pyproject.toml" not in names_in_zip:
        raise HTTPException(
            status_code=422,
            detail="requirements.txt or pyproject.toml is missing from the ZIP root.",
        )

    # ------------------------------------------------------------------ #
    # Step 4 — Zip Slip prevention                                         #
    # ------------------------------------------------------------------ #
    target_dir = settings.servers_dir / server_name
    dangerous = _check_zip_slip(zip_ref, target_dir)
    if dangerous:
        raise HTTPException(
            status_code=422,
            detail={
                "message": (
                    "ZIP contains path traversal entries (Zip Slip attack detected). "
                    "Upload rejected."
                ),
                "dangerous_paths": dangerous,
            },
        )

    # ------------------------------------------------------------------ #
    # Step 5 — check for duplicate server name                             #
    # ------------------------------------------------------------------ #
    existing = await db.execute(
        select(McpServer).where(McpServer.name == server_name)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A server named '{server_name}' already exists. "
                "Delete it first or use a different name."
            ),
        )

    # ------------------------------------------------------------------ #
    # Step 6 — extract to servers_dir/<name>/                              #
    # ------------------------------------------------------------------ #
    target_dir.mkdir(parents=True, exist_ok=True)
    zip_ref.extractall(target_dir)
    zip_ref.close()
    logger.info("server_zip_extracted", server_name=server_name, target=str(target_dir))

    # ------------------------------------------------------------------ #
    # Step 7 — register in DB                                              #
    # ------------------------------------------------------------------ #
    # Convert env spec to plain string dict (values come from .env at runtime)
    env_vars: dict[str, str] = dict.fromkeys(env_spec, "")

    server = McpServer(
        name=server_name,
        description=description,
        path=server_name,
        entrypoint_module=module_name,
        env_vars=json.dumps(env_vars),
        python_version_constraint=manifest.get("python_version", ""),
        auto_start=True,
        restart_on_error=True,
        status=ServerStatus.stopped.value,
    )
    db.add(server)
    await db.flush()
    await db.refresh(server)

    logger.info("server_registered_via_upload", server_name=server_name, id=server.id)

    # ------------------------------------------------------------------ #
    # Step 8 — trigger venv creation + auto-start asynchronously           #
    # ------------------------------------------------------------------ #
    await _start_deployed_server(server_name)

    return ok(
        {
            "server": ServerRead.model_validate(server),
            "manifest": manifest,
            "message": f"Server '{server_name}' deployed successfully. Auto-start initiated.",
        }
    )


@router.post(
    "/single-file",
    status_code=status.HTTP_201_CREATED,
    summary="Create a single-file MCP server from editor contents",
)
async def create_single_file_server(
    payload: SingleFileServerCreate,
    _admin: AdminDep,
    db: DbDep,
) -> dict[str, Any]:
    settings = get_settings()
    server_name = payload.name
    target_dir = settings.servers_dir / server_name

    existing = await db.execute(
        select(McpServer).where(McpServer.name == server_name)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A server named '{server_name}' already exists. "
                "Delete it first or use a different name."
            ),
        )

    if await _target_dir_exists(target_dir):
        raise HTTPException(
            status_code=409,
            detail=f"A server directory named '{server_name}' already exists on disk.",
        )

    try:
        await _write_single_file_package(target_dir, payload.code, payload.requirements)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to write single-file server package '{server_name}': {exc}",
        ) from exc

    manifest = {
        "name": server_name,
        "version": "1.0.0",
        "description": payload.description,
        "entrypoint": "main.py",
        "module": "main",
        "env": {key: {} for key in payload.env_vars},
    }

    server = McpServer(
        name=server_name,
        description=payload.description,
        path=server_name,
        entrypoint_module="main",
        env_vars=json.dumps(payload.env_vars),
        python_version_constraint="",
        auto_start=payload.auto_start,
        restart_on_error=True,
        status=ServerStatus.stopped.value,
    )
    db.add(server)
    await db.flush()
    await db.refresh(server)

    logger.info("single_file_server_created", server_name=server_name, id=server.id)

    if payload.auto_start:
        await _start_deployed_server(server_name)

    message = (
        f"Server '{server_name}' created successfully. Auto-start initiated."
        if payload.auto_start
        else f"Server '{server_name}' created successfully. Start it from the Servers page."
    )
    return ok(
        {"server": ServerRead.model_validate(server), "manifest": manifest, "message": message}
    )
