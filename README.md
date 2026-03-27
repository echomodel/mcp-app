# mcp-app

Config-driven framework for building and running MCP servers as HTTP services. Define tools as pure Python functions, configure via YAML, run with two commands.

## Install

```bash
pip install git+https://github.com/krisrowe/mcp-app.git
```

## Quick Start

Create `mcp-app.yaml` in your repo root:

```yaml
name: my-app
store: filesystem
middleware:
  - user-identity
tools: my_app.mcp.tools
```

Create your tools module — pure async functions, no framework imports:

```python
# my_app/mcp/tools.py
from my_app.sdk.core import MySDK

sdk = MySDK()

async def do_thing(param: str) -> dict:
    """Tool description shown to agents."""
    return sdk.do_thing(param)
```

Run as HTTP service:

```bash
mcp-app serve
```

## mcp-app.yaml Reference

```yaml
name: my-app                    # Required — MCP server name, data store path
store: filesystem               # Required — data store (alias or module path)
middleware:                      # Optional — omit for no auth
  - user-identity               #   array of middleware (alias or module path)
tools: my_app.mcp.tools         # Required — module path to discover tools from
```

### Store

| Value | Description |
|-------|-------------|
| `filesystem` | Built-in. Per-user directories with `~` email encoding. Reads `APP_USERS_PATH` env var, falls back to `~/.local/share/{name}/users/` |
| `my.module.MyStore` | Custom. Any class satisfying the `UserDataStore` protocol (`load`, `save`, `list_users`, `delete`) |

No dot = built-in alias. Dot = Python module path, dynamically imported.

### Middleware

| Value | Description |
|-------|-------------|
| `user-identity` | Validates JWT, extracts `sub` claim, sets `current_user_id` ContextVar. For data-owning apps. |
| `credential-proxy` | Validates JWT, swaps for stored backend credential, rewrites Authorization header. For API-proxy apps. (Future) |
| `my.module.MyMiddleware` | Custom. ASGI middleware class with signature `__init__(self, app, verifier, store=None)` |

Middleware is an array — order matters (first = outermost). Omit entirely for no auth.

### Tool Discovery

The `tools` module is imported and all public async functions (not starting with `_`) are registered as MCP tools. Function names become tool names. Docstrings become descriptions. Type hints become schemas.

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `SIGNING_KEY` | For HTTP | `dev-key` | JWT signing key |
| `JWT_AUD` | No | None (skip) | Token audience validation |
| `APP_USERS_PATH` | No | `~/.local/share/{name}/users/` | Per-user data directory |
| `TOKEN_DURATION_SECONDS` | No | 315360000 (~10yr) | Default token lifetime |

## User Identity

In HTTP mode, the middleware sets `current_user_id` (a ContextVar). The SDK reads it:

```python
from mcp_app.context import current_user_id

user = current_user_id.get()  # "default" (stdio) or "alice@example.com" (HTTP)
```

Without middleware (or when running a solution locally via its own CLI), `current_user_id` defaults to `"default"`.

## Admin Endpoints

When middleware is configured, REST admin endpoints are mounted at `/admin`:

- `POST /admin/users` — register user, returns JWT
- `GET /admin/users` — list users
- `DELETE /admin/users/{email}` — revoke user
- `POST /admin/tokens` — issue new token for existing user

Gated by admin-scoped JWT (`scope: "admin"`, same signing key).

## Deployment

### With gapp

[gapp](https://github.com/krisrowe/gapp) detects `mcp-app.yaml` automatically. No `service.entrypoint` needed in `gapp.yaml`:

```yaml
# gapp.yaml — just env vars and public access
public: true
env:
  - name: SIGNING_KEY
    secret:
      generate: true
  - name: APP_USERS_PATH
    value: "{{SOLUTION_DATA_PATH}}/users"
```

### Without gapp

Any platform that runs Python apps:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install -e .
EXPOSE 8080
CMD ["mcp-app", "serve"]
```

Set environment variables for `SIGNING_KEY` and `APP_USERS_PATH`.

### MCP Client Configuration

**Claude.ai:**
```
https://your-service.run.app/?token=YOUR_TOKEN
```

**Claude Code / Gemini CLI (remote):**
```json
{
  "mcpServers": {
    "my-app": {
      "url": "https://your-service.run.app/",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN"
      }
    }
  }
}
```

## Architecture

mcp-app wraps [FastMCP](https://github.com/modelcontextprotocol/python-sdk) (the official MCP Python SDK) and [Starlette](https://www.starlette.io/) (ASGI framework). Solutions never import these directly — mcp-app handles all wiring.

```
mcp-app.yaml
    → bootstrap reads config
    → imports tools module, discovers async functions
    → registers each as FastMCP tool
    → creates data store from config
    → stacks middleware from config
    → composes admin endpoints + middleware + FastMCP into one ASGI app
    → serves via uvicorn (mcp-app serve)
```
