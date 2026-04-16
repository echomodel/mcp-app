---
name: author-mcp-app
description: "Build, structure, deploy, and manage Python MCP servers and web APIs. Use when asked to create a new MCP server, structure a solution repo, add multi-user auth, set up a data store, migrate an existing app, review an app against standards, deploy and test a solution, manage users on a deployed instance, connect an admin CLI, or any question about building or operating a deployable Python MCP service — \"create an MCP server\", \"add auth to my app\", \"deploy and test this\", \"redeploy and verify\", \"set up user management\", \"manage users\", \"connect the admin CLI\", \"how do I get the signing key\", \"make this multi-user\", \"review my solution\", \"is this ready to deploy\", etc."
disable-model-invocation: false
user-invocable: true
---

# Author MCP App

## Overview

This skill guides users through building Python MCP servers and
web APIs that are self-contained, deployable apps. Solutions built
with this guidance work locally (stdio, single user) and deployed
(HTTP, multi-user) without code changes.

## Framework Choice

This skill supports two approaches:

### Recommended: mcp-app (config-driven)

[mcp-app](https://github.com/echomodel/mcp-app) is a framework that
wraps FastMCP and Starlette. You define tools as plain async functions,
wire up with two lines in Python, and run with one command. No config
files, no framework imports in your tool code.

**What the user gets with mcp-app:**

- **Zero framework code in tools.** Tools are plain async functions.
  No decorators, no FastMCP imports, no framework coupling in
  business code. mcp-app discovers public async functions from the
  module declared in `tools:` and registers them automatically —
  function names become tool names, docstrings become descriptions,
  type hints become schemas.

- **User identity and profile.** Identity middleware runs by default
  in HTTP mode — validates JWTs, loads the full user record (auth +
  profile) in one store read, sets `current_user` ContextVar. The
  SDK reads `current_user.get()` for user identity and profile data.

- **User management out of the box.** REST admin endpoints
  (`POST /admin/users`, `GET /admin/users`,
  `DELETE /admin/users/{email}`, `POST /admin/tokens`,
  `PATCH /admin/users/{email}/profile`) — user registration
  with optional profile data, listing, revocation, token
  issuance, and profile updates with no code.

- **Per-user data storage.** `filesystem` store (default) provides
  per-user JSON under XDG-compliant paths. Custom stores plug in
  via module path. The SDK accesses data through `get_store()`.

- **Typed profile with Pydantic.** Apps declare a profile model
  on the `App` object. Profile data is validated at registration
  and hydrated as a typed object on `current_user.get().profile`.

- **One composition root.** The `App` class declares name, tools
  module, profile model, and store in one place. CLIs (`serve`,
  `stdio`, `connect`, `users`, `tokens`, `health`, `probe`,
  `register`) are derived automatically. The admin CLI generates
  typed flags from the profile model.

- **Free tests for auth, admin, and wiring.** `mcp_app.testing`
  ships test modules that check auth enforcement, user admin, JWT
  handling, CLI wiring, and tool protocol compliance against your
  app. Import them, provide your `App` as a fixture, get 25+ tests.

- **Identity enforced by default.** Every tool is wrapped with
  identity enforcement — if no user is established (HTTP middleware
  didn't run, stdio `--user` wasn't passed), the tool returns an
  error instead of running unauthenticated. You can't accidentally
  ship a wide-open service.

- **Deployable anywhere.** Standard container image, any platform.
  Or use [gapp](https://github.com/echomodel/gapp) for rapid
  deployment to serverless Cloud Run.

**Install:**
```bash
pip install git+https://github.com/echomodel/mcp-app.git
```

### Alternative: FastMCP (manual wiring)

If the user prefers direct control, already has a FastMCP-based
app, or has requirements that mcp-app doesn't cover, use FastMCP
directly with the `mcp` package. The architecture rules (SDK-first,
thin tools, XDG paths) apply equally to both approaches.

**When to suggest FastMCP directly:**
- User explicitly asks for it
- Existing codebase already uses FastMCP and migration isn't wanted
- Need for custom transport or protocol extensions
- stdio-only tool with no deployment plans
- User wants full control over the ASGI middleware stack

## Modes

This skill operates in three modes depending on what the user
needs. Determine the mode from the user's request and the state
of the current working directory.

### Mode 1: Greenfield — Build a New Solution

User wants to create a new MCP server or web API from scratch.

**First, help them decide: local or remote?**

**Local MCP server (stdio)** makes sense when:
- Works with local files, code, git repos, or system config
- Manages the local workstation or development environment
- Needs fast, low-latency interaction
- Single user, single machine

**Remote MCP server (HTTP)** makes sense when:
- Accesses cloud data or external APIs
- Needs to be available from multiple devices
- Needs multi-user support
- Benefits from always-on availability

Based on this, the solution targets stdio only (simpler — no auth,
no deployment) or stdio + HTTP (needs auth, deployment planning).
Both follow the same repo structure.

### Mode 2: Migration — Port an Existing App

1. Check the mcp-app framework version (see below)
2. Read the existing codebase to understand current structure.
   **If deployment config exists** (e.g., `gapp.yaml`,
   Dockerfile, CI config) — do not modify it directly. When
   you reach deployment configuration, invoke the appropriate
   deployment skill if one is available. The runtime contract
   in this skill tells you what the app needs; the deployment
   tool's skill knows how to configure it.
3. **Check for existing auth and credential storage.** If the
   app has its own authentication, token storage, or credential
   management — custom middleware, config files, env vars for
   tokens, auth CLI commands, a deployment tool's auth wrapper
   — migrating to mcp-app **replaces all of it.** mcp-app's
   user profile store IS the credential management system now.
   Flag this to the user:
   - Existing tokens become invalid after migration
   - Existing users need to be re-registered in mcp-app's
     user store via the admin CLI
   - Per-user credentials (API keys, OAuth tokens) are stored
     in mcp-app user profiles, not config files or env vars
   - **Delete the old credential code.** Any custom token
     storage (config files like `~/.config/*/token`, env var
     token discovery, `auth` subcommands, `get_token()`
     helpers) is dead code after migration. Do not create
     fallback chains that check both old and new paths —
     that defeats the purpose of migrating. The SDK reads
     credentials from `current_user.get().profile`, period.
   - MCP clients (Claude.ai, Claude Code, Gemini CLI) will
     need new tokens and possibly updated endpoint URLs
   - Check for existing user data on disk or in cloud storage
     that may need format conversion
   - **If a working remote deployment exists**, connect to it
     with the admin CLI to retrieve existing user credentials
     for local registration. Don't ask the user to manually
     extract tokens from browsers or config files when the
     data is already accessible through the running service.
     Use the deployment tool's skills to discover connection
     details (URL, signing key) if needed.
4. Walk through the Compliance Checklist, noting conformance
5. Propose a migration plan in priority order
6. Execute with the user's approval
7. Run the checklist again to verify

### Mode 3: Review — Evaluate Against Standards

1. Check the mcp-app framework version (see below)
2. Run the Compliance Checklist and present results as a table
3. For each failure, explain what's wrong and the fix

### Checking the mcp-app framework version

For any existing app that already depends on mcp-app, ensure
the installed version is current before proceeding. Check how
the dependency is declared (e.g., in `pyproject.toml`) and
whether it pins a specific version or commit.

If it points to a git URL with no pin (e.g.,
`mcp-app @ git+https://...`), the installed version may be
stale even though the dependency declaration looks correct.
Reinstall to pull the latest:

```bash
pip install -e . --upgrade
```

After upgrading, if `tests/framework/` exists, run it:

```bash
pytest tests/framework/ -v
```

If it passes, the app is compatible with the new version. If
any tests fail, investigate before proceeding — the failure
may indicate an API change the app needs to adapt to.

If `tests/framework/` does not exist, that's a compliance gap
— adopt the framework test suite (see Step 5 in Testing and
Validation).

If the app pins a specific version or commit, confirm with the
user whether they want to update before making changes that
may depend on newer framework features.

## Compliance Checklist

### Structure
- [ ] Three-layer architecture: `sdk/`, `mcp/`, optional `cli/`
- [ ] All business logic in `sdk/`
- [ ] MCP tools are thin (one-liners calling SDK methods)
- [ ] `APP_NAME` constant in `__init__.py`
- [ ] `pyproject.toml` with correct dependencies and entry points

### MCP Server (mcp-app)
- [ ] `App` object declared in `__init__.py` with name and tools_module
- [ ] Tools module contains plain async functions (no decorators)
- [ ] Identity middleware runs by default (no config needed)
- [ ] Tool docstrings are clear and user-centric

### MCP Server (FastMCP — if not using mcp-app)
- [ ] Uses `mcp` package (FastMCP) with `stateless_http=True`
- [ ] DNS rebinding protection disabled for Cloud Run
- [ ] `mcp.run()` for stdio, `app` variable for HTTP (uvicorn)

### User Identity and Profile
- [ ] SDK reads `current_user.get()` for identity — `.email` and `.profile`
- [ ] Profile model declared on `App` if app needs per-user data
- [ ] Profile validated with Pydantic at registration time
- [ ] Per-user data scoping works in both stdio and HTTP modes

### App CLI and Entry Points
- [ ] `App` object with `mcp_cli` and `admin_cli` cached properties
- [ ] Entry points in `pyproject.toml` target `app.mcp_cli` and `app.admin_cli`
- [ ] `mcp_app.apps` entry point group registered
- [ ] Profile model on `App` drives typed admin CLI flags

### Paths and Environment Variables
- [ ] XDG path resolver functions in SDK (data, config, cache)
- [ ] Each resolver checks env var override first, then XDG fallback
- [ ] No hardcoded absolute paths in code
- [ ] `SIGNING_KEY` required for HTTP (no default)

### Testing
- [ ] SDK unit tests in `tests/unit/`
- [ ] Full-stack HTTP tests using httpx ASGI transport
- [ ] No mocks unless needed for network I/O
- [ ] Tests use temp dirs and env vars for isolation
- [ ] mcp-app framework test suite — if `tests/framework/` exists,
  run `pytest tests/framework/ -v`. If it doesn't, set it up
  (see Step 5 in Testing and Validation)

### Documentation
- [ ] README.md with quick start, deployment, config
- [ ] CONTRIBUTING.md with architecture and testing standards
- [ ] CLAUDE.md: `@README.md` and `@CONTRIBUTING.md`
- [ ] `.gemini/settings.json` with context file declarations

### Deployment Readiness
- [ ] Deployable as a standard container image
- [ ] Optionally, `gapp.yaml` for rapid Cloud Run deployment
- [ ] `SIGNING_KEY` set as environment variable (no default)

## Repository Structure

### Single-package (recommended for new apps)

```
my-solution/
  my_solution/
    __init__.py       # APP_NAME, mcp_cli, admin_cli, optional Profile
    sdk/
      core.py         # Business logic — ALL behavior here
    mcp/
      tools.py        # Pure async functions calling SDK
    cli/              # Optional — app-specific Click commands
      main.py
  tests/
    unit/
  pyproject.toml
```

### Multi-package (when SDK, MCP, CLI have different dependencies)

Some apps separate SDK, MCP server, and CLI into independent
installable packages so users only install what they need:

```
my-solution/
  sdk/
    my_solution/      # my-solution-sdk package
      __init__.py     # APP_NAME
      core.py
    pyproject.toml
  mcp/
    my_solution_mcp/  # my-solution-mcp package
      __init__.py     # mcp_cli, admin_cli, optional Profile
      tools.py
    pyproject.toml    # depends on my-solution-sdk, mcp-app
  cli/
    my_solution_cli/  # my-solution package (CLI)
      main.py
    pyproject.toml    # depends on my-solution-sdk
  tests/
```

In multi-package repos, the `App` object goes in the MCP package's
`__init__.py` — that's where mcp-app is a dependency.

### __init__.py — the app's identity

**API-proxy app** (needs per-user credentials):

```python
# my_solution/__init__.py
from pydantic import BaseModel, Field
from mcp_app import App
from my_solution.mcp import tools

class Profile(BaseModel):
    token: str = Field(description="API token from https://example.com/settings")

app = App(
    name="my-solution",
    tools_module=tools,
    profile_model=Profile,
    profile_expand=True,
)
```

**Data-owning app** (no per-user credentials — just identity):

```python
# my_solution/__init__.py
from mcp_app import App
from my_solution.mcp import tools

app = App(
    name="my-solution",
    tools_module=tools,
)
```

No profile model needed. User identity comes from
`current_user.get().email`. App data lives in the store or
however the app manages its own storage.

### pyproject.toml entry points

```toml
[project]
name = "my-solution"
dependencies = ["mcp-app"]

[project.scripts]
my-solution = "my_solution.cli:cli"           # app's own CLI (optional)
my-solution-mcp = "my_solution:app.mcp_cli"   # serve, stdio
my-solution-admin = "my_solution:app.admin_cli" # connect, users, health

[project.entry-points."mcp_app.apps"]
my-solution = "my_solution:app"
```

One `pipx install my-solution` gives three commands. The
`mcp_app.apps` entry point lets framework tooling discover
the app.

### Rules

- **SDK first.** All behavior lives in the SDK. MCP and CLI are
  thin wrappers.
- **No business logic in MCP tools or CLI commands.**
- **If you're writing logic in a tool or command, stop and move it
  to SDK.**
- **Minimize non-business code.** The goal is to write as little
  code as possible that isn't focused on the problem domain. Use
  mcp-app features when they eliminate boilerplate — that's what
  the framework is for. But don't adopt features the app doesn't
  need. Don't adopt features that don't reduce code, configuration,
  or complexity for this specific app. When existing code handles
  concerns that available tooling already covers — auth, user
  management, server bootstrapping, transport, deployment,
  infrastructure — replace it with the tooling. The goal is to
  shed everything that isn't business logic. If the tooling covers
  most but not all of a concern, work with the user on how to
  close the gap rather than keeping a parallel custom
  implementation.

## MCP Server Setup

### With mcp-app (recommended)

No config files. The `App` object wires everything:

```python
# my_solution/__init__.py
from mcp_app import App
from my_solution.mcp import tools

app = App(name="my-solution", tools_module=tools)
```

Tools module — plain async functions that call SDK methods:

```python
# my_solution/mcp/tools.py
from my_solution.sdk.core import MySDK

sdk = MySDK()

async def do_thing(param: str) -> dict:
    """Do the thing for the current user."""
    return sdk.do_thing(param)
```

**Tool discovery:** mcp-app registers all public async functions
in the tools module as MCP tools. Function name → tool name,
docstring → description, type hints → schema. Functions starting
with `_` are skipped.

**Import carefully.** Any async function imported into the tools
module becomes a tool — including SDK functions. Always use a
class-based SDK so tools call `sdk.method()` and SDK methods
stay hidden from discovery.

**SDK has state** (config, file paths, store) — instantiate:
```python
# Data-owning app (e.g., food logger with local storage)
from my_solution.sdk.core import MySDK
sdk = MySDK()  # holds config, paths

async def do_thing(param: str) -> dict:
    """Do the thing."""
    return sdk.do_thing(param)
```

**SDK is stateless** (just wraps an external API) — use the
class as a namespace via classmethods, no pointless instance:
```python
# API-proxy app (e.g., wraps a financial API)
from my_solution.sdk.core import MySDK
sdk = MySDK  # the class itself, not an instance

async def list_items() -> dict:
    """List items."""
    return await sdk.list_items()
```

```python
# my_solution/sdk/core.py
class MySDK:
    @classmethod
    def _client(cls):
        user = current_user.get()
        return MyClient(token=user.profile.token)

    @classmethod
    async def list_items(cls) -> dict:
        client = cls._client()
        return await client.get_items()
```

Both patterns prevent leakage. The class groups methods and
keeps client creation in one place.

**Escape hatch for existing function-based SDKs:** if
refactoring to a class isn't worth it, import with underscore
prefix:
```python
from my_solution.sdk import get_items as _get_items
```

Identity middleware runs automatically in HTTP mode. Store
defaults to filesystem. No configuration unless adding custom
middleware.

**Run:**
```bash
my-solution-mcp serve              # HTTP
my-solution-mcp stdio --user local  # stdio
```

### With FastMCP (alternative)

```python
# my_solution/mcp/server.py
from mcp.server.fastmcp import FastMCP
from my_solution import APP_NAME
from my_solution.sdk.core import MySDK

mcp = FastMCP(APP_NAME, stateless_http=True, json_response=True)
mcp.settings.transport_security.enable_dns_rebinding_protection = False

sdk = MySDK()

@mcp.tool()
async def do_thing(param: str) -> dict:
    """Do the thing."""
    return sdk.do_thing(param)

app = mcp.streamable_http_app()  # For uvicorn HTTP mode

def run_server():
    mcp.run()             # For stdio mode
```

## User Identity and Profile

### How it works

In HTTP mode, identity middleware validates the JWT, loads the full
user record from the store (auth + profile in one read), and sets
`current_user` ContextVar. In stdio mode, the CLI loads the user
record from the store using the `--user` flag.

The SDK reads it:

```python
from mcp_app.context import current_user

user = current_user.get()
user.email       # "alice@example.com" (HTTP) or "local" (stdio)
user.profile     # typed Pydantic model or raw dict
```

### Two app patterns — same framework, different SDK reads

**Data-owning** (owns user data — food logs, notes):

```python
from mcp_app.context import current_user
from mcp_app import get_store

class MySDK:
    def save_entry(self, data):
        user = current_user.get()
        store = get_store()
        store.save(user.email, "entries/today", data)
```

The SDK reads `current_user.get().email` for user identity. How
it stores data is the app's choice — `get_store()` provides
mcp-app's per-user key-value store, but the SDK can also manage
its own storage (XDG paths, custom databases, etc.) using the
email as the scoping key.

**API-proxy** (wraps external API — financial data, task management):

```python
from mcp_app.context import current_user
import httpx

class MySDK:
    def list_items(self):
        user = current_user.get()
        token = user.profile.token  # typed via Pydantic
        resp = httpx.get("https://api.example.com/items",
                         headers={"Authorization": f"Bearer {token}"})
        return resp.json()
```

Both use `current_user.get()`. The middleware is the same (identity
only). The SDK decides what to read from the user context.

### Profile registration

The app declares its per-user profile shape:

```python
# my_solution/__init__.py
from pydantic import BaseModel, Field
from mcp_app import App
from my_solution.mcp import tools

class Profile(BaseModel):
    token: str = Field(description="Personal access token from https://example.com/settings")

app = App(
    name="my-solution",
    tools_module=tools,
    profile_model=Profile,
    profile_expand=True,
)
```

`profile_expand=True` generates typed CLI flags (`--token`).
`profile_expand=False` accepts the profile as a JSON blob or `@file`.
Profile registration happens automatically when the `App` is
constructed — no separate `register_profile()` call needed.

**Field descriptions are the self-documentation mechanism for
API-proxy apps.** The Pydantic model is the single place where
the app author declares what per-user credentials the app needs.
The field name is the app author's choice (`token`, `api_key`,
`github_pat`, `plaid_access_token` — mcp-app doesn't enforce
or assume any naming). The `Field(description=...)` should say
what the credential is, what system it connects to, and where
the operator can obtain it.

This matters because the admin CLI surfaces field names and
descriptions in `--help` output for `users add` and
`users update-profile`. An operator (or agent) managing a
deployed instance discovers what credentials the app needs
by running `my-solution-admin users add --help` — no source
code or documentation needed. This is the re-discovery path:
months later, when a token needs rotating, the CLI tells you
what each field is for.

**When building an API-proxy app, always include
`Field(description=...)` on every profile field.** A bare
`token: str` works mechanically but gives operators nothing
to work with when they encounter the field in a CLI or admin
tool. A good description answers: what is this, what system
does it authenticate to, and where do I get one.

**Propagate this into the implementing app.** When creating or
reviewing an API-proxy app:

1. **Code comment on the Profile class** — explain that field
   descriptions drive CLI help text and are the primary way
   operators discover what credentials the app needs.
2. **CONTRIBUTING.md** — document that profile fields must
   include `Field(description=...)` and what a good description
   looks like. This ensures future contributors maintain the
   self-documentation when adding or changing profile fields.

These are not optional polish — they are the re-discovery
mechanism. Without descriptions, an operator rotating a
credential six months later sees `--token` in `--help` with
no explanation of what token, for what system, or where to
get a new one.

### User management

Each mcp-app solution generates three CLI entry points:

```bash
my-solution              # app's own CLI (optional)
my-solution-mcp serve    # MCP server (HTTP or stdio)
my-solution-admin        # admin: connect, users, tokens, health, probe, register
```

**Always prefer the per-app admin CLI** (`my-solution-admin`)
over the generic CLI (`mcp-app`). The per-app CLI stores its
connection config per app — each app remembers its own target
(local or remote) and signing key in
`~/.config/{name}/setup.json`. This lets you return to an app
in a future session and immediately run admin operations without
re-discovering how or where it was deployed. The generic CLI
stores only one connection at a time — connecting to a different
service overwrites the previous one.

The framework currently tracks one connection per app (a single
deployment environment, whether local or remote). If the same
app is deployed to multiple environments, `connect` switches
between them but only remembers the last one configured.

**At the start of any session involving admin operations**,
verify the current connection before assuming it's correct.
Run `my-solution-admin health` (remote) or
`my-solution-admin users list` (local or remote) to confirm
which target the CLI is pointed at. Don't assume that after
a deploy or local MCP client configuration the admin CLI is
connected to that target — `connect` and `deploy` are
independent operations.

The admin CLI handles user registration, profile updates, token
issuance, revocation, deployment verification, and MCP client
registration for both local and remote instances. The
`mcp-app-admin` skill, if available, covers the full admin
workflow including signing key retrieval from deployment tooling.

**`users add` rejects existing users.** If the user already
exists, `add` fails with an error directing you to
`users update-profile`. This prevents accidental profile
overwrites — especially dangerous for API-proxy apps where the
profile contains backend credentials.

**`users update-profile`** updates individual profile fields
without replacing the entire profile. For apps with
`profile_expand=True`, the key argument is validated against
the Pydantic model's fields:

```bash
# Typed key (expand=True) — key is validated, tab-completable
my-solution-admin users update-profile alice@example.com token new-api-key

# JSON merge (expand=False or no profile model)
my-solution-admin users update-profile alice@example.com '{"token": "new-key"}'
```

Use `update-profile` to rotate backend credentials, refresh
OAuth tokens, or change any per-user setting without
re-registering the user.

### Environment variables

| Var | Required | If Missing | Purpose |
|-----|----------|------------|---------|
| `SIGNING_KEY` | For HTTP | Startup fails | JWT signing key |
| `JWT_AUD` | No | Audience not validated | Expected JWT `aud` claim |
| `APP_USERS_PATH` | No | `~/.local/share/{name}/users/` | Per-user data directory |
| `TOKEN_DURATION_SECONDS` | No | 315360000 (~10yr) | Token lifetime in seconds |

**`SIGNING_KEY`** — a secret. Never commit it to the repo, never
put it in a checked-in config file. Generate a strong random value:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

How the signing key gets into the environment depends on the
deployment tool. Work with the user to determine the right
approach for their setup. Common patterns:

- **CI/CD secrets** — e.g., GitHub Actions secrets injected as
  env vars during deployment
- **Cloud secret managers** — e.g., GCP Secret Manager, AWS
  Secrets Manager, mapped to the env var by the deployment tool
- **Deployment tool generated** — some tools (e.g., Terraform's
  `random_password`) can generate and manage the secret directly

The goal: the secret is stored safely and injected into the
`SIGNING_KEY` env var wherever the server runs. The agent should
guide the user through this for their specific deployment path.

**After deploy, you need the signing key back** to configure the
admin CLI for user management. The deployment tool that created
or stored the secret must provide a way to retrieve it. If you're
using a deployment skill, check whether it has a secrets get/read
command. For example, with gapp: `gapp_secret_get(env_var_name=
"SIGNING_KEY", plaintext=True)`. Without a deployment tool, read
the secret directly from wherever it was stored (cloud secret
manager, CI/CD secrets, etc.).

**`JWT_AUD`** — optional. If unset, audience is not validated and
any valid JWT signed with the same key is accepted. If multiple
apps share the same signing key but do not set `JWT_AUD` (or set
it to the same value), they will accept each other's user tokens.
This may be intentional (shared auth across a suite of apps) or
undesirable (cross-app token leakage). If each app has a unique
signing key, audience validation is less critical. Discuss with
the user and let them decide.

**`APP_USERS_PATH`** — critical for any deployment where the
filesystem is not persistent. The default (`~/.local/share/{name}/users/`)
works on a developer's laptop. In a container, this path is
ephemeral — the app starts, users get registered, tools execute,
and then user data is silently lost on container restart. No error,
no warning. For any persistent deployment, this must point to a
mounted volume or persistent storage path. Make the user aware of
this and confirm the path is durable before considering deployment
complete.

**`TOKEN_DURATION_SECONDS`** — defaults to ~10 years, which
effectively means tokens are permanent. If the user wants tokens
to expire sooner, set this. The value applies to newly issued
tokens only — existing tokens keep their original expiry.

## Testing and Validation

After building the solution, write tests and validate both transports.
This is not optional — do it before the compliance dashboard.

### Step 1: SDK unit tests

Test business logic directly. Set `current_user` and env vars
in fixtures — the SDK reads these at runtime:

```python
import os
import pytest
from mcp_app.context import current_user
from mcp_app.models import UserRecord

@pytest.fixture(autouse=True)
def isolated_env(tmp_path):
    os.environ["MY_SOLUTION_DATA"] = str(tmp_path / "data")
    os.environ["MY_SOLUTION_CONFIG"] = str(tmp_path / "config")
    token = current_user.set(UserRecord(email="test-user"))
    yield
    current_user.reset(token)
    del os.environ["MY_SOLUTION_DATA"]
    del os.environ["MY_SOLUTION_CONFIG"]

def test_saves_entry():
    sdk = MySDK()
    result = sdk.save_entry({"item": "apple"})
    assert result["success"]

def test_multi_user_isolation(tmp_path):
    """Data for different users doesn't mix."""
    token = current_user.set(UserRecord(email="alice@example.com"))
    try:
        sdk = MySDK()
        sdk.save_entry({"item": "apple"})
    finally:
        current_user.reset(token)

    token = current_user.set(UserRecord(email="bob@example.com"))
    try:
        sdk = MySDK()
        sdk.save_entry({"item": "banana"})
    finally:
        current_user.reset(token)
```

### Step 2: Full-stack HTTP validation

Validate the entire ASGI stack in-memory using httpx's ASGI
transport. No server process, no port, no Docker. httpx is a
dependency of mcp-app — the solution gets it for free.

**If it works here, it works in uvicorn, it works in Docker.**

```python
import httpx
import jwt as pyjwt
from datetime import datetime, timezone, timedelta
from mcp_app.bootstrap import build_app

@pytest.fixture
def app_client(tmp_path):
    os.environ["APP_USERS_PATH"] = str(tmp_path / "users")
    os.environ["SIGNING_KEY"] = "test-key"
    app, mcp, store, config = build_app()
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")

@pytest.mark.asyncio
async def test_register_and_call_tool(app_client):
    admin_token = pyjwt.encode(
        {"sub": "admin", "scope": "admin",
         "iat": datetime.now(timezone.utc),
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        "test-key", algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    resp = await app_client.post(
        "/admin/users",
        json={"email": "user@example.com",
              "profile": {"token": "test-api-key"}},
        headers=headers,
    )
    assert resp.status_code == 200
    assert "token" in resp.json()
```

### Step 3: stdio validation

```bash
claude mcp add my-solution -- my-solution-mcp stdio --user local
```

### Step 4: Run tests

```bash
pytest tests/unit/ -v
```

All tests must pass before the compliance dashboard.

### Step 5: mcp-app framework test suite

mcp-app ships reusable tests that check auth enforcement,
user admin, JWT handling, CLI wiring, tool protocol compliance,
and SDK test coverage — against YOUR app. These are the
authoritative verification that the app is correctly built on
the framework.

**Check if `tests/framework/` exists.** If it does, run it:

```bash
pytest tests/framework/ -v
```

If it passes, the app is verified. If it fails, investigate —
the failure is either a real compliance issue or an upstream
bug (check mcp-app's issue tracker).

**If `tests/framework/` does not exist, create it now:**

`tests/framework/conftest.py` — the only file that differs
per app (points at your `App` object):

```python
import pytest
from my_solution import app as my_app

@pytest.fixture(scope="session")
def app():
    return my_app
```

`tests/framework/test_framework.py` — identical across all
mcp-app solutions:

```python
from mcp_app.testing.iam import *
from mcp_app.testing.wiring import *
from mcp_app.testing.tools import *
from mcp_app.testing.health import *
```

Then run:

```bash
pytest tests/framework/ -v
```

Zero failures means: auth works, admin works, tools are wired,
identity is enforced, and the SDK has test coverage for every
tool.

**When to run these tests:**
- After adopting the framework test suite for the first time
- After upgrading mcp-app to a newer version
- After any migration or structural change
- As part of any compliance review

### When to stub

- **Network I/O** — stub HTTP clients, external API calls
- **Cloud CLIs** — mock at the SDK function boundary
- **Everything else** — real code, real files, real config

## Deployment

The solution is a standard Python app. It deploys as a container
or a process on any platform. This section describes what the app
needs from its environment — the runtime contract — and then
covers containerization and deployment routes.

### Running locally

**stdio** — no auth, no signing key. The MCP client launches the
process:
```bash
my-solution-mcp stdio --user local
```

**HTTP** — requires `SIGNING_KEY` at minimum:
```bash
SIGNING_KEY=your-key my-solution-mcp serve
```

With all options:
```bash
SIGNING_KEY=your-key \
APP_USERS_PATH=/data/my-solution/users \
JWT_AUD=my-solution \
TOKEN_DURATION_SECONDS=2592000 \
  my-solution-mcp serve --host 0.0.0.0 --port 8080
```

### Runtime contract

Any deployment target must provide:

- **Start command:** `my-solution-mcp serve` (optionally
  `--host` and `--port`, defaults to `0.0.0.0:8080`).
  This is a CLI command, not an importable ASGI module path.
  mcp-app does not expose a module-level ASGI app variable —
  it builds the ASGI app internally at startup. Deployment
  tools that distinguish between a raw command and an ASGI
  entrypoint must use the command form.
- **Environment variables:** see the environment variables
  section above — at minimum `SIGNING_KEY` (secret) and
  `APP_USERS_PATH` (persistent path) for any durable deployment
- **MCP endpoint path:** `/` (root). mcp-app serves the MCP
  SSE/streamable transport at the root path, not `/mcp`. MCP
  clients connect to `https://host:port/`, not
  `https://host:port/mcp`. If a previous deployment served at
  a different path, client URLs must be updated.
- **Health check:** `GET /health` — no auth required, returns
  `{"status": "ok"}`
- **Admin API:** `POST/GET /admin/users`, `DELETE /admin/users/{email}`,
  `PATCH /admin/users/{email}/profile`, `POST /admin/tokens` —
  all require admin auth via signing key
- **Auth model:** the app handles its own auth via JWT. If the
  platform has its own auth gate (e.g., IAM, API gateway), it
  must allow unauthenticated traffic through to the app
- **Build root:** the repo root where `pyproject.toml` lives

**Docker example:**
```bash
docker build -t my-solution .
docker run -p 8080:8080 \
  -e SIGNING_KEY=your-key \
  -v /persistent/path:/data \
  -e APP_USERS_PATH=/data/users \
  my-solution
```

### Containerizing

If the deployment target needs a container image, add a
Dockerfile to the repo root:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install -e .
EXPOSE 8080
CMD ["my-solution-mcp", "serve"]
```

The build context is the repo root. `pip install -e .` installs
the solution package (which depends on mcp-app). The app listens
on port 8080 by default.

Some deployment tools (e.g., gapp, Cloud Build, Buildpacks)
generate or manage the Dockerfile for you. Check your tool's
documentation before writing one manually.

### Deployment routes

mcp-app does not prescribe a deployment tool. Common options:

- **Bare metal / VPS** — `pip install -e . && my-solution-mcp serve`
  with env vars set in the shell or a process manager
- **Docker** — build the image, run it with `-e SIGNING_KEY=...`
  and a volume mount for `APP_USERS_PATH`
- **Cloud Run / similar** — deploy from source or from a container
  image, set env vars and secrets through the platform
- **gapp** — if you're using the echomodel skill collection,
  there is a deploy skill that handles infrastructure, secrets,
  and data volumes for Cloud Run. Invoke it — it will guide
  through setup, secret configuration, and deployment using
  the runtime contract above.

When using a deployment skill, invoke it now. The runtime
contract, env var requirements, and auth model are already in
your context — map them to the deployment tool's configuration.
After deployment completes, continue below with post-deploy
verification and user management.

Regardless of route, the agent must ensure:
1. `SIGNING_KEY` is sourced from a secrets store or generated by
   the deployment tool — never hardcoded or checked in
2. `APP_USERS_PATH` points to persistent storage — not the
   container's ephemeral filesystem
3. The platform allows unauthenticated HTTP traffic through to
   the app (mcp-app handles auth internally)

### Post-deploy: admin setup, users, and verification

After deployment, the next steps are: retrieve the signing key
from the deployment environment, connect the admin CLI, register
users, verify the deployment end-to-end, and generate MCP client
registration commands. The `mcp-app-admin` skill, if available,
covers this workflow in detail — including how to trace the
signing key through various deployment tools (gapp, Terraform,
cloud secret managers, Docker, CI/CD secrets).

**Quick reference** (see `mcp-app-admin` for full guidance):

```bash
# Connect admin CLI (signing key from your deployment tool)
my-solution-admin connect https://your-service --signing-key xxx

# Probe: health + MCP tools round-trip in one command
my-solution-admin probe

# Register a user
my-solution-admin users add alice@example.com

# Generate MCP client registration commands (mints a token)
my-solution-admin register --user alice@example.com
```

`probe` confirms the deployment is serving tools end-to-end — not
just that the process is alive (`health`), but that the MCP layer
responds with the expected tools. Use it as the single verification
step after any deploy or redeploy.

`register` emits ready-to-paste commands for Claude Code, Gemini
CLI, and the Claude.ai URL form, with the URL and token already
substituted. Both commands support `--json` for structured output
when called from an agent.

## Gitignore

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
build/
dist/
.venv/
venv/
.eggs/

# Environment
.env

# Testing
.pytest_cache/

# Claude Code
.claude/

# Gemini (except settings.json)
.gemini/*
!.gemini/settings.json

# OS
.DS_Store

# Logs
*.log
```

## Documentation

### README.md
Covers: why the repo exists, quick start, deployment, CLI, config.

### CONTRIBUTING.md
Covers: architecture, testing, conventions, how to add features.

### Agent context files

**CLAUDE.md:**
```markdown
@README.md
@CONTRIBUTING.md
```

**`.gemini/settings.json`:**
```json
{
  "context": {
    "fileName": ["README.md", "CONTRIBUTING.md"]
  }
}
```

## Compliance Dashboard

After all testing and validation steps are complete (including
the framework test suite from Step 5), present the dashboard:

```
## Solution Compliance Dashboard: {APP_NAME}

| Category | Item | Status |
|----------|------|--------|
| Structure | SDK layer contains all business logic | ✅ |
| Structure | MCP tools are thin wrappers | ✅ |
| MCP | App object declared | ✅ |
| Identity | current_user accessible, profile typed | ✅ |
| CLI | Entry points for mcp + admin | ✅ |
| Testing | SDK unit tests pass | ✅ |
| Testing | mcp-app test suite passes | ✅ |
| Testing | stdio validated | ✅ |
| Deploy | Dockerfile or gapp.yaml present | ❌ |

✅ = conforms  ❌ = missing/wrong  ⚠️ = partial
```

**The solution is ready when `pytest tests/` passes with zero
failures.** The mcp-app test suite is the authoritative check —
if it passes, auth works, admin works, tools are wired, identity
is enforced, and the SDK has test coverage for every tool.

After presenting the dashboard:

1. If there are ❌ or ⚠️ items: "Want me to fix these?"
2. If all ✅: "This solution is ready for deployment."
