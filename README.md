# mcp-app

Framework for building and running MCP servers as HTTP services.
Define tools as pure Python functions, wire up with two lines, run
with one command.

## Why mcp-app

FastMCP is great for quickly spinning up a local tool. But as soon
as you want to productize it, share it with others, or use it across
multiple identities, you end up building auth, user management, admin
endpoints, and deployment config into each app. They all invariably
get done a little differently.

When you're moving at the speed of agents — building and releasing
impactful tools quickly — you need them to be consistent and secure
without repeating boilerplate into each one and trying to manage all
the implementations. You want to scale impact instead of adding to
the cognitive load needed to keep deploying and trusting you'll be
able to come back and refresh a token or add a user months later.

mcp-app gives you:

- **Identity enforced by default.** JWT auth runs automatically.
  Tools can't execute without an established user. You can't
  accidentally ship a wide-open service.
- **User management built in.** Admin endpoints, CLI for local and
  remote user management, typed profile per user — identical across
  every app.
- **Both transports, same code.** `serve` (HTTP) and `stdio`
  (local) from one `App` object.
- **Free tests for your app.** `mcp_app.testing` checks auth,
  admin, wiring, and tool coverage against your specific app.
  Import the tests, run pytest, confirm everything works.
- **Deployment-ready.** Container, bare metal, Cloud Run, or gapp.

The consistency is the point. User management, token rotation, auth
enforcement, admin CLI — these work the same way across all your
solutions. Learn it once, the tests confirm it works, and when you
need to update a token or revoke a user six months later, the
workflow is the same regardless of which app you're touching.

## Install

```bash
pip install git+https://github.com/echomodel/mcp-app.git
```

## Quick Start

Create your tools module — pure async functions, no framework imports:

```python
# my_app/mcp/tools.py
from my_app.sdk.core import MySDK

sdk = MySDK()

async def do_thing(param: str) -> dict:
    """Tool description shown to agents."""
    return sdk.do_thing(param)
```

Wire up in `__init__.py`:

```python
# my_app/__init__.py
from mcp_app import App
from my_app.mcp import tools

app = App(name="my-app", tools_module=tools)
```

For API-proxy apps with per-user credentials:

```python
# my_app/__init__.py
from pydantic import BaseModel
from mcp_app import App
from my_app.mcp import tools

class Profile(BaseModel):
    token: str

app = App(
    name="my-app",
    tools_module=tools,
    profile_model=Profile,
    profile_expand=True,
)
```

`profile_expand=True` generates typed CLI flags (`--token`) on
the admin CLI. `profile_expand=False` (default) accepts profile
as JSON or `@file`.

Add entry points to `pyproject.toml`:

```toml
[project.scripts]
my-app-mcp = "my_app:app.mcp_cli"
my-app-admin = "my_app:app.admin_cli"

[project.entry-points."mcp_app.apps"]
my-app = "my_app:app"
```

The `mcp_app.apps` entry point lets the test suite and tooling
discover your app automatically.

Run:

```bash
my-app-mcp serve                   # HTTP, multi-user
my-app-mcp stdio --user local      # stdio, single user
```

No config files. Tool discovery, identity middleware, admin endpoints,
and store wiring are handled by the framework from the Python args.

### Store

Default store is filesystem — per-user directories under
`~/.local/share/{name}/users/`. Override with `APP_USERS_PATH`
env var. Custom store backends can be passed to `App`.

### Middleware

Identity middleware runs automatically in HTTP mode. It validates
JWTs, loads the full user record from the store, and sets the
`current_user` ContextVar. No configuration needed.

See [docs/custom-middleware.md](docs/custom-middleware.md) for
advanced middleware configuration.

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

**What's identical:** store setup, admin endpoints, tool discovery, deployment. The middleware is the same. The SDK decides what to read from the user context.

### Tool Discovery

The `tools` module is imported and all public async functions (not starting with `_`) are registered as MCP tools. Function names become tool names. Docstrings become descriptions. Type hints become schemas.

## Environment Variables

| Variable | Required | If Missing | Purpose |
|----------|----------|------------|---------|
| `SIGNING_KEY` | For HTTP | Startup fails | JWT signing key |
| `JWT_AUD` | No | Audience not validated | Expected JWT `aud` claim |
| `APP_USERS_PATH` | No | `~/.local/share/{name}/users/` | Per-user data directory |
| `TOKEN_DURATION_SECONDS` | No | 315360000 (~10yr) | Token lifetime in seconds |

**`SIGNING_KEY`** is a secret. Never commit it to the repo. Generate
a strong random value:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

How it gets into the environment depends on your deployment: CI/CD
secrets (e.g., GitHub Actions), cloud secret managers (e.g., GCP
Secret Manager), or deployment tools that generate and manage
secrets directly.

**`JWT_AUD`** — if unset, audience is not validated. Apps sharing the
same signing key without distinct `JWT_AUD` values will accept each
other's user tokens. If each app has a unique signing key, audience
validation is less critical.

**`APP_USERS_PATH`** — the default writes to the local filesystem,
which works for development. In a container, this path is ephemeral
— the app starts, users get registered, tools execute, and then
user data is silently lost on container restart. No error, no
warning. For any persistent deployment, set `APP_USERS_PATH` to a
mounted volume or persistent storage path.

**`TOKEN_DURATION_SECONDS`** — the default (~10 years) effectively
means tokens are permanent. Set a shorter value if tokens should
expire. Applies to newly issued tokens only.

## User Identity and Profile

Every mcp-app solution has a `current_user` ContextVar set before tools execute. No default — tools that run without an established identity return an error.

| Transport | How it's set |
|-----------|-------------|
| HTTP (`my-app-mcp serve`) | Identity middleware validates JWT, loads full user record from store |
| stdio (`my-app-mcp stdio`) | CLI loads user record from store using `--user` flag |

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

### stdio identity

stdio user identity is always specified via the `--user` flag:

```bash
mcp-app stdio --user local
my-app-mcp stdio --user alice@example.com
```

The CLI loads the user record from the store and sets `current_user`.
Refuses to start without `--user`.

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
from mcp_app.bootstrap import build_asgi
from my_app.mcp import tools
import httpx

app, mcp, store = build_asgi("my-app", tools)
transport = httpx.ASGITransport(app=app)
client = httpx.AsyncClient(transport=transport, base_url="http://test")
```

`build_asgi()` returns the same ASGI app the CLI gives to uvicorn.
httpx runs it in-process. If it works here, it works in Docker.
httpx is already a dependency of mcp-app.

See CONTRIBUTING.md for full test examples.

## Running the Server

### stdio (local, single user)

No auth, no signing key, no server process. The MCP client launches
the process directly:

```bash
my-app-mcp stdio --user local
```

`--user` is required — it specifies which user record to load from
the store. Refuses to start without it.

### HTTP (multi-user)

```bash
SIGNING_KEY=your-key my-app-mcp serve
```

With persistent storage and all options:

```bash
SIGNING_KEY=your-key \
APP_USERS_PATH=/data/my-app/users \
JWT_AUD=my-app \
TOKEN_DURATION_SECONDS=2592000 \
  my-app-mcp serve --host 0.0.0.0 --port 8080
```

Runs uvicorn on `0.0.0.0:8080` by default. Override with `--host`
and `--port`.

## Deployment

mcp-app is a standard Python app. Deploy it however you deploy
Python — as a process, in a container, on any platform. The app
does not know or care how it was deployed.

### Runtime contract

Any deployment environment must provide:

- **Start command:** `my-app-mcp serve` (optionally `--host` /
  `--port`, default `0.0.0.0:8080`)
- **`SIGNING_KEY` env var** — required for HTTP. A secret — must
  not be committed to the repo or hardcoded in config files.
  Source it from a secrets store, CI/CD secrets, or have the
  deployment tool generate it (see Environment Variables above)
- **`APP_USERS_PATH` env var** — must point to persistent storage
  for any durable deployment. The default writes to the local
  filesystem, which is ephemeral in containers (see Environment
  Variables above)
- **MCP endpoint:** `/` (root path). MCP clients connect to
  `https://host:port/`, not `/mcp`
- **Health check:** `GET /health` — no auth, returns
  `{"status": "ok"}`
- **Admin API:** `/admin/users` (POST, GET),
  `/admin/users/{email}` (DELETE), `/admin/tokens` (POST)
- **Auth model:** mcp-app handles its own auth via JWT. If the
  platform has an auth gate (IAM, API gateway, etc.), configure
  it to allow unauthenticated traffic through to the app
- **Build root:** the repo root where `pyproject.toml` lives

### Bare metal

```bash
pip install -e .
SIGNING_KEY=your-key my-app-mcp serve
```

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install -e .
EXPOSE 8080
CMD ["my-app-mcp", "serve"]
```

```bash
docker build -t my-app .
docker run -p 8080:8080 \
  -e SIGNING_KEY=your-key \
  -v /persistent/path:/data \
  -e APP_USERS_PATH=/data/users \
  my-app
```

The Dockerfile works on any container platform. The volume mount
ensures user data survives container restarts.

### Cloud platforms

Deploy from source or a container image using your platform's
tooling. Set `SIGNING_KEY` via the platform's secret manager and
`APP_USERS_PATH` to a persistent volume. Ensure the platform
allows unauthenticated HTTP traffic through to the app.

Deployment tools like [gapp](https://github.com/echomodel/gapp)
can automate infrastructure, secrets, and container builds.

### Post-deploy verification

**1. Liveness** — confirm the process is up:
```bash
curl https://your-service/health
# {"status": "ok"}
```

**2. Admin auth** — confirm admin JWT works and the store is
connected:
```bash
my-app-admin connect https://your-service --signing-key xxx
my-app-admin users list
```

**3. Register a user** and get their token:
```bash
my-app-admin users add alice@example.com
# Returns: {"email": "alice@example.com", "token": "..."}
```

**4. User auth** — confirm user JWT works end-to-end by calling
`tools/list`. This goes through user JWT middleware (not admin),
loads the user record from the store, and returns registered
tools:
```bash
curl -X POST https://your-service/ \
  -H "Authorization: Bearer USER_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 1}'
```

If this returns the tool list, user auth works, the store loaded
the user record, and tools are wired. The app is fully operational.

## User Management

### Setup

```bash
# Local (filesystem store on this machine)
my-app-admin connect local

# Remote (deployed instance)
my-app-admin connect https://your-service --signing-key xxx
```

All subsequent commands route automatically based on the
connection mode.

### Managing users

```bash
# Register users
my-app-admin users add alice@example.com
my-app-admin users add bob@example.com --profile '{"token": "api-key-xxx"}'

# List users
my-app-admin users list

# Revoke a user (invalidates all their tokens)
my-app-admin users revoke alice@example.com

# Issue a new token for an existing user
my-app-admin tokens create alice@example.com

# Health check (remote only)
my-app-admin health
```

The token returned from `users add` or `tokens create` is what
the user puts in their MCP client configuration.

## MCP Client Configuration

### stdio (local)

No signing key needed — stdio has no JWT auth.

**CLI registration:**
```bash
claude mcp add my-app -- my-app-mcp stdio --user local
gemini mcp add my-app -- my-app-mcp stdio --user local
```

**Manual config** (`~/.claude.json` or `~/.gemini/settings.json`):
```json
{
  "mcpServers": {
    "my-app": {
      "command": "my-app-mcp",
      "args": ["stdio", "--user", "local"]
    }
  }
}
```

### HTTP (remote)

**CLI registration:**
```bash
claude mcp add --transport http my-app \
  https://your-service/ \
  --header "Authorization: Bearer USER_TOKEN"
```

**Manual config** (`~/.claude.json` or `~/.gemini/settings.json`):
```json
{
  "mcpServers": {
    "my-app": {
      "url": "https://your-service/",
      "headers": {
        "Authorization": "Bearer ${MY_APP_TOKEN}"
      }
    }
  }
}
```

Both Claude Code and Gemini CLI support `${VAR}` expansion in
config files — reference a host environment variable instead of
pasting the token directly.

**Claude.ai / Claude mobile (remote via URL):**
```
https://your-service/?token=USER_TOKEN
```

Remote MCP servers added through Claude.ai are available across
all Claude clients — web, mobile, and Claude Code.

## Architecture

mcp-app wraps [FastMCP](https://github.com/modelcontextprotocol/python-sdk) (the official MCP Python SDK) and [Starlette](https://www.starlette.io/) (ASGI framework). Solutions never import these directly — mcp-app handles all wiring.

```
App(name="my-app", tools_module=tools)
    → discovers async functions in tools module
    → registers each as FastMCP tool (with identity enforcement)
    → creates data store from app name
    → HTTP (serve): wraps with identity middleware + admin endpoints → uvicorn
    → stdio (--user): loads user record from store → FastMCP over stdin/stdout
```

## Free Tests for Your App

mcp-app ships reusable test modules that check auth, user admin,
JWT enforcement, CLI wiring, and tool protocol compliance against
your specific app. Import them in two files, provide your `App`
object as a fixture, and get 25+ tests for free.

### 1. Create `tests/framework/conftest.py`

```python
import pytest
from my_app import app

@pytest.fixture(scope="session")
def app():
    return app
```

### 2. Create `tests/framework/test_framework.py`

```python
from mcp_app.testing.iam import *
from mcp_app.testing.wiring import *
from mcp_app.testing.tools import *
from mcp_app.testing.health import *
```

This file is identical across all mcp-app solutions. The
`conftest.py` is the only file that changes — it points the
tests at your specific `App` object.

### 3. Run

```bash
pytest tests/
```

Zero failures means: auth works, admin works, tools are wired,
identity is enforced, and the SDK has test coverage for every
tool. Your app is correctly built on mcp-app.

## Further Reading

- [docs/custom-middleware.md](docs/custom-middleware.md) — advanced middleware configuration
- [CONTRIBUTING.md](CONTRIBUTING.md) — architecture, design decisions, testing
