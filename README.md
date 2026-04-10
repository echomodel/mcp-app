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
| `bearer-proxy` | Validates JWT, swaps for stored backend token (PAT, API key), rewrites Authorization header. For API-proxy apps. (Planned — [#8](https://github.com/echomodel/mcp-app/issues/8)) |
| `google-oauth2-proxy` | Like bearer-proxy but refreshes expired Google OAuth2 access tokens. For apps wrapping Google APIs. (Planned — [#8](https://github.com/echomodel/mcp-app/issues/8)) |
| `my.module.MyMiddleware` | Custom. ASGI middleware class with signature `__init__(self, app, verifier, store=None)` |

Middleware is an array — order matters (first = outermost). Omit entirely for no auth.

### Two App Patterns

Data-owning apps and API-proxy apps use nearly identical setup. The only difference is one line in `mcp-app.yaml`:

**Data-owning app** (owns user data — food logs, notes, etc.):

```yaml
# mcp-app.yaml
name: my-data-app
store: filesystem
middleware:
  - user-identity
tools: my_data_app.mcp.tools
```

```python
# my_data_app/mcp/tools.py
from my_data_app.sdk.core import MySDK

sdk = MySDK()

async def save_entry(data: dict) -> dict:
    """Save a data entry for the current user."""
    return sdk.save(data)  # SDK reads current_user_id internally
```

The `user-identity` middleware validates the JWT, extracts the user's email from the `sub` claim, and sets the `current_user_id` ContextVar. The SDK reads it to scope data per user. The request passes through unchanged.

**API-proxy app** (wraps an external API — financial data, task management, etc.):

```yaml
# mcp-app.yaml — static tokens (PATs, API keys)
name: my-api-proxy
store: filesystem
middleware:
  - bearer-proxy
tools: my_api_proxy.mcp.tools
```

```yaml
# mcp-app.yaml — Google APIs (OAuth2 with token refresh)
name: my-google-proxy
store: filesystem
middleware:
  - google-oauth2-proxy
tools: my_google_proxy.mcp.tools
```

```python
# my_api_proxy/mcp/tools.py
from my_api_proxy.sdk.core import MySDK

sdk = MySDK()

async def list_items() -> dict:
    """List items from the external API."""
    return sdk.list_items()  # SDK reads Authorization header (backend token)
```

The proxy middleware validates the JWT, looks up the stored backend credential for that user, resolves an access token (passthrough for bearer, refresh for Google OAuth2), and rewrites the `Authorization` header. The SDK receives a valid backend API token — it doesn't know about JWTs or user management.

Note: `bearer-proxy` and `google-oauth2-proxy` are planned — see [#8](https://github.com/echomodel/mcp-app/issues/8). Custom middleware via module path works today for API-proxy apps.

**What's identical:** store setup, admin endpoints, tool discovery, `mcp-app.yaml` structure, deployment. Only the middleware choice differs.

### Tool Discovery

The `tools` module is imported and all public async functions (not starting with `_`) are registered as MCP tools. Function names become tool names. Docstrings become descriptions. Type hints become schemas.

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `SIGNING_KEY` | For HTTP | none — required | JWT signing key. Must be set when middleware is configured. |
| `JWT_AUD` | No | None (skip) | Token audience validation |
| `APP_USERS_PATH` | No | `~/.local/share/{name}/users/` | Per-user data directory |
| `TOKEN_DURATION_SECONDS` | No | 315360000 (~10yr) | Default token lifetime |

## User Identity

Every mcp-app solution requires that `current_user_id` is set before tools execute. There is no default — tools that run without an established identity return an error.

| Transport | How identity is set |
|-----------|-------------------|
| HTTP (`mcp-app serve`) | Middleware extracts it from the JWT `sub` claim |
| stdio (`mcp-app stdio`) | Configured in `mcp-app.yaml` under `stdio.identity` |
| Direct SDK use | Caller sets `current_user_id` explicitly before calling SDK methods |

The SDK reads it:

```python
from mcp_app.context import current_user_id

user = current_user_id.get()  # "alice@example.com" (HTTP) or "local" (stdio)
```

### stdio identity configuration

```yaml
# mcp-app.yaml
stdio:
  user: "local"
```

The `user` value is set as `current_user_id` for the session. It scopes
data storage — `~/.local/share/{name}/users/{user}/`. There is no
authentication in stdio mode; the MCP client launches the process directly.

`mcp-app stdio` refuses to start without `stdio.user` configured.

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

Note: Claude Code does not currently support env var interpolation in
HTTP headers. Tokens are stored in cleartext in the local config. For
stdio servers, use `-e KEY=value` to pass secrets as environment
variables.

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
