# Contributing to mcp-app

## Architectural Decisions

### Agent-composed over provider-coupled (admin tools)

The original design proposed a provider plugin system where mcp-app internally
discovers deployment backends. This was rejected in favor of stateless admin
tools that the AI agent orchestrates externally.

**Reasoning:**
- The agent IS the orchestrator — building a second integration layer in code
  adds coupling for no benefit
- MCP's design intent: tools are stateless, self-describing, composed by the
  caller
- Unix philosophy: small tools, agent-composed. Neither mcp-app nor deployment
  tools know about each other
- The deploy→verify→manage workflow happens naturally when agents call tools
  in sequence

**What this means in practice:**
- RemoteAuthAdapter is stateless — takes a URL and signing key, makes REST calls
- MCP admin tools take `base_url` and `signing_key` as explicit parameters
- No internal references to gapp, Cloud Run, or any deployment tool
- The admin tools don't know how the service was deployed or where the signing
  key came from

### cwd is never used for deploy or admin

App-specific CLIs (`my-app-mcp serve`, `my-app-admin`) get their config
from Python args — they work from any directory. The `mcp-app` generic
CLI is for remote admin (setup, users, health) when you don't have the
app's own admin CLI installed locally. No command depends on the current
working directory.

### Config vs problem-domain resources

`config` subcommands are for tool preferences (output format, storage backend,
keychain settings). Problem-domain resources (fleets, users, tokens) get their
own top-level command groups with CRUD operations. Never mix them.

**Test:** "If I deleted this, would I lose work or just a preference?"
- Preference → `config`
- Managed resource → its own command group

### Signing key storage

The fleetless admin path needs to persist a signing key locally.

- **Default:** OS keychain via `keyring` library (macOS Keychain, Windows
  Credential Manager, Linux Secret Service). Zero config on desktop platforms.
- **Fallback:** file-based storage in XDG config dir, chosen explicitly via
  `mcp-app config signing-key-store file`. Never a silent fallback — fail
  with an actionable hint if keychain is unavailable.
- **Escape hatch:** `MCP_APP_SIGNING_KEY` env var or `--signing-key` flag
  always work.
- **Fleet mode:** the deploy provider resolves the signing key from the cloud's
  secret store on demand. Nothing stored locally.

Note: current code writes to `active.json` in plaintext. This should migrate
to keychain-first once `keyring` is added as a dependency.

### Separate fleets over local override files

An earlier design used a gitignored `.fleet.local.yaml` that extended the
shared fleet manifest with local-only solutions. This was rejected because
any mechanism that layers config on top of shared state risks mutating it —
even "additive" changes to existing objects can be destructive (changing a
region, adding a config field that alters provider behavior, overriding a
secret reference).

Separate fleets eliminate this entirely. Each fleet is self-contained. Want
local docker instances? Put them in a `local` fleet. Shared Cloud Run
services? They're in `work`. They never mix, merge, or conflict.

### Credentials are the SDK's concern, not the framework's

Earlier designs had credential proxy middleware (`bearer-proxy`,
`google-oauth2-proxy`) that loaded backend credentials, refreshed
OAuth2 tokens, and rewrote HTTP Authorization headers. This was
built, shipped, and removed after deeper analysis:

- MCP tool functions don't read HTTP headers. The middleware rewrote
  a header nobody consumed.
- The SDK already knows what credentials it needs. An API-proxy SDK
  calls an external API — it knows whether it needs a bearer token
  or Google OAuth2. The framework adding a layer between "credential
  in store" and "credential in SDK" added coupling without value.
- Google's `google-auth` library handles OAuth2 refresh natively.
  The middleware was reimplementing what the SDK's own dependencies
  provide.

Credentials are stored in the user profile (loaded once at auth time
with the auth record). The SDK reads `current_user.get().profile` and
interprets the contents. mcp-app doesn't know what's in the profile.

### One user record, one store read

Auth fields (email, created, revoke_after) and profile data are
stored together in one record per user. The verifier loads the whole
record in one store read and sets `current_user` — no second read
for credentials or profile. The SDK reads what it needs from the
already-loaded record.

### Three CLI entry points per app

Apps generate three separate CLI entry points from one codebase:

- `my-app` — the app's own business CLI (optional, app-specific)
- `my-app-mcp` — `serve` and `stdio` (from `create_mcp_cli`)
- `my-app-admin` — `connect`, `users`, `tokens`, `health`
  (from `create_admin_cli`)

**Why three, not one:** The app's business CLI, MCP server commands,
and admin operations are different concerns with different audiences.
Mixing them in one CLI creates a confusing top-level command space.
Separating them lets each be self-contained — `my-app-admin` can be
used by an operator who doesn't need the app's business commands.

**Why `admin` is separate from `mcp`:** Admin manages users (add,
list, revoke). MCP runs the server (serve, stdio). An operator
managing users on a deployed instance doesn't need serve/stdio. A
developer running the server locally doesn't need user management
commands in the same CLI. Different jobs, different tools.

**Why `admin` is separate from the app CLI:** Admin has its own
config (`connect local` or `connect <url>`). If admin commands
shared the app's CLI, that config could conflict with or leak into
the app's own configuration. `gwsa admin connect https://...`
should never affect `gwsa drive search`. Separate entry points
mean separate config scopes — admin writes to its own setup file,
the app CLI never reads it.

### UserAuthStore protocol — one interface, two backends

User management operations (add, list, revoke) go through the
`UserAuthStore` protocol. Two implementations:

- `DataStoreAuthAdapter` — wraps any `UserDataStore` for local
  filesystem (or any custom store). Direct store writes.
- `RemoteAuthAdapter` — wraps HTTP calls to a deployed instance's
  `/admin` endpoints.

The CLI calls `_get_auth_store()` which returns the right adapter
based on the `connect` config (local or remote URL). All user
management commands use the same interface — no branching in CLI
command code.

### `connect local` vs `connect <url>`

The admin CLI needs to know where to manage users. Two modes:

- `connect local` — write directly to the local filesystem store.
  For stdio apps running on this machine.
- `connect <url> --signing-key xxx` — talk to a deployed instance
  via HTTP admin API. For managing users on a remote server.

This is configured once and remembered in
`~/.config/{app-name}/setup.json`. Subsequent `users` commands
route automatically. The user doesn't think about local vs remote
on every command.

### Profile registration is optional

`register_profile(Model)` declares a Pydantic model for typed
profile validation. This is for API-proxy apps that need structured
per-user credentials. Data-owning apps (no per-user credentials)
skip it entirely — `user.profile` is `None`.

When registered with `expand=True`, the admin CLI generates typed
flags from the model fields (e.g., `--token`). When registered with
`expand=False`, the CLI accepts the profile as a JSON string or
`@file`.

### SIGNING_KEY has no default

Earlier versions defaulted to `"dev-key"`. This was removed because
the code is in a public repo — anyone who reads it can forge JWTs.
`SIGNING_KEY` must be explicitly set as an environment variable for
HTTP mode. Missing or empty raises `RuntimeError` at startup.

### stdio identity comes from --user, not yaml

`mcp-app stdio --user local` specifies the user identity. There is
no config file for stdio identity. Identity is a runtime
argument, not a versioned config setting — putting it in yaml would
mean committing user choices to version control.

## What mcp-app Is

A config-driven framework for building and running MCP servers as HTTP
services (and eventually stdio). Solutions define tools as pure Python
functions. The framework handles everything else: FastMCP setup, tool
discovery, middleware, auth, admin endpoints, data stores, and serving.

### Core principle: zero framework imports in tool code

Tools are plain async functions. Docstrings become MCP tool descriptions.
Type hints become tool schemas. No `@mcp.tool()` decorators. The framework
discovers and registers tools automatically from the module passed to
`create_mcp_cli`.

How this works: bootstrap receives the tools module, finds all public
async functions via `inspect`, and calls `mcp.tool()(func)` on each one.
The decorator still runs — mcp-app just calls it for you so your tools
module has no framework coupling.

### What mcp-app provides

- `create_mcp_cli()` / `create_admin_cli()` CLI factories
- `create_app_cli()` factory for app-specific CLIs with typed profile flags
- Tool discovery from module path (public async functions)
- Store abstraction (`filesystem` built-in, custom via module path)
- Identity middleware (`user-identity`) — runs by default in HTTP mode
- Admin REST endpoints at `/admin` (register with profile, list, revoke, tokens)
- `current_user` ContextVar — `User` object with `.email` and `.profile`
- `register_profile()` — typed profile validation via Pydantic
- `UserAuthStore` protocol
- `UserDataStore` protocol + `FileSystemUserDataStore`
- `DataStoreAuthAdapter` bridge
- `JWTVerifier`
- `RemoteAuthAdapter` — stateless REST client for deployed instances
- MCP admin tools server (`mcp-app admin-tools`)

### What mcp-app does NOT provide

- Deployment (gapp or any container platform handles this)
- CLI scaffolding (solutions use Click directly)
- SDK scaffolding (solutions write their own)
- Dockerfile generation (gapp handles this)

## Two Transports: HTTP and stdio

A solution built with mcp-app works over both transports without code
changes. Same yaml, same tools module, same SDK.

### HTTP mode (`mcp-app serve`)

The full production stack:
- FastMCP wrapped with identity middleware (runs by default)
- Admin REST endpoints at `/admin`
- `current_user` set by verifier: full user record (auth + profile) in one store read
- uvicorn runs internally (port 8080 by default)
- Store wired and accessible via `get_store()`

### stdio mode (`mcp-app stdio`)

Local single-user mode:
- FastMCP runs over stdin/stdout
- No middleware, no admin endpoints, no ASGI layer
- `current_user` loaded from store using `--user` flag
- Store still wired — `get_store()` works the same way
- Tool discovery identical to HTTP — same module, same functions

**Why mcp-app matters for stdio:** Without it, solutions that want stdio
must use FastMCP directly with `@mcp.tool()` decorators and manual setup.
With `mcp-app stdio`, the same yaml-driven tool discovery works for both
transports. One build, two commands.

**When raw FastMCP is fine for stdio:** If the solution is stdio-only, has
no store, no identity concerns, and no plans for HTTP — raw FastMCP with
decorators is simpler. mcp-app adds value when the solution needs both
transports or uses the store/identity infrastructure.

### stdio identity

Identity in stdio mode is a simple string — there is no authentication.
The MCP client launches the process directly; if you can run the command,
you're in. The `--user` flag specifies which user record to load from
the store:

```bash
mcp-app stdio --user local
my-app-mcp stdio --user alice@example.com
```

`--user` is required. There is no yaml config for stdio identity —
it's a runtime argument, not a versioned setting. `mcp-app stdio`
refuses to start without it.

### Solution entry points

Solutions declare a console script that invokes `mcp-app stdio`:

```toml
[project.scripts]
my-solution-mcp = "my_solution.cli:run_stdio"
```

Users register with: `claude mcp add my-solution -- my-solution-mcp`

## Tool Discovery

The tools module is a Python module passed to `create_mcp_cli`. All
public async functions in it are registered as MCP tools:

```python
# my_solution/mcp/tools.py
from my_solution.sdk.core import MySDK

sdk = MySDK()

async def do_thing(param: str) -> dict:
    """Do the thing for the current user."""
    return sdk.do_thing(param)
```

- Function name → tool name (`do_thing`)
- Docstring → tool description shown to agents
- Type hints → input schema
- Functions starting with `_` are skipped
- Sync functions are skipped (only async)

This is the mechanism that eliminates `@mcp.tool()` decorators. The
decorator still runs internally — bootstrap calls `mcp.tool()(func)`
for each discovered function.

## Middleware and Identity

### How identity works

Identity middleware (`user-identity`) runs by default in HTTP mode. It:
1. Extracts JWT from Authorization header or `?token=` query param
2. Validates JWT signature and claims via `JWTVerifier`
3. Loads the full user record from the store (auth + profile, one read)
4. Hydrates the profile with the registered Pydantic model if available
5. Sets `current_user` ContextVar — available to all tool functions

The SDK reads `current_user.get()` and gets a `UserRecord` with `.email`
and `.profile`. One import, one call, typed access.

### Default behavior

If `middleware` is omitted from yaml (the common case), `user-identity`
runs automatically. To add custom middleware or disable auth:

```yaml
# Custom middleware — must include user-identity explicitly
middleware:
  - my_app.auth.RateLimiter
  - user-identity

# Explicitly no auth
middleware: []
```

### Why no credential proxy middleware

Earlier designs had `bearer-proxy` and `google-oauth2-proxy` middleware
that resolved backend credentials and rewrote HTTP Authorization headers.
These were removed because:

- **MCP tool functions don't read HTTP headers.** The middleware rewrote
  a header that nobody read. Tools call SDK methods, not HTTP endpoints.
- **Credentials are the SDK's concern.** The SDK knows what kind of
  credential it needs (bearer token, Google OAuth2, etc.) and how to
  use it. The framework shouldn't interpret credential contents.
- **One record, one read.** The user profile (which includes credentials)
  is loaded alongside the auth record by the verifier. No second store
  read needed. The SDK reads `current_user.get().profile` — already in
  memory.
- **Token refresh is the SDK's concern.** Google's `google-auth` library
  handles OAuth2 token refresh. The SDK refreshes explicitly before API
  calls and writes back to the store. mcp-app doesn't need to know about
  Google tokens.

The identity middleware handles authentication (who is this user?). The
SDK handles authorization and credential usage (what can this user do?
what backend token do they have?).

### Why pure ASGI middleware, not FastMCP's built-in auth

FastMCP provides `TokenVerifier`, `BearerAuthBackend`, and `ctx.client_id`.
We rejected these because:

- It couples the framework to FastMCP — mcp-app should work with any ASGI
  app
- `ctx.client_id` is only available inside MCP tool functions, not in the
  SDK layer
- The SDK would need to import FastMCP or bridge from `ctx.client_id` to a
  ContextVar per tool function

Pure ASGI middleware owns the ContextVar and sets it before any app code
runs. The SDK reads it. No bridging. No FastMCP imports in the SDK.

### Two app patterns — same middleware, different SDK behavior

Both data-owning and API-proxy apps use `user-identity` middleware (the
default). The difference is what the SDK reads from `current_user`:

**Data-owning** (echofit — food logs, notes):
```python
user = current_user.get()
store = get_store()
store.save(user.email, "daily/2026-04-10", entries)
```

**API-proxy** (some-third-party-api — wraps external API):
```python
user = current_user.get()
token = user.profile["token"]
resp = httpx.get("https://api.example.com/...",
                 headers={"Authorization": f"Bearer {token}"})
```

**API-proxy with OAuth2 refresh** (gwsa — wraps Google APIs):
```python
user = current_user.get()
creds = Credentials.from_authorized_user_info(user.profile)
if creds.expired:
    creds.refresh(Request())
    get_store().update_profile(user.email, json.loads(creds.to_json()))
service = build("gmail", "v1", credentials=creds)
```

## Store Architecture

### UserDataStore protocol

Generic per-user JSON storage: `load(user, key)`, `save(user, key, data)`,
`list_users()`, `delete(user, key)`.

### UserAuthStore protocol

What the auth framework needs: `get(email)`, `list()`, `save(record)`,
`delete(email)`. Operates on `UserAuthRecord` (email, created,
revoke_after).

### DataStoreAuthAdapter

Bridges `UserDataStore` → `UserAuthStore`. The full user record (auth
fields + profile) is stored under one key per user. One store read gets
everything — the verifier loads auth + profile together, sets
`current_user` with the complete record.

### Why two protocols

Auth doesn't know about app data. A MySQL app can implement
`UserAuthStore` against its customers table without ever using
`UserDataStore`. The bridge is optional convenience for simple
filesystem-based apps.

### User record structure

The adapter stores one record per user containing both auth fields and
the app profile:

```json
{
  "email": "alice@example.com",
  "created": "2026-04-01T00:00:00",
  "revoke_after": null,
  "profile": {"token": "some-third-party-api-pat-xxx"}
}
```

Auth fields (`email`, `created`, `revoke_after`) are managed by the
framework. The `profile` field is opaque to mcp-app — the SDK interprets
it. Both are loaded in one store read at auth time.

## Relationship to Other Packages

### gapp (deployment)

gapp deploys containers to Cloud Run. It doesn't know about mcp-app's
internals. mcp-app doesn't know about gapp. Neither imports the other.

gapp config for how to run the app:
- `service.cmd: my-app-mcp serve` — for mcp-app solutions
- `service.entrypoint: my_app.mcp.server:app` — for raw FastMCP/uvicorn

See the deployment matrix in README.md for all deployment options
(bare metal, Docker, gcloud --source, gapp) with both mcp-app and
FastMCP.

### app-user (archived)

`app-user` was the original standalone auth library. mcp-app absorbed all
its code. The `app-user` repo is archived. Solutions use
`from mcp_app import ...`.

### gapp_run (legacy)

`gapp_run` is gapp's ASGI runtime wrapper that handled credential
mediation for API-proxy solutions. It's legacy — credential management
moved to the SDK layer (profile on `current_user`, SDK handles token
refresh). `gapp_run` remains for backward compatibility with solutions
that haven't migrated to mcp-app.

## SDK-First Architecture

All business logic lives in the core layer, not in CLI or MCP wrappers.

- `admin_client.py` — RemoteAuthAdapter, UserAuthStore over HTTP
- `cli.py` — thin Click wrapper, calls SDK, formats output
- `admin_tools.py` — thin MCP wrapper, calls SDK, handles tool schema

If you're writing logic in a CLI command or MCP tool handler, stop and move
it to the SDK.

## Testing and Local Validation

### The pattern: httpx ASGI transport

mcp-app and solutions built on it validate locally without running a
server, without Docker, and without any cloud dependencies. The key is
httpx's ASGI transport — it runs the full ASGI app in-memory:

```python
from mcp_app.bootstrap import build_app
import httpx

app, mcp, store, config = build_app()
transport = httpx.ASGITransport(app=app)
client = httpx.AsyncClient(transport=transport, base_url="http://test")
```

`build_asgi()` returns the complete ASGI app — same object that
`my-app-mcp serve` gives to uvicorn. Giving it to httpx
instead means the full stack runs in-process: tool discovery, middleware,
admin endpoints, store wiring. No server process, no port binding, no
cleanup.

**If it works in httpx ASGI transport, it works in uvicorn, it works in
Docker.** The ASGI app is the app. Transport is just how bytes get in
and out.

httpx is already a direct dependency of mcp-app (used by RemoteAuthAdapter),
so solutions get it for free. No extra dependencies to write tests.

### What to test in solutions

Solutions should validate their tools and auth flow locally:

```python
import os
import pytest
import httpx
from mcp_app.bootstrap import build_app

@pytest.fixture
def app_client(tmp_path):
    """Build the full ASGI app and return an httpx client."""
    os.environ["APP_USERS_PATH"] = str(tmp_path / "users")
    os.environ["SIGNING_KEY"] = "test-key"
    app, mcp, store, config = build_app()
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")

@pytest.mark.asyncio
async def test_admin_register_and_list(app_client):
    """Register a user via admin API, verify they appear in list."""
    # Mint an admin token
    import jwt as pyjwt
    from datetime import datetime, timezone, timedelta
    admin_token = pyjwt.encode(
        {"sub": "admin", "scope": "admin",
         "iat": datetime.now(timezone.utc),
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        "test-key", algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Register
    resp = await app_client.post(
        "/admin/users",
        json={"email": "user@example.com"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data

    # List
    resp = await app_client.get("/admin/users", headers=headers)
    assert resp.status_code == 200
    users = resp.json()
    assert any(u["email"] == "user@example.com" for u in users)
```

This tests the full stack: yaml config → tool discovery → middleware →
admin endpoints → store → filesystem. Same code path as production.

### mcp-app's own tests

mcp-app uses the same pattern internally:

```python
transport = httpx.ASGITransport(app=starlette_app)
http_client = httpx.AsyncClient(transport=transport, base_url="http://test")
client = RemoteAuthAdapter("http://test", signing_key, http_client=http_client)
```

RemoteAuthAdapter → httpx → ASGI → Starlette → admin.py → FileSystemUserDataStore → tmp_path.

### stdio validation

Register with an MCP client directly:

```bash
claude mcp add my-app -- mcp-app stdio
```

Claude Code launches the process and manages its lifecycle. No background
server, no port management, no cleanup. Call tools through the agent.

Use `--user` to select a specific user account for the session:

```bash
claude mcp add my-app -- mcp-app stdio --user alice@example.com
```

### What httpx ASGI transport validates

Everything that matters for deployment readiness:
- Tool discovery from the tools module
- Middleware auth (JWT validation, user identity)
- Admin endpoints (user registration, listing, tokens)
- Store wiring (per-user data, auth records)
- SDK business logic (your actual tools)

What it doesn't test (and doesn't need to):
- Port binding (trivial, uvicorn handles it)
- DNS/networking (transport plumbing, not app logic)
- Container startup (Dockerfile concern, not app concern)

## Dependencies

httpx is a direct dependency (used by RemoteAuthAdapter). It is also the #2 Python
HTTP client by downloads (~500M/month), maintained by Encode (author of Django
REST Framework and Starlette), and a hard dependency of every major AI SDK
(OpenAI, Anthropic, Google GenAI). It was already a transitive dependency via
starlette and mcp.
