# mcp-app

Config-driven framework for building and running MCP servers as HTTP services. Define tools as pure Python functions, configure via YAML, run with two commands.

## Install

```bash
pip install git+https://github.com/echomodel/mcp-app.git
```

## Quick Start

Create `mcp-app.yaml` in your repo root:

```yaml
name: my-app
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

Run locally or as HTTP service:

```bash
mcp-app stdio   # local, single user, stdin/stdout
mcp-app serve   # HTTP, multi-user, production
```

## mcp-app.yaml Reference

```yaml
name: my-app                    # Required — MCP server name, data store path
tools: my_app.mcp.tools         # Required — module path to discover tools from
store: filesystem               # Optional — defaults to filesystem
stdio:                          # Required for stdio mode
  user: "local"                 #   identity for the local session
```

Only `name` and `tools` are required. Identity middleware runs automatically in HTTP mode. Store defaults to filesystem.

### Store

| Value | Description |
|-------|-------------|
| `filesystem` | Default. Per-user directories with `~` email encoding. Reads `APP_USERS_PATH` env var, falls back to `~/.local/share/{name}/users/` |
| `my.module.MyStore` | Custom. Any class satisfying the `UserDataStore` protocol (`load`, `save`, `list_users`, `delete`) |

No dot = built-in alias. Dot = Python module path, dynamically imported.

### Middleware

Identity middleware (`user-identity`) runs automatically in HTTP mode. It validates JWTs, loads the full user record from the store, and sets the `current_user` ContextVar. You don't need to configure it.

To add custom middleware or disable auth entirely:

```yaml
# Custom middleware (user-identity must be included explicitly)
middleware:
  - my_app.auth.RateLimiter
  - user-identity

# No auth (explicitly empty)
middleware: []
```

Custom middleware must match the signature `__init__(self, app, verifier, store=None)`.

### Two App Patterns

Both data-owning and API-proxy apps use the same framework. The difference is what the SDK reads from the user context.

**Data-owning app** (owns user data — food logs, notes, etc.):

```python
# my_data_app/sdk/core.py
from mcp_app.context import current_user
from mcp_app import get_store

class MySDK:
    def save_entry(self, data):
        user = current_user.get()
        store = get_store()
        store.save(user.email, "entries/today", data)
```

The SDK reads `current_user.get().email` to scope data. The store holds per-user app data.

**API-proxy app** (wraps an external API — financial data, Google Workspace, etc.):

```python
# my_proxy/sdk/core.py
from mcp_app.context import current_user
import httpx

class MySDK:
    def list_items(self):
        user = current_user.get()
        token = user.profile["token"]
        resp = httpx.get("https://api.example.com/items",
                         headers={"Authorization": f"Bearer {token}"})
        return resp.json()
```

The SDK reads `current_user.get().profile` for the backend credential. The profile was saved at registration time and loaded in one read with the auth record.

**What's identical:** store setup, admin endpoints, tool discovery, yaml structure, deployment. The middleware is the same. The SDK decides what to read from the user context.

### Tool Discovery

The `tools` module is imported and all public async functions (not starting with `_`) are registered as MCP tools. Function names become tool names. Docstrings become descriptions. Type hints become schemas.

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `SIGNING_KEY` | For HTTP | none — required | JWT signing key. Must be set for HTTP mode. |
| `JWT_AUD` | No | None (skip) | Token audience validation |
| `APP_USERS_PATH` | No | `~/.local/share/{name}/users/` | Per-user data directory |
| `TOKEN_DURATION_SECONDS` | No | 315360000 (~10yr) | Default token lifetime |

## User Identity and Profile

Every mcp-app solution has a `current_user` ContextVar set before tools execute. No default — tools that run without an established identity return an error.

| Transport | How it's set |
|-----------|-------------|
| HTTP (`mcp-app serve`) | Identity middleware validates JWT, loads full user record from store |
| stdio (`mcp-app stdio`) | CLI loads user record from store using `stdio.user` from yaml |

The SDK reads it:

```python
from mcp_app.context import current_user

user = current_user.get()
user.email       # "alice@example.com" (HTTP) or "local" (stdio)
user.profile     # dict or typed Pydantic model — whatever was saved at registration
```

### Profile

The user record includes an optional `profile` field — app-specific data saved at registration time (backend credentials, preferences, config). mcp-app stores it and loads it but does not interpret it.

For typed profile access, the app registers a Pydantic model:

```python
# my_app/__init__.py
from pydantic import BaseModel
from mcp_app.context import register_profile

class Profile(BaseModel):
    token: str

register_profile(Profile)
```

Now `user.profile.token` is typed and validated. If no model is registered, `user.profile` is a raw dict.

### User registration with profile

```bash
# Data-owning app — no profile needed
mcp-app users add alice@example.com

# API-proxy app — profile contains backend credential
mcp-app users add alice@example.com --profile '{"token": "api-key-xxx"}'
```

### stdio configuration

```yaml
# mcp-app.yaml
stdio:
  user: "local"
```

`mcp-app stdio` loads the user record for `"local"` from the store and sets `current_user`. Refuses to start without `stdio.user` configured.

## Admin Endpoints

REST admin endpoints are mounted at `/admin` in HTTP mode:

- `POST /admin/users` — register user (with optional profile), returns JWT
- `GET /admin/users` — list users
- `DELETE /admin/users/{email}` — revoke user
- `POST /admin/tokens` — issue new token for existing user

Gated by admin-scoped JWT (`scope: "admin"`, same signing key).

## Local Testing

Validate the full stack in-memory — no server, no Docker, no cloud:

```python
from mcp_app.bootstrap import build_app
import httpx

app, mcp, store, config = build_app()
transport = httpx.ASGITransport(app=app)
client = httpx.AsyncClient(transport=transport, base_url="http://test")
```

`build_app()` returns the same ASGI app that `mcp-app serve` gives to
uvicorn. httpx runs it in-process. If it works here, it works in Docker.
httpx is already a dependency of mcp-app.

See CONTRIBUTING.md for full test examples.

## Deployment

mcp-app is a standard Python app. Deploy it however you deploy Python.

### Bare metal (no container)

```bash
pip install -e .
SIGNING_KEY=your-key mcp-app serve
```

For development or simple VPS deployments. Runs uvicorn on port 8080.

### Docker (any container platform)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install -e .
EXPOSE 8080
CMD ["mcp-app", "serve"]
```

```bash
# Build and run locally
docker build -t my-app .
docker run -p 8080:8080 -e SIGNING_KEY=your-key my-app
```

This Dockerfile works on any platform that runs containers.

### Google Cloud Run (source deploy — no Docker needed)

```bash
gcloud run deploy my-app \
  --source . \
  --allow-unauthenticated \
  --set-env-vars SIGNING_KEY=your-key
```

Builds in the cloud. No local Docker install required. If a Dockerfile
exists it uses it; otherwise Google Cloud Buildpacks detect the Python app.

### gapp (fastest path to Cloud Run)

[gapp](https://github.com/echomodel/gapp) auto-detects `mcp-app.yaml`
and handles Dockerfile generation, secrets, and data volumes:

```yaml
# gapp.yaml
public: true
env:
  - name: SIGNING_KEY
    secret:
      generate: true
  - name: APP_USERS_PATH
    value: "{{SOLUTION_DATA_PATH}}/users"
```

```bash
gapp deploy
```

No Dockerfile to write. gapp generates one with `CMD ["mcp-app", "serve"]`.

gapp has three ways to know how to run your app (in priority order):
1. `service.entrypoint` in gapp.yaml — ASGI module:app path, wrapped with uvicorn
2. `service.cmd` in gapp.yaml — raw command, runs as written
3. `mcp-app.yaml` detected in repo — generates `CMD ["mcp-app", "serve"]`

### FastMCP without mcp-app

If using FastMCP directly (no mcp-app.yaml), the same deployment options
work. The Dockerfile CMD and gapp config differ:

```dockerfile
# Dockerfile for FastMCP
CMD ["uvicorn", "my_app.mcp.server:app", "--host", "0.0.0.0", "--port", "8080"]
```

```yaml
# gapp.yaml for FastMCP
service:
  entrypoint: my_app.mcp.server:app
```

```bash
# Bare metal for FastMCP
uvicorn my_app.mcp.server:app --host 0.0.0.0 --port 8080
```

### Deployment matrix

| | Bare metal | Docker | gcloud --source | gapp |
|---|---|---|---|---|
| **mcp-app** | `mcp-app serve` | `CMD ["mcp-app", "serve"]` | auto-detected | auto-detected |
| **FastMCP** | `uvicorn module:app` | `CMD ["uvicorn", "..."]` | needs Dockerfile | `service.entrypoint` |

mcp-app doesn't know about gapp. gapp doesn't know about mcp-app's internals.
Deploy anywhere — the framework serves an ASGI app on a port.

### MCP Client Configuration

#### CLI-based registration

**Claude Code (stdio — local):**
```bash
claude mcp add my-app -- mcp-app stdio
```

**Claude Code (HTTP — remote):**
```bash
claude mcp add --transport http my-app \
  https://your-service.run.app/ \
  --header "Authorization: Bearer YOUR_TOKEN"
```

**Gemini CLI (stdio — local):**
```bash
gemini mcp add my-app -- mcp-app stdio
```

#### Manual configuration (JSON)

**Claude Code / Gemini CLI (remote):**

Add to `~/.claude.json` or `~/.gemini/settings.json`:

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

**Claude.ai / Claude mobile / Claude Code (remote via URL):**
```
https://your-service.run.app/?token=YOUR_TOKEN
```

Remote MCP servers added through Claude.ai are available across all
Claude clients — web, mobile app, and Claude Code — without separate
configuration for each.

## Architecture

mcp-app wraps [FastMCP](https://github.com/modelcontextprotocol/python-sdk) (the official MCP Python SDK) and [Starlette](https://www.starlette.io/) (ASGI framework). Solutions never import these directly — mcp-app handles all wiring.

```
mcp-app.yaml
    → bootstrap reads config
    → imports tools module, discovers async functions
    → registers each as FastMCP tool (with identity enforcement)
    → creates data store from config
    → HTTP: wraps with identity middleware + admin endpoints → uvicorn
    → stdio: loads user record from store → FastMCP over stdin/stdout
```
