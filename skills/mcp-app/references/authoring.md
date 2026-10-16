# Authoring an mcp-app solution

Read this when building a new solution, migrating an existing server onto
mcp-app, or changing an app's structure, `App` declaration, tools module,
safe tool, or extra HTTP routes. Identity and profile models are in
`identity-and-profile.md`; tests in `testing.md`; the compliance checklist
in `review-checklist.md`.

Contents: framework choice · greenfield: local or remote · migrating an
existing app · repository structure · MCP server setup (tool discovery,
host-path safety, SDK shapes, safe tool, extra HTTP routes, plain MCPServer)

## Framework choice

Two approaches are supported:

### Recommended: mcp-app (config-driven)

[mcp-app](https://github.com/echomodel/mcp-app) is a framework that
wraps the official MCP Python SDK's `MCPServer` (SDK 2.x) and Starlette.
You define tools as plain async functions,
wire up with two lines in Python, and run with one command. No config
files, no framework imports in your tool code.

**What the user gets with mcp-app:**

- **Zero framework code in tools.** Tools are plain async functions.
  No decorators, no MCP SDK imports, no framework coupling in
  business code. mcp-app discovers public async functions from the
  module passed as `tools_module` and registers them automatically —
  function names become tool names, docstrings become descriptions,
  type hints become schemas.

- **User identity and profile.** Identity middleware runs by default
  in HTTP mode — validates the identity provider's access token, loads
  the full user record (auth + profile) in one store read, sets
  `current_user` ContextVar. The SDK reads `current_user.get()` for
  user identity and profile data. Users sign in with the operator's
  identity provider (standard MCP OAuth); the app holds no secret.

- **User management out of the box.** REST admin endpoints
  (`POST /admin/users`, `GET /admin/users`,
  `DELETE /admin/users/{email}`,
  `GET /admin/users/{email}/profile`,
  `PATCH /admin/users/{email}/profile`) — user registration
  with optional profile data, listing, revocation, and profile
  reads/updates with no code. Administrators are the emails in
  `ADMIN_EMAILS`.

- **Per-user data storage.** `filesystem` store (default) provides
  per-user JSON under XDG-compliant paths. Custom stores plug in
  via module path. The SDK accesses data through `get_store()`.

- **Typed profile with Pydantic.** Apps declare a profile model
  on the `App` object. Profile data is validated at registration
  and hydrated as a typed object on `current_user.get().profile`.

- **One composition root.** The `App` class declares name, tools
  module, profile model, and store in one place. CLIs (`serve`,
  `stdio`, `connect`, `users`, `health`, `probe`, `register`) are
  derived automatically. The admin CLI generates
  typed flags from the profile model.

- **Free tests for auth, admin, and wiring.** `mcp_app.testing`
  ships test modules that check auth enforcement, user admin, token
  validation, CLI wiring, and tool protocol compliance against your
  app. Import them, provide your `App` as a fixture, get 25+ tests.

- **Identity enforced by default.** Every tool is wrapped with
  identity enforcement — if no user is established (HTTP middleware
  didn't run, stdio `--user` wasn't passed), the tool returns an
  error instead of running unauthenticated. You can't accidentally
  ship a wide-open service.

- **Deployable anywhere.** Standard container image, any platform.
  Or use [gapp](https://github.com/echomodel/gapp) for rapid
  deployment to serverless Cloud Run.

**Install** (pin a released tag; see `framework-version.md`):
```toml
dependencies = ["mcp-app @ git+https://github.com/echomodel/mcp-app.git@vX.Y.Z"]
```

### Alternative: MCPServer (manual wiring)

If the user prefers direct control, already has an app on the SDK's
`MCPServer` (or 1.x `FastMCP`), or has requirements that mcp-app
doesn't cover, use `MCPServer` directly with the `mcp` package. The architecture rules (SDK-first,
thin tools, XDG paths) apply equally to both approaches.

**When to suggest MCPServer directly:**
- User explicitly asks for it
- Existing codebase already uses MCPServer and migration isn't wanted
- Need for custom transport or protocol extensions
- stdio-only tool with no deployment plans
- User wants full control over the ASGI middleware stack

## Greenfield: local or remote?

For a new server, first help the user decide where it runs.

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
Both follow the same repo structure. A stdio-only server with no store, no
identity needs, and no plans for HTTP may not need mcp-app at all: plain
plain MCPServer is simpler (see the end of this file). Say so and let the user
choose.

## Migrating an existing app

1. Check the mcp-app framework version (`framework-version.md`)
2. Read the existing codebase to understand current structure.
   **If deployment config exists** (e.g., Dockerfile, CI
   workflows, `.tf` files, deployment-tool configs) — do not
   modify it directly. When
   you reach deployment configuration, invoke the appropriate
   deployment skill if one is available. `runtime-contract.md`
   says what the app needs; the deployment tool's skill knows
   how to configure it.
3. **Check for existing auth and credential storage.** If the
   app has its own authentication, token storage, or credential
   management — custom middleware, config files, env vars for
   tokens, auth CLI commands, a deployment tool's auth wrapper
   — migrating to mcp-app **replaces all of it.** mcp-app's
   user profile store IS the credential management system now.
   Flag this to the user:
   - Existing tokens become invalid after migration; users sign
     in with the identity provider from their MCP client instead
   - Existing users need to be re-registered in mcp-app's
     user store (`operate.md`, `auth.md`)
   - Per-user credentials (API keys, OAuth tokens) are stored
     in mcp-app user profiles, not config files or env vars
   - **Delete the old credential code.** Any custom token
     storage (config files like `~/.config/*/token`, env var
     token discovery, `auth` subcommands, `get_token()`
     helpers) is dead code after migration. Do not create
     fallback chains that check both old and new paths —
     that defeats the purpose of migrating. The SDK reads
     credentials from `current_user.get().profile`, period.
   - MCP clients (Claude.ai, Claude Code, Antigravity CLI) will
     need to re-add the server by URL (no token) and possibly
     updated endpoint URLs
   - Check for existing user data on disk or in cloud storage
     that may need format conversion
   - **If a working remote deployment exists**, read its user
     list and profiles through `/admin` (with an administrator's
     token, `auth.md`) rather than asking the user to extract
     credentials from browsers or config files by hand. Use the
     deployment tool's skills to discover the URL if needed.
4. Walk through the compliance checklist (`review-checklist.md`), noting conformance
5. Propose a migration plan in priority order
6. Execute with the user's approval
7. Run the checklist again to verify
8. Close out the session as `SKILL.md` describes.


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
    api_key: str = Field(description="API key from https://example.com/settings")

app = App(
    name="my-solution",
    tools_module=tools,
    profile_model=Profile,
    profile_expand=True,
)
```

The field name `api_key` here is illustrative — profile is whatever
the app declares. A data-owning app might instead store user
preferences (`display_name`, `default_region`, etc.) on the profile,
or skip the profile entirely if it has nothing per-user beyond
identity.

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
dependencies = ["mcp-app @ git+https://github.com/echomodel/mcp-app.git@vX.Y.Z"]

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

**File uploads & host-path inputs (MANDATORY for any file tool).**
A tool that reads a file path the *caller* supplies is safe over **stdio**
— the process runs as the local user, so reading their own files is no
privilege escalation — but is an **arbitrary server-side file read over
HTTP**, where the deployed server is multi-tenant and reachable by untrusted
callers. With the public source + a known data-volume layout, a caller can
name `/proc/self/environ` (the process env, with whatever credentials the
SDK holds) or another user's data file, have the server read it, and
exfiltrate it (e.g. by attaching it to a record they control). That is
**cross-tenant disclosure.**

Rules for any tool that ingests a file:

- **The HTTP surface never reads a server-side path from client input.**
  Accept the file as **bytes** (`content_base64`) for small payloads, or
  hand back an **out-of-band upload URL** the client PUTs to for large ones.
- **Host-path convenience is stdio-only.** If you want a "read this local
  path" affordance, put it in a **separate** tool annotated
  `@mcp_transport("stdio")` (the framework then never registers it on the
  HTTP server), or keep it in the CLI/provider layer, which runs as the OS
  user.
- **Model "attach a file" as two tools**, not one with a `path` arg over HTTP:

  ```python
  from mcp_app import mcp_transport

  async def attach_file(record_id: str, content_base64: str) -> dict:
      """Attach a file (base64 bytes). Safe on every transport."""
      ...

  @mcp_transport("stdio")
  async def attach_local_file(record_id: str, path: str) -> dict:
      """Attach a file by local path — stdio only (runs as the local user)."""
      ...
  ```

- **Do not gate by a Cloud-specific env var** (e.g. `K_SERVICE`): it's
  Cloud-Run-only and *fails open* on other hosts. Use `@mcp_transport`, or
  `from mcp_app import is_stdio` for a runtime check (fail-closed: false over
  HTTP and before startup).

The framework reports the transport and honors `@mcp_transport`; it does not
infer which inputs are sensitive — declaring that is your job as the author.

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
        return MyClient(api_key=user.profile.api_key)

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

**Tool docstrings are operator-facing.** The docstring and type
hints on each tool function drive what `tools show <name>`
displays in the admin CLI — not just what an MCP-client agent
sees. Authors writing tool docstrings are now writing operator
help content too. Be specific and concise.

**Run:**
```bash
my-solution-mcp serve              # HTTP
my-solution-mcp stdio --user local  # stdio
```

### Declaring a safe tool for smoke testing

Each app may optionally declare ONE safe, read-only, low-PII
tool that the admin CLI can invoke for an end-to-end smoke
test (`my-solution-admin safe-tool --invoke`). This becomes the
canonical "deeper than probe" check — exercising the
solution-specific tool wiring, the upstream credential, and the
response shape, without relying on a human or agent to read
user-authored content.

```python
from mcp_app import App, SafeTool
from my_solution.mcp import tools

app = App(
    name="my-solution",
    tools_module=tools,
    safe_tool=SafeTool(
        name="count_items",
        arguments={},
        description="returns the number of configured items in the user's account",
    ),
)
```

`safe_tool` is **optional**. The framework treats "no safe tool
declared" as a fully supported state — `probe` is still
available and the admin CLI's `safe-tool` command surfaces a
structured "not declared" envelope.

#### What makes a tool "safe"

The defining property is **low information density about the
user**. A response identical for every user of the same product
is ideal. A response that varies per user only along impersonal
axes (counts, configuration enums, public reference data) is
acceptable. A response containing content the user themselves
authored is not.

In priority order:

1. **Pure counts** — `{"count": 9}`. Safest by far. Strong fit
   even for products whose normal responses are highly personal.
2. **System enums / fixed taxonomies** — labels the platform
   defines, not labels the user created (e.g., a fixed set of
   built-in role names or system-defined statuses).
3. **Identifier-only listings** — opaque IDs the user didn't
   type (UUIDs, content hashes, internal numeric IDs), with no
   names, labels, or other user-authored fields.
4. **Mixed / partial** — a list where each item exposes only a
   system-derived subset (creation timestamp range bucket,
   record type, state). Acceptable only when the subset itself
   isn't identifying.

Anti-patterns:

- Names, labels, subjects, descriptions the user wrote.
- "Last N items" or "items from the last N days" — these reveal
  recency patterns and often the most-recent items themselves.
- Free-text fields the user could have typed arbitrary content into.
- Tools whose response shape depends on the user's data in a
  way that leaks configuration choices.

If no existing tool fits cleanly, the right move is often to
**add a small dedicated tool exclusively for this purpose**:

- `count_<entity>() -> {"count": N}`
- `health() -> {"status": "ok", "upstream_reachable": true}` if
  the framework's `/health` doesn't already cover the upstream.
- A flag on an existing tool that downgrades the response to
  counts/IDs only.

This is a legitimate and explicitly blessed pattern. A
purpose-built safe tool is generally better than reusing a tool
that returns more than the smoke test needs.

#### The `description` field

Short, app-provided, plain English. This is the field the admin
CLI surfaces in the envelope and the human-readable output. It
is intentionally separate from the MCP-side tool description —
which is written for an agent consuming the tool list and may
be more revealing than is appropriate for an admin smoke-test
artifact. Write the safe-tool description for an operator
deciding whether to invoke it.

#### Opting out

If no candidate is appropriately safe and adding one isn't
worth it for the solution's risk profile, leave `safe_tool`
unset and rely on `probe`. The framework treats this as a
normal, supported configuration. The choice is the author's.

### Extra HTTP routes — an out-of-band data plane

MCP tool responses cannot carry large binary payloads: clients
cap how much a single tool result holds, and under HTTP transport
the agent and server don't share a filesystem, so a server-local
path is unreachable from the agent. When an app must move bytes
bigger than an inline tool response allows (large file
upload/download, generated reports, media), it contributes its own
HTTP routes via the `App.extra_routes` field and the bytes travel
out-of-band of the MCP response.

```python
# my_solution/__init__.py
from starlette.responses import StreamingResponse
from starlette.routing import Route
from mcp_app import App
from my_solution.mcp import tools
from my_solution.sdk.core import MySDK

sdk = MySDK()

async def download(request):
    sdk.verify_signed_url(request.url)        # 403 on bad/expired signature
    return StreamingResponse(sdk.stream(request.path_params["file_id"]))

app = App(
    name="my-solution",
    tools_module=tools,
    extra_routes=[Route("/files/{file_id}", download)],
)
```

Rules:

- **The framework does not authenticate these routes.** Unlike the
  MCP endpoint and `/admin` (token-gated), `extra_routes` are mounted
  un-wrapped — each route owns its own auth, like the public
  `/health` route. This is deliberate: an out-of-band fetch usually
  carries no access token (the token lives in the MCP client, not in
  the agent's hands), so the URL itself must be the credential. The
  canonical pattern is a **self-authorizing signed URL**: an MCP tool
  mints a short-lived URL signed with a secret the app owns (mcp-app
  holds none to lend it; a per-app env var, or a key generated at
  startup if URLs are short-lived and the service runs one instance),
  the agent fetches it with a plain `curl`/GET, and the route handler
  verifies the signature before streaming. No agent-held credential,
  bounded blast radius.
- **Routing precedence:** routes mount after `/health` and `/admin`,
  before the MCP catch-all at `/`. They take precedence over MCP but
  cannot shadow the framework's own endpoints.
- **Thin handlers (SDK-first):** signature verification, streaming,
  and chunking live in the SDK. The route handler parses the
  request, calls the SDK, and returns a response.
- **Zero cost when unused:** `extra_routes` defaults to `None`. Apps
  that don't need it pass nothing and get the standard three-route
  stack with no new imports and no behavior change. Starlette is
  already a transitive dependency of every mcp-app app, so using
  `extra_routes` only means importing the `Route`/`Mount`/response
  types you build the routes with.
- **HTTP only:** stdio mode has no ASGI layer, so `extra_routes`
  applies to HTTP serving. A CLI on the same machine reads local
  files directly and doesn't need the data plane.

Keep the inline path too — small payloads (and tool-only MCP
clients that can't perform an out-of-band fetch) still use an
inline content block / base64 argument. The data-plane routes are
the large-payload path, not a replacement for inline.

### With MCPServer (alternative)

```python
# my_solution/mcp/server.py
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from my_solution import APP_NAME
from my_solution.sdk.core import MySDK

mcp = MCPServer(APP_NAME)

sdk = MySDK()

@mcp.tool()
async def do_thing(param: str) -> dict:
    """Do the thing."""
    return sdk.do_thing(param)

app = mcp.streamable_http_app(  # For uvicorn HTTP mode
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    ),
)

def run_server():
    mcp.run()             # For stdio mode
```

