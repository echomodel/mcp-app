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
- **Persistence verification at startup.** Every server start
  logs the resolved data directory, its filesystem type, and
  free space. Set one env var and the process refuses to come
  up if the data dir is on the wrong filesystem — so a misconfigured
  volume mount can't silently route writes to ephemeral storage.
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
from pydantic import BaseModel, Field
from mcp_app import App
from my_app.mcp import tools

class Profile(BaseModel):
    api_key: str = Field(description="API key from https://example.com/settings")

app = App(
    name="my-app",
    tools_module=tools,
    profile_model=Profile,
    profile_expand=True,
)
```

`profile_expand=True` generates typed CLI flags (`--api-key`) on
the admin CLI. `profile_expand=False` (default) accepts profile
as JSON or `@file`.

The `Field(description=...)` is important — it appears in `--help`
output for both `users add` and `users update-profile`. An operator
or agent managing a deployed instance discovers what credentials the
app needs by running `my-app-admin users add --help`. The
description should say what the credential is, where to get it,
and what system it connects to. The field name itself
(`token`, `api_key`, `github_pat`, etc.) is the app author's
choice — mcp-app does not enforce or assume any naming convention.

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
env var. Custom store backends can be passed to `App`. See
[Data storage](#data-storage) for the full storage contract,
the startup `data_dir` log line, and the optional
`REQUIRED_FS_TYPE` assertion.

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
        api_key = user.profile["api_key"]
        resp = httpx.get("https://api.example.com/items",
                         headers={"Authorization": f"Bearer {api_key}"})
        return resp.json()
```

The SDK reads `current_user.get().profile` for whatever it needs. The profile was saved at registration time and loaded in one read with the auth record.

**What's identical:** store setup, admin endpoints, tool discovery, deployment. The middleware is the same. The SDK decides what to read from the user context.

### Tool Discovery

The `tools` module is imported and all public async functions (not starting with `_`) are registered as MCP tools. Function names become tool names. Docstrings become descriptions. Type hints become schemas.

## Environment Variables

| Variable | Required | If Missing | Purpose |
|----------|----------|------------|---------|
| `SIGNING_KEY` | For HTTP | Startup fails | JWT signing key |
| `JWT_AUD` | No | Audience not validated | Expected JWT `aud` claim |
| `APP_USERS_PATH` | No | `~/.local/share/{name}/users/` | Per-user data directory |
| `REQUIRED_FS_TYPE` | No | No assertion | Opt-in startup assertion that the data dir lives on a specific filesystem type. See [Data storage](#data-storage). |
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

**`REQUIRED_FS_TYPE`** — opt-in startup assertion. See [Data storage](#data-storage).

## Data storage

mcp-app's default `FileSystemUserDataStore` writes per-user data
under a single root directory. The path resolves with this
precedence:

1. `APP_USERS_PATH` env var, if set.
2. `${XDG_DATA_HOME}/{app-name}/users/`, with `XDG_DATA_HOME`
   defaulting to `~/.local/share`.

**Storage contract.** Anything mcp-app writes for a user lives
under this root. The directory must be a durable location in any
non-ephemeral deployment. In a container without a mounted volume
the path resolves to the container's overlay filesystem — writes
look fine, the app appears healthy, and every record disappears
when the container restarts. There is no warning.

### Startup data_dir log line

On every server start (HTTP or stdio) mcp-app emits one
`logger.info` line under the `mcp_app.startup` logger summarizing
the resolved data directory:

```
INFO mcp_app.startup data_dir path=/var/lib/my-app/users exists=true writable=true fs_type=fuse.gcsfuse free_bytes=137438953472 required_fs_type=<unset>
```

Fields:

| Field | Meaning |
|-------|---------|
| `path` | Resolved absolute path (post-`APP_USERS_PATH`/XDG resolution). |
| `exists` | Whether the path exists after startup. mcp-app creates it if missing. |
| `writable` | Result of a sentinel write+delete in the path. |
| `fs_type` | Filesystem type as reported by the OS. `unknown` if the platform doesn't expose it. |
| `free_bytes` | Free space in bytes from `statvfs`. `-1` if unavailable. |
| `required_fs_type` | Value of `REQUIRED_FS_TYPE`, or `<unset>`. |

The log line is plain facts — no policy. An operator (or a
log-scraping monitor) decides what's acceptable.

#### `fs_type` interpretation

mcp-app reports the raw string from the OS. Common values an
operator should recognize:

| `fs_type` | What it means |
|-----------|---------------|
| `fuse`, `fuse.gcsfuse`, `nfs`, `smbfs`, `cifs` | Mounted network or object storage — durable. |
| `overlay`, `overlayfs` | Container ephemeral layer — **writes here vanish on restart**. |
| `ext4`, `xfs`, `apfs`, `btrfs`, `zfs`, `hfs` | Local disk — durable. |
| `tmpfs` | In-memory — lost on restart. |
| `unknown` | Platform doesn't expose fs type or detection failed. |

### Optional `REQUIRED_FS_TYPE` assertion

Set `REQUIRED_FS_TYPE` to opt into a startup assertion. mcp-app
compares it against the actual `fs_type` and either records the
match or aborts the process.

| `REQUIRED_FS_TYPE` state | `fs_type` matches? | Behavior |
|--------------------------|--------------------|----------|
| Unset (or empty)         | n/a                | `logger.debug` notes the assertion was skipped. The `data_dir` info line shows `required_fs_type=<unset>`. |
| Set                      | Yes                | `logger.info` emits one combined line including `fs_type_check=ok`. |
| Set                      | No, or path missing/not writable | `logger.error` emits one combined line including `fs_type_check=mismatch` (or `path_missing`/`not_writable`). The process exits non-zero so the broken revision never serves traffic. |

**Matching semantics.** The value is matched as a comma-separated
list, prefix-friendly on `.` boundaries:

- `fuse` matches `fuse` and `fuse.gcsfuse` (prefix on `.`).
- `fuse,nfs` matches either.
- `apfs` matches only `apfs` exactly.
- Whitespace around commas is ignored. Empty entries are skipped.

The default behavior (unset) is unchanged from earlier versions —
local development, laptops, CI, and any deployment that doesn't
care are not affected.

**Why opt-in.** mcp-app cannot know whether ephemeral storage is
intended. `overlayfs` is correct on a developer laptop using
Docker for iteration; it's a data-loss bug on a production
deployment that was supposed to mount a volume. The framework
reports facts and lets the operator declare what's acceptable.

**Why always log `required_fs_type`, even when unset.** A single
line shows whether the assertion was wired up. If a deployment is
*supposed* to be setting `REQUIRED_FS_TYPE` and the line shows
`<unset>`, the wiring is broken — visible immediately, no second
log line needed.

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

The user record includes an optional `profile` field — whatever
per-user data the app wants to attach: backend credentials,
preferences, configuration, defaults. mcp-app stores it and loads
it but does not interpret it. There is no "profile schema" at
the framework level — each app declares its own.

For typed profile access, the app declares a Pydantic model on
the `App` object. A credential-bearing example for an API-proxy
app:

```python
class Profile(BaseModel):
    api_key: str = Field(description="API key from https://example.com/settings")

app = App(name="my-app", tools_module=tools, profile_model=Profile, profile_expand=True)
```

A non-credential example for a data-owning app that wants per-user
preferences:

```python
class Profile(BaseModel):
    display_name: str = Field(description="Name shown on shared content")
    default_region: str = Field(description="Region for new entries, e.g. 'us-east'")

app = App(name="my-app", tools_module=tools, profile_model=Profile, profile_expand=True)
```

Both shapes are equally valid — same machinery, different content.
`user.profile.api_key` or `user.profile.display_name` is typed
and validated. If no model is registered, `user.profile` is a
raw dict.

**Field descriptions are how the app tells operators (and agents)
what each field is for.** When `profile_expand=True`, the admin
CLI generates typed flags from the model — the field name becomes
the flag, the description becomes the help text. An operator
running `my-app-admin users add --help` sees exactly what to
provide and where to get it, without reading the source code.
This is the re-discovery mechanism: months later, when a value
needs updating, the CLI tells you what each field is for.

### User registration with profile

```bash
# No profile needed
my-app-admin users add alice@example.com

# Profile set at registration via typed flags (whatever the model declares)
my-app-admin users add alice@example.com --api-key xxx-yyy-zzz
my-app-admin users add bob@example.com --display-name "Bob" --default-region us-east

# Update a single profile field later
my-app-admin users update-profile alice@example.com api_key new-key
my-app-admin users update-profile bob@example.com default_region eu-west

# Read the current profile (e.g., to verify what's stored)
my-app-admin users get-profile alice@example.com
```

`users add` rejects existing users — use `users update-profile`
to change credentials for a user that's already registered.

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
- `GET /admin/users/{email}/profile` — read a user's profile
- `PATCH /admin/users/{email}/profile` — merge fields into a user's profile
- `DELETE /admin/users/{email}` — revoke user
- `POST /admin/tokens` — issue new token for existing user
- `GET /admin/safe-tool` — return the deployment's safe-tool declaration
  (or a structured "not declared" envelope)

Gated by admin-scoped JWT (`scope: "admin"`, same signing key).

### Safe tool

Each app may optionally declare ONE safe, read-only, low-PII tool the
admin CLI can invoke for an end-to-end smoke test. This becomes the
canonical "deeper than probe" check, both for human operators and
agent-driven validation that should not see user content.

```python
from mcp_app import App, SafeTool

app = App(
    name="my-app",
    tools_module=tools,
    safe_tool=SafeTool(
        name="count_items",
        arguments={},
        description="returns the number of configured items",
    ),
)
```

`safe_tool` is optional. The defining property is *low information
density about the user* — counts, system enums, opaque IDs, never
content the user authored. The framework treats "no safe tool
declared" as a fully supported state. See `mcp_app.SafeTool` for the
full guidance.

The CLI command `<my-app>-admin safe-tool [--invoke] [--json]` shows
or runs the declaration. The `/admin/safe-tool` endpoint carries
metadata only — the CLI does the MCP handshake itself, avoiding
duplication of MCP transport logic on the server. The structured
envelope is versioned (`schema_version: "1"`) and additive-only;
consumers must tolerate unknown fields.

### Tools subcommand group

Every admin CLI inherits a `tools` subcommand group for ad-hoc
discovery and invocation against the connected deployment:

```bash
my-app-admin tools list                        # enumerate
my-app-admin tools show <name>                 # schema + example
my-app-admin tools call <name> --arg k=v       # invoke with scalars
my-app-admin tools call <name> --body '<json>' # invoke with full args
```

The tools shown are exactly the tools the solution registered via its
tools module — no separate declaration needed. `safe-tool` curates,
`tools` enumerates; both serve different operators in different
moments.

## Local Testing

Validate the full stack in-memory — no server, no Docker, no cloud:

```python
from my_app import app
import httpx

transport = httpx.ASGITransport(app=app)
client = httpx.AsyncClient(transport=transport, base_url="http://test")
```

`App` is directly ASGI-callable, so any ASGI host — httpx in-process,
uvicorn, hypercorn, granian, Mangum for Lambda — treats it as the
server callable without wrapping. If it works here, it works in
Docker. httpx is already a dependency of mcp-app.

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

**This posture is inherited.** Apps built on mcp-app are
deployment-agnostic by default. When authoring your app's own
README, describe what the app needs from any environment — env
vars, start command, endpoint paths, auth model — and let the
reader's deployment tooling map to it. Docker is a useful
universal illustration; specific platforms (Cloud Run, ECS,
Kubernetes) should only appear in your docs if the app is
deliberately coupled to one. Concrete values tied to a
deployment (signing-key secret names, `APP_USERS_PATH` paths,
orchestration details) belong in the deployment tooling's
domain, not the app's README. This is how the same app can be
picked up and deployed anywhere without its docs arguing with
the operator's choice.

### Where deployment config lives under the agnostic route

When the app is deployment-agnostic, the deployment decisions
and configuration live *separately* from the app repo — in
CI/CD workflows, ops repos, infrastructure-as-code modules, or
wherever environment-specific (but non-secret) settings, build
scripts, and deployment tooling belong. The app repo stays
focused on the app. Operators bring their own deployment
tooling, and agentic workflows operating on a deployment
environment will typically have additional skills or plugins
loaded for *that* tooling, separate from the app itself.

Some of the connective tissue is retained across sessions by
the mcp-app admin CLI. Per-app `connect` config persists the
deployed URL and signing-key access for each app, so returning
to administer an app months later doesn't require
re-discovering how or where it was deployed. This state lives
in XDG config paths (`~/.config/{app-name}/setup.json`) —
always outside the solution app repo — where it can be managed
and versioned by a dotfile manager or lifted into a separate,
private operator-owned repo if durability beyond the
workstation is needed. Either way, it stays external to the
solution app repo. Capabilities here may expand over time —
additional metadata about a deployment (environments, aliases,
deployment tool hints) could reasonably accrue to this per-app
config, still in external locations not versioned with or
exposed in the repo itself as a reusable product.

### The opinionated-tooling alternative

A secondary route — not required by mcp-app — is to ship
opinionated build and deployment tooling *inside* the app repo:
Dockerfiles beyond a minimal illustration, CI workflow
templates, Terraform modules (`.tf` files) or other
infrastructure-as-code, platform-specific manifests, or configs
for a particular deployment tool. Done well, this tooling is
still
*operator-agnostic*: environment specifics (project IDs,
secret names, domains) and secrets stay out of the repo; the
configs describe how to build and deploy without dictating
where. The goal is to give operators an easy, opinionated path
— batteries included rather than assembly required.

This route trades some portability for convenience. Apps
published as **reusable public products** commonly avoid it,
or include only a minimal Docker example, to maximize audience
and adoption — any in-repo tooling assumption is one more thing
a would-be user has to agree with or work around. Apps that
are **internal, personal, or have a narrower audience** may
reasonably include more opinionated tooling, on the theory that
the authors and operators are closely aligned and the
convenience is worth it. Both are valid — the choice is the
author's.

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
  `/admin/users/{email}` (DELETE), `/admin/users/{email}/profile`
  (GET, PATCH), `/admin/tokens` (POST)
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

**1. Connect** the admin CLI:
```bash
my-app-admin connect https://your-service --signing-key xxx
```

**2. Register a user** (if none exist yet):
```bash
my-app-admin users add alice@example.com
```

**3. Probe** — single-command end-to-end verification:
```bash
my-app-admin probe
```

Output:
```
URL: https://your-service
Health: healthy
MCP: ok (probed as alice@example.com)
Tools (3):
  do_thing
  list_items
  get_status
```

Probe hits `/health` for liveness, then does an MCP `tools/list`
round-trip using a short-lived token minted for an existing user.
If it reports all tools, the app is fully operational — health,
admin auth, user auth, MCP layer, and tool wiring all work.

**4. Inspect what tools the deployment exposes:**
```bash
my-app-admin tools list
my-app-admin tools show <name>
```

`tools list` enumerates the tools the solution registered. `tools
show <name>` renders the schema and a copy-pasteable invocation
example. Useful as a sanity check that the tools module loaded and
the names match expectations.

**5. End-to-end smoke test (if the app declared a safe tool):**
```bash
my-app-admin safe-tool --invoke
```

Confirms the full stack — framework + solution-specific tool wiring
+ upstream credential + response shape. The JSON-RPC request body
is printed before the call so you can copy and replay it from a
debugger or another terminal.

| `probe` | `safe-tool --invoke` | Likely problem |
|---|---|---|
| ❌ | n/a | Framework layer (network, signing key, MCP transport) |
| ✅ | `supported: false` | No safe tool declared. Rely on probe, or declare one. |
| ✅ | non-200 status | Solution-specific tool failed. Inspect `result.body`. |
| ✅ | 200 but empty/missing | Tool wired but upstream credential invalid/expired. |
| ✅ | 200 with expected shape | Full stack verified. Done. |

**6. Debug a specific tool with custom arguments:**
```bash
my-app-admin tools call <name> --arg k=v
my-app-admin tools call <name> --body '{"k": "v"}'
```

Use when `safe-tool --invoke` failed and you want to isolate the
issue, or when no safe tool is declared and you want a real
round-trip. The output includes the wire-level request body so
you can replay it manually.

**7. Generate MCP client registration commands:**
```bash
my-app-admin register --user alice@example.com
```

This outputs ready-to-paste commands for Claude Code, Gemini
CLI, and the Claude.ai URL form.

## User Management

### Connect

**Prefer the per-app admin CLI** (`my-app-admin`) over the
generic CLI (`mcp-app`) whenever possible. The per-app CLI
stores connection config per app — each app remembers its own
target (local or remote) and signing key independently in
`~/.config/{name}/setup.json`. This means you can switch between
administering different apps without losing connection state,
and return to an app months later without re-discovering how or
where it was deployed.

The generic CLI stores one connection at a time in
`~/.config/mcp-app/setup.json`. Connecting to a different
service overwrites the previous connection. It exists for cases
where the per-app admin CLI isn't installed locally.

```bash
# Per-app admin CLI (preferred) — local or remote
my-app-admin connect local
my-app-admin connect https://your-service --signing-key xxx

# Generic CLI — remote only, single connection
mcp-app connect https://your-service --signing-key xxx
```

`connect local` is only available on the per-app admin CLI
because it needs the app name to locate the filesystem store
(`~/.local/share/{name}/users/`). The generic CLI doesn't know
which app it's managing, so it only supports remote targets.

Connection config is set once and never repeated. No other
command accepts `--url` or `--signing-key`.

**Note:** the framework currently tracks one connection per app
— a single deployment environment (local or remote), not
multiple environments. If you deploy the same app to staging
and production, `connect` switches between them but only
remembers the last one configured.

### Managing users

```bash
# Register users (profile fields are app-specific — see the app's Pydantic model)
my-app-admin users add alice@example.com
my-app-admin users add bob@example.com --profile '{"api_key": "xxx-yyy-zzz"}'

# List users
my-app-admin users list

# Read a user's profile
my-app-admin users get-profile alice@example.com

# Update a single profile field
my-app-admin users update-profile alice@example.com api_key new-key

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

## Skill installation and usage

Two agent skills ship with this repo under `skills/`:

- **[`author-mcp-app`](skills/author-mcp-app/SKILL.md)** —
  guides authoring, migration, review, and framework-upgrade
  work on mcp-app solutions.
- **[`mcp-app-admin`](skills/mcp-app-admin/SKILL.md)** — guides
  operators and agents managing deployed mcp-app instances
  (connect, verify, users, tokens, MCP client registration).

### Installing the skills

Install as symlinks from a local clone so edits in the repo
go live immediately:

```bash
# Claude Code — user scope
ln -s $(pwd)/skills/author-mcp-app  ~/.claude/skills/author-mcp-app
ln -s $(pwd)/skills/mcp-app-admin   ~/.claude/skills/mcp-app-admin

# Gemini CLI — link from local clone
gemini skills link ./skills/author-mcp-app
gemini skills link ./skills/mcp-app-admin
```

Install method may vary by agent platform; follow the
established pattern in your environment.

### When to invoke

**`author-mcp-app`** is for lifecycle events on a solution
repo, not for steady-state work:

- **Initial authoring** of a new mcp-app solution (greenfield).
- **Periodic review** of an existing solution against the
  current framework — produces a compliance dashboard.
- **Framework upgrades** or migrations to adopt new features
  or replace deprecated patterns.

**`mcp-app-admin`** is for operational work on a deployed
instance — connecting the admin CLI, verifying the
deployment, managing users, rotating credentials, registering
MCP clients. Invoke it alongside whatever deployment-tool
skill (if any) is in use.

### Design goal: self-obsolescence for the solution repo

The processes these skills describe — authoring, reviewing,
upgrading, deploying, redeploying, administering — are all
inherently recurring. The admin process in particular runs
continuously across the lifetime of a deployed app
(redeploys, user additions, credential rotations, client
registrations). That work never becomes obsolete.

What *can* become obsolete, per solution repo, are the
**skills as agent-guidance artifacts**. `author-mcp-app` is
designed — when `mcp-app-admin` and any other relevant
accelerator skills are available in the environment at
authoring time — to absorb their guidance into the solution
repo's own `README.md`, `CONTRIBUTING.md`, and agent context
files (`CLAUDE.md`, `.gemini/settings.json`) in app-specific
and often more concrete terms than the skills themselves can
offer. The solution repo's docs end up carrying the complete
end-to-end process — authoring AND operating — expressed in
the app's real CLI names, real profile fields, real
deployment posture.

Once the author skill has completed that pass, a future
agent opening the solution repo with **neither skill loaded**
must be able to install, run, deploy, redeploy, connect the
admin CLI, manage users, rotate credentials, register MCP
clients, add or modify tools, and run tests, entirely from
the repo's own files. Neither skill is needed for ongoing
work on that specific repo.

The skills remain broadly useful:

- **`author-mcp-app`** — for lifecycle events on any repo
  (initial authoring, periodic review, framework upgrade),
  or on repos that haven't been brought under this discipline
  yet.
- **`mcp-app-admin`** — for operational work on instances
  whose repos don't have the admin journey fully documented
  (legacy apps, third-party apps, or any solution that
  skipped the author skill's pass), and as a cross-cutting
  reference that tracks framework evolution before any one
  repo's docs catch up.

The bar the author skill holds itself to: if it ran on this
repo successfully, neither skill should be required the next
time someone (human or agent) opens the repo to do normal
work on it.

### The three-stage lifecycle and where deployment fits

An mcp-app solution moves through three stages from working
tree to operating service:

1. **Author** — write, structure, and locally validate the
   solution's code. Owned by `author-mcp-app`.
2. **Deploy** — turn the validated working tree into a
   reachable URL that passes a minimal health check (`GET
   /health` returns `{"status": "ok"}`). **Owned by neither
   mcp-app skill.** This is intentionally external. The
   *operator* — the human running the deploy, or the agent
   environment standing in for them — chooses the route,
   using whatever deployment tooling, skills, plugins,
   scripts, or context that environment brings. A solution
   *may* prescribe a particular mechanism (e.g., a Dockerfile
   plus opinionated CI workflows in the repo), but it need
   not, and echomodel first-party solutions deliberately do
   not. The mcp-app skills require only that this stage
   exists in some form and yields a healthy URL.
3. **Operate** — connect the admin CLI, verify the deployment
   end-to-end, manage users, rotate credentials, register MCP
   clients, troubleshoot. Owned by `mcp-app-admin`. Assumes
   stage 2 already produced a healthy URL.

**Where stage-2 guidance comes from.** Because mcp-app
deliberately does not own the deploy step, an agent reaching
the author → deploy boundary looks for guidance in (in order):

1. **The operator's agent environment** — a deployment skill
   or plugin loaded for the cloud platform, container
   orchestrator, or deployment automation the operator uses;
   any global or user-level context (e.g., agent context
   files) that describes how this operator deploys mcp-app
   solutions. This is the primary source for solutions that
   don't prescribe deployment, and it's where first-party
   echomodel deployments live.
2. **The solution's own repo** — if the app prescribes a
   deployment route, it documents that in `CONTRIBUTING.md`,
   `CLAUDE.md`, `README.md`, or via in-repo scripts with
   documented usage. Most solutions don't and shouldn't, but
   some legitimately do.
3. **The user.** If neither (1) nor (2) yields a clear path,
   the agent asks. It does not improvise with raw cloud CLI
   commands, ad-hoc `curl` calls, or guessed credentials.
   Absence of stage-2 guidance is a signal that the
   environment has not been set up for agent-driven deploys
   on this solution, and the user must direct the next step.

The guidance — wherever it comes from — must let the agent:

- Initiate or trigger deployment with the chosen tooling.
- Discover the URL of an existing or freshly-produced
  deployment.
- Confirm the URL passes the minimal `/health` check before
  handing off to `mcp-app-admin`.

**Implementing apps should recommend installing both
mcp-app skills, and pairing with a deployment route.** A
short footer in the app's README pointing at
`author-mcp-app`, `mcp-app-admin`, and a note that the
operator's environment must supply a deployment route (a
skill, a plugin, or documented manual steps) tells a
returning operator how the lifecycle is meant to fit
together. The skills themselves are not prerequisites — the
app's docs must be self-sufficient — but when both skills are
loaded *and* a deployment route is arranged, the agent moves
through the lifecycle with much less prompting.

**Why this split.** mcp-app aspires to a clean separation:
the framework opinions stop at the runtime contract, and
deployment opinions live with the operator. Folding the
deploy step into either skill would couple the framework to a
specific deployment posture, defeating the agnostic-by-default
goal — and pushing it onto each implementing app would force
every solution to carry deployment opinions it doesn't
otherwise need. The skills coordinate the boundaries
(`author-mcp-app` decides when authoring is "done";
`mcp-app-admin` decides what counts as a verified operating
instance) but neither owns what happens between them.

## Further Reading

- [docs/custom-middleware.md](docs/custom-middleware.md) — advanced middleware configuration
- [CONTRIBUTING.md](CONTRIBUTING.md) — architecture, design decisions, testing
