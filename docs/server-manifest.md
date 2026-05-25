# MCP Server ZIP Package Format

This document specifies the format for deploying an MCP server to MCP Central via ZIP upload.
The same manifest format is used by normal package uploads and codebase-backed uploads.

---

## ZIP Structure

```
server.zip
├── manifest.json       ← REQUIRED: server metadata
├── requirements.txt    ← Python dependencies, or use pyproject.toml
├── pyproject.toml      ← Python uv project metadata, or use requirements.txt
├── package.json        ← JavaScript/TypeScript dependencies
├── main.py             ← Python entrypoint
├── index.js            ← JavaScript entrypoint
├── src/index.ts        ← TypeScript entrypoint
├── mypackage/          ← optional: additional Python packages
│   ├── __init__.py
│   └── tools.py
└── assets/             ← optional: static data files
```

### Rules

- All files must be at the **ZIP root** or in subdirectories within the ZIP.
- **No absolute paths** in the ZIP. Any entry whose resolved path escapes the extraction
  directory is rejected (Zip Slip prevention).
- The `entrypoint` file named in `manifest.json` **must exist** in the ZIP.
- Python packages must include either `requirements.txt` or `pyproject.toml` at the ZIP root.
- Packages with `pyproject.toml` are installed with `uv sync --no-dev`; checked-in `uv.lock`
  files are honored by uv when present.
- JavaScript and TypeScript packages must include `package.json` at the ZIP root. Checked-in
  `package-lock.json` files are installed with `npm ci`; otherwise the hub uses `npm install`.
- The language is detected automatically from `manifest.language`, the entrypoint extension
  (`.py`, `.js`, `.ts`), or the presence of `package.json`.

---

## manifest.json Schema

```json
{
  "name": "my-server",
  "version": "1.0.0",
  "description": "What this server does",
  "entrypoint": "main.py",
  "language": "python",
  "module": "main",
  "python_version": ">=3.10",
  "node_version": ">=18",
  "command": "npx",
  "args": ["--no-install", "my-mcp-server"],
  "env": {
    "MY_API_KEY": {
      "description": "API key for the upstream service",
      "required": true,
      "secret": true
    },
    "LOG_LEVEL": {
      "description": "Logging verbosity",
      "required": false,
      "secret": false
    }
  },
  "capabilities": ["tools", "resources"],
  "tags": ["search", "data"],
  "tools": [
    {
      "name": "search",
      "description": "Search marketplace listings by keywords. Supports optional 'pages' (default 5) and 'include_descriptions' (default true) parameters."
    },
    {
      "name": "link",
      "description": "Return Marketplace URLs for the given item ids"
    },
    {
      "name": "description",
      "description": "Return descriptions for the given item ids"
    }
  ]
}
```

### Field Reference

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | YES | Server identifier. Must match `/^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$/` |
| `version` | string | YES | Semantic version string (e.g. `"1.0.0"`) |
| `description` | string | NO | Human-readable description shown in the UI |
| `entrypoint` | string | YES | Path to the entrypoint file within the ZIP (e.g. `"main.py"`) |
| `language` | string | NO | Runtime language. One of `"python"`, `"javascript"`, or `"typescript"`. If omitted, the hub detects it automatically. |
| `module` | string | NO | Python module path to import (e.g. `"main"` or `"mypackage.server"`). Defaults to the entrypoint filename without `.py`. Ignored for JS/TS. |
| `python_version` | string | NO | PEP 440 version specifier for the Python interpreter (e.g. `">=3.10"`) |
| `node_version` | string | NO | Informational Node version constraint for JavaScript/TypeScript packages (e.g. `">=18"`) |
| `command` | string | NO | Optional explicit launcher for JS/TS packages. Must be one of `"node"`, `"npm"`, or `"npx"`. If omitted, JS runs `node <entrypoint>` and TS runs `npx --no-install tsx <entrypoint>`. |
| `args` | array | NO | Optional argv array used with `command`. Never executed through a shell. |
| `env` | object | NO | Environment variables the server needs. The hub seeds one editable field per key in the server's UI form on upload; operators fill values in there. Values are stored per-server on `McpServer.env_vars` and injected into the subprocess at start/restart. **Note:** values are currently persisted in cleartext in SQLite (see AGENTS.md §13 KI-1). |
| `capabilities` | array | NO | Informational: `"tools"`, `"resources"`, `"prompts"` |
| `tags` | array | NO | Freeform tags for UI filtering |
| `tools` | array | NO | Optional manual tool declarations. Each item must include `name` and may include `description` and `inputSchema`. These are stored with the server and used as fallback discovery metadata for clients such as opencode. |

---

## Deployment Modes

### Package upload

`POST /api/v1/upload` creates an immutable managed package under `servers/<name>/`.
Dependencies are installed the first time the server starts, when its venv is created.

### Codebase upload

`POST /api/v1/upload/codebase` creates or refreshes a development-oriented server under
`servers/<name>/`. It accepts the same ZIP structure and `manifest.json` schema, but has two
important differences:

- Re-uploading a ZIP with the same manifest `name` refreshes the stopped codebase server in place.
- The hub recreates the server venv on every start, so changes to `requirements.txt` or
  `pyproject.toml` are applied without manually deleting `.venv`.

This mode is intended for MCP servers under active development or servers that require frequent
maintenance. Stop the server before refreshing its codebase.

---

## Writing the MCP Server

### JavaScript / TypeScript packages

JavaScript packages run with `node <entrypoint>` by default. TypeScript packages run with
`npx --no-install tsx <entrypoint>`, so include `tsx` in `package.json` when uploading `.ts`
entrypoints. If a package needs a different npm/npx launcher, set `command` and `args` in
`manifest.json`; the hub still launches it as an argv list without `shell=True`.

Example JavaScript manifest:

```json
{
  "name": "my-node-server",
  "version": "1.0.0",
  "entrypoint": "index.js",
  "env": {
    "API_TOKEN": {
      "description": "Token for the upstream service",
      "required": true,
      "secret": true
    }
  }
}
```

For the Firefly III MCP server from `fabianonetto/mcp-server-firefly-iii`, use the ready-made
manifest in `docs/examples/firefly-iii-manifest.json`. That manifest targets GitHub's
"Download ZIP" layout, where the repository contents are nested under
`mcp-server-firefly-iii-main/`; if you build a ZIP from inside the cloned repository instead,
change `entrypoint` back to `index.js`.

### Python packages

Your server must expose a `main()` or `run()` function in the entrypoint module. The hub
launches it with:

```python
import importlib
mod = importlib.import_module("your.module")
mod.main()
```

### Transport

Servers must use **stdio** transport: read JSON-RPC requests from `stdin`, write responses to
`stdout`. All logs and errors must go to `stderr`.

### Example using FastMCP

```python
# main.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-server")

@mcp.tool()
def greet(name: str) -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"

def main():
    mcp.run()  # runs over stdio by default
```

### Error handling

- All unhandled exceptions are automatically captured by the hub's wrapper and written to
  `stderr` as a full traceback.
- Use `sys.stderr` for debug/informational output — `stdout` is reserved for MCP protocol.
- The hub persists stderr to the database and surfaces it in the Logs UI.

---

## Environment Variables

The hub injects the following env vars into every server process:

| Variable | Description |
|---|---|
| `MCP_SERVER_NAME` | The server's registered name |
| `PYTHONPATH` | Set to the server's directory |
| `HTTP_PROXY` / `HTTPS_PROXY` | tinyproxy address (for network filtering) |
| `PYTHONUNBUFFERED` | Always `1` (ensures stdout/stderr flushing) |
| `PYTHONFAULTHANDLER` | Always `1` (enables crash tracebacks) |
| `NODE_NO_WARNINGS` | Set to `1` for Node-backed MCP servers |

Variables declared in the `manifest.json` `env` section are configured **per server in the
MCP Central web UI** after upload. The hub stores them on `McpServer.env_vars` (a JSON column
in SQLite) and injects them into the subprocess environment on every start/restart. Editing
a value while the server is running requires a restart for the change to take effect.

> **Security note (AGENTS.md §13 KI-1, open issue):** these values — including those declared
> `"secret": true` — are persisted in cleartext in `data/mcp_central.db`. Treat them as
> plaintext-at-rest until that issue is resolved. For very high-value secrets, prefer storing
> them on the host filesystem and referencing them from a small wrapper, rather than pasting
> them into the UI form.

---

## Security Notes

- Servers run in **isolated Python venvs** — packages installed for one server cannot
  affect another.
- All outbound HTTP/HTTPS traffic is routed through `tinyproxy`. Blocked domains and IP
  ranges are configured via `.env` / `docker-compose.yml`.
- Servers are spawned without `shell=True`. No shell injection is possible via server names
  or arguments.
- No `eval()` or `exec()` is used in the hub codebase.
