# mcp-app

Framework for building and running MCP servers as HTTP services.
Define tools as pure Python functions, wire up with two lines, run
with one command.

## Why mcp-app

The MCP SDK's `MCPServer` is great for quickly spinning up a local tool. But as soon
as you want to productize it, share it with others, or use it across
multiple identities, you end up building auth, user management, admin
endpoints, and deployment config into each app. They all invariably
get done a little differently.

When you're moving at the speed of agents — building and releasing
impactful tools quickly — you need them to be consistent and secure
without repeating boilerplate into each one and trying to manage all
the implementations. You want to scale impact instead of adding to
the cognitive load needed to keep deploying and trusting you'll be
able to come back and rotate a credential or add a user months later.

mcp-app gives you:

- **Identity enforced by default.** Standard MCP authorization runs
  automatically: users sign in with your identity provider, and
  tools can't execute without an established user. You can't
  accidentally ship a wide-open service, and you hold no secret.
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

The consistency is the point. User management, credential rotation,
auth enforcement, admin CLI — these work the same way across all your
solutions. Learn it once, the tests confirm it works, and when you
need to rotate a credential or revoke a user six months later, the
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
the bearer token against the identity provider's keys, loads the
full user record from the store, and sets the `current_user`
ContextVar. No configuration beyond the issuer is needed.

See [docs/custom-middleware.md](docs/custom-middleware.md) for
advanced middleware configuration.

### Authentication

HTTP callers authenticate with standard MCP authorization. mcp-app is
an OAuth 2.1 *resource server*: an external authorization server (an
identity provider, typically fronting Sign in with Google) signs the
user in and issues the access token. mcp-app never sees a password
and holds no signing secret. Per request it validates the token's
signature against the issuer's published keys (JWKS), checks `iss`,
`aud` and `exp`, reads the email claim, and loads that user's record.
The outcomes a client sees:

- **No token, or an invalid one** → `401` with
  `WWW-Authenticate: Bearer ... resource_metadata="<url>"`. A standard
  client follows that pointer to
  `/.well-known/oauth-protected-resource`, learns the issuer, and
  starts the sign-in flow. The document is public.
- **Valid token, email not registered** → `403` and no challenge.
  The identity is established; the service just isn't open to it.
- **Valid token, registered email** → the request runs with
  `current_user` set.
- **Valid token, email in `ADMIN_EMAILS`** → admitted even if not yet
  registered; the record is created on first sign-in. This is how a
  fresh deployment bootstraps without `users add`.

The token is read from the `Authorization` header only. The
`?token=` query form is not accepted.

**Configuration is the issuer and the administrators**, nothing
more. `AUTH_ISSUER` names the authorization server; `ADMIN_EMAILS`
names who may call `/admin`. Everything about *this* server — its
public URL, and therefore the audience a token must carry and the
`resource` it advertises — is derived from each request's `Host`
header. On any front door that routes by hostname (Cloud Run, a
Kubernetes ingress, an API gateway, a reverse proxy) that header is
the same fact that delivered the request, so there is nothing to
configure and nothing to drift. `serve` honors the front door's
`X-Forwarded-Proto`, so the derived URL is `https` behind TLS
termination. `AUTH_AUDIENCE` pins the audience for the rare
deployment reached by address rather than by name, or one answering
on several hostnames; see [Environment
Variables](#environment-variables).

**What the operator sets up at the issuer** (provider UIs differ):

1. An API (resource) whose identifier is the server's public URL,
   exactly as users type it, trailing slash included. Refresh
   tokens ("offline access") on.
2. Sign in with Google as the login method; password login off.
3. Dynamic client registration enabled, or client ID metadata
   documents supported, so MCP clients register themselves with the
   server URL alone. `<issuer>/.well-known/oauth-authorization-server`
   must list a `registration_endpoint` (or advertise CIMD) and
   `S256` under `code_challenge_methods_supported`.
4. The user's email included in access tokens. If the issuer
   namespaces custom claims, set `AUTH_EMAIL_CLAIM` to the full claim
   name.
5. If the issuer needs a default audience to issue JWT (not opaque)
   access tokens when a client sends `resource` rather than
   `audience`, set it to the API identifier.

The same configuration can be pinned in code. The environment
variables exist so one build can be parameterized per deployment
without a code change:

```python
from mcp_app import App, OAuthResourceServer

app = App(
    name="my-app",
    tools_module=tools,
    auth=OAuthResourceServer(
        issuer="https://login.example.com/",
        email_claim="https://example.com/email",
    ),
)
```

`stdio` ignores all of this: identity there is the `--user` flag.

### Extra routes (custom data plane)

MCP tool responses are the wrong place for large binary payloads —
clients cap how much a single tool result can carry, and under HTTP
transport the agent and server don't share a filesystem, so a
server-local path is unreachable. When an app needs to move bytes
larger than an inline tool response allows, it contributes its own
HTTP routes via `extra_routes` and lets agents transfer the bytes
out-of-band of the MCP response:

```python
# my_app/__init__.py
from starlette.responses import StreamingResponse
from starlette.routing import Route
from mcp_app import App
from my_app.mcp import tools
from my_app.sdk.core import MySDK

sdk = MySDK()

async def download(request):
    # The app owns this route's auth. A common pattern is a
    # self-authorizing signed URL: an MCP tool mints a short-lived
    # URL signed with a secret the app holds, the agent fetches it
    # with a plain GET, and this handler verifies the signature.
    file_id = request.path_params["file_id"]
    sdk.verify_signed_url(request.url)          # 403 on bad/expired sig
    return StreamingResponse(sdk.stream(file_id))

app = App(
    name="my-app",
    tools_module=tools,
    extra_routes=[Route("/files/{file_id}", download)],
)
```

How it behaves:

- Routes are mounted **after** `/health` and `/admin` and **before**
  the MCP catch-all at `/`, so they take precedence over MCP but
  cannot shadow the framework's own endpoints.
- The framework does **not** wrap them in identity middleware —
  each route owns its auth, exactly like the public `/health` route.
  This is deliberate: an out-of-band data plane is typically reached
  by a fetch that carries no access token, so the URL itself must be
  the credential (e.g. a signed-URL scheme verified in the handler).
- `extra_routes` defaults to `None`. Apps that don't need it pass
  nothing and get the standard three-route stack unchanged — no new
  imports, no behavior change. (Starlette is already a dependency of
  every mcp-app app; using `extra_routes` just means importing the
  `Route`/`Mount`/response types you already build with.)
- stdio mode has no ASGI layer, so `extra_routes` applies to HTTP
  serving only.

Keep handlers thin (SDK-first): signature verification, streaming,
and any chunking belong in the SDK, not the route handler.

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

### Transport-scoped tools (`@mcp_transport`)

By default a tool is registered on **both** transports. To restrict one,
annotate it:

```python
from mcp_app import mcp_transport

@mcp_transport("stdio")          # registered ONLY over stdio
async def attach_local_file(transaction_id: str, path: str) -> dict:
    """Attach a file the local user names by path."""
    ...
```

A transport-restricted tool is **never registered on the other transport** —
it isn't advertised to those clients at all (no misleading schema entry, no
runtime rejection). `@mcp_transport("http")` is also supported.

**Why this exists — host paths and HTTP.** A tool that reads a file path the
*caller* names is safe over **stdio** (the process runs as the local user, so
reading their own files is no escalation) but is an **arbitrary server-file
read over HTTP**, where the server is reachable by untrusted callers and holds
other users' data and process secrets (`/proc/self/environ`, the user-data
volume). **A deployed (HTTP) MCP tool must never read a server-side path from
client input.** Accept the bytes (`content_base64`) or hand back an
out-of-band upload URL the client PUTs to; keep host-path reads in a separate
tool annotated `@mcp_transport("stdio")` (or in the CLI). Model "attach a
file" as two tools: a bytes/URL tool (all transports) + a host-path tool
(stdio only).

The active transport is also exposed as a fact for finer-grained checks:

```python
from mcp_app import is_stdio, get_transport

is_stdio()        # True only over stdio; False over HTTP and before startup (fail-closed)
get_transport()   # "stdio" | "http" | None
```

The framework **reports** the transport and **honors** `@mcp_transport` at
registration; it does not otherwise infer which inputs are sensitive — that
declaration is the tool author's (see the [mcp-app skill](skills/mcp-app/SKILL.md)).

## Environment Variables

mcp-app reads its configuration from the environment so one build can
be parameterized per deployment. Three variables configure a
production HTTP deployment; the rest are overrides for unusual
setups. None of them is a secret: mcp-app holds no signing key, the
identity provider does.

| Variable | Required | If Missing | Purpose |
|----------|----------|------------|---------|
| `AUTH_ISSUER` | For HTTP | Startup fails | The authorization server's issuer identifier, exactly as in the token's `iss` claim (trailing slash included if the issuer uses one). See [Authentication](#authentication). |
| `ADMIN_EMAILS` | For HTTP | No administrators; startup warns | Comma-separated emails that may call `/admin`. Each is also admitted as a user on first sign-in. |
| `APP_USERS_PATH` | No | `~/.local/share/{name}/users/` | Per-user data directory |
| `AUTH_AUDIENCE` | No | Derived from the request `Host` | Value the token's `aud` claim must contain. Set only for a deployment reached by address rather than hostname, or one answering on several hostnames. |
| `AUTH_EMAIL_CLAIM` | No | `email` | Claim carrying the user's email (namespaced issuers: the full claim name) |
| `AUTH_JWKS_URI` | No | OpenID discovery | Where to fetch the issuer's signing keys, if discovery is unavailable |
| `REQUIRED_FS_TYPE` | No | No assertion | Opt-in startup assertion that the data dir lives on a specific filesystem type. See [Data storage](#data-storage). |

**`AUTH_ISSUER`** must match the token's `iss` claim byte for byte; a
missing or extra trailing slash is the usual mistake. The startup
log's `mcp_app.startup auth` line echoes what the server is using.

**`ADMIN_EMAILS`** is the whole admin model. Nothing is stored, there
is no promotion path, and changing the set is a redeploy. Compared
lower-cased. With it empty the server starts and serves registered
users, but nobody can call `/admin` or bootstrap the first user, so
startup logs a warning.

**`AUTH_AUDIENCE`** — by default the audience a token must carry is
the URL the request arrived at, which is the API identifier the
operator registered at the issuer, so a token issued for one mcp-app
server is refused by another. Pin it when the derived URL is wrong:
the server is reached by IP, or several hostnames route to it. The
exposure of leaving it derived on a hostname-routed platform is
small and bounded: an attacker would already need a user's valid
token *and* a way to route it to this server under a different
hostname, and token lifetime bounds the window.

**`APP_USERS_PATH`** — the default writes to the local filesystem,
which works for development. In a container, this path is ephemeral
— the app starts, users get registered, tools execute, and then
user data is silently lost on container restart. No error, no
warning. For any persistent deployment, set `APP_USERS_PATH` to a
mounted volume or persistent storage path.

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
| HTTP (`my-app-mcp serve`) | Identity middleware validates the issuer-signed bearer token, loads the full user record from the store |
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

- `POST /admin/users` — register user (with optional profile); returns
  `{"email", "registered": true}`
- `GET /admin/users` — list users
- `GET /admin/users/{email}/profile` — read a user's profile
- `PATCH /admin/users/{email}/profile` — merge fields into a user's profile
- `DELETE /admin/users/{email}` — revoke user
- `GET /admin/safe-tool` — return the deployment's safe-tool declaration
  (or a structured "not declared" envelope)
- `GET /admin/health` — full health diagnostic detail (paths, fs_type,
  free bytes, mount source) that the public `/health` intentionally
  omits. See [Health endpoint](#health-endpoint).

They accept the identity provider's access token for an email listed
in `ADMIN_EMAILS` — the same kind of token an MCP client obtains for
that user. mcp-app issues no tokens of its own, so there is no token
endpoint: the authorization server issues every token, and
`DELETE /admin/users/{email}` is the access control on this side.

**Reaching `/admin` on a deployment.** The admin CLI runs every
`users` command against the local store (`connect local`). Against a
deployment it does not yet sign in, so remote `users`, `tools` and
`safe-tool` commands exit with a message saying so; a signed-in
remote mode is planned. Until then an administrator drives `/admin`
on a deployment with their own access token from the identity
provider (`curl -H "Authorization: Bearer <token>"`), and the common
case — the operator is the first user — needs no admin call at all,
because an `ADMIN_EMAILS` entry is admitted on first sign-in.

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

## Health endpoint

`GET /health` returns a structured response that platform health
checks (Cloud Run readiness, Kubernetes liveness, uptime monitors)
can act on. It requires no auth.

```json
{
  "status": "healthy",
  "checks": {
    "persistent_storage": "verified"
  }
}
```

### Status enum

| `status` | HTTP code | Meaning |
|----------|-----------|---------|
| `healthy`   | 200 | All declared checks passing. |
| `degraded`  | 200 | Concern surfaced (e.g., `unverified` storage); safe to serve. |
| `unhealthy` | 503 | A required check failed; deflect traffic. |

The 503 mapping is what makes a structurally broken revision actually
get pulled out of rotation by the platform. Without it, /health would
be cosmetic.

### checks.persistent_storage

| Value | Meaning |
|-------|---------|
| `verified` | `REQUIRED_FS_TYPE` was set, the actual filesystem matched, and the data path is writable. |
| `unverified` | `REQUIRED_FS_TYPE` was not set; the framework deliberately did not assert the filesystem. Normal for development. |
| `unavailable` | The check failed — fs_type mismatch with `REQUIRED_FS_TYPE`, missing path, or not writable. Drives `unhealthy` and HTTP 503. |

`unhealthy` only fires when an operator opted into `REQUIRED_FS_TYPE`
and the contract was violated. Without that opt-in the framework
cannot know whether ephemeral storage was intended (it's normal on a
dev laptop), so the worst it produces is `degraded`. See
[Data storage](#data-storage) for `REQUIRED_FS_TYPE`.

### Identity-free public response

The public response carries the verdict only — never the resolved
path, the actual `fs_type`, the expected `REQUIRED_FS_TYPE` value,
free bytes, mount source, or any other identifying detail.

Identifying detail leaks the deployment shape (storage technology,
cloud provider, mount layout) to anyone who can reach `/health`,
which is unauthenticated. Operators who need the underlying detail
use the admin surface or the startup logs.

### Admin surface for full detail

`GET /admin/health` (an administrator's token) returns the full diagnostic:

```json
{
  "status": "unhealthy",
  "http_status": 503,
  "checks": {"persistent_storage": "unavailable"},
  "details": {
    "persistent_storage": {
      "path": "/var/lib/my-app/users",
      "exists": true,
      "writable": true,
      "fs_type": "overlay",
      "free_bytes": 1234567,
      "required_fs_type": "fuse",
      "fs_type_check": "mismatch",
      "mount_source": "overlay"
    }
  }
}
```

Use this when `/health` reports `degraded` or `unhealthy` and you
need to know why without consulting startup logs.

### Adding a check (for framework contributors)

Future checks land in `mcp_app.health_check`:

1. Define the check's enum (its own value domain — describing the
   contract, not the mechanism).
2. Add the entry to `_STORAGE_CHECK_TO_PUBLIC` (or analogous map).
3. Document its aggregation rule (what produces `unhealthy` vs
   `degraded`).
4. Add the test coverage at the same time, including an
   identity-free assertion on the public payload.

The public response shape never changes — new checks add a new key
to the `checks` object.

### Migration from `{"status": "ok"}`

Earlier versions returned `{"status": "ok"}`. The new shape is the
shape — there is no compatibility shim. Consumers that pattern-matched
the literal `"ok"` should match against `status in ("healthy",
"degraded")` for "should I send traffic" semantics, which is the
boundary the framework itself uses for HTTP 200 vs 503.

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

No auth, no identity provider, no server process. The MCP client
launches the process directly:

```bash
my-app-mcp stdio --user local
```

`--user` is required — it specifies which user record to load from
the store. Refuses to start without it.

### HTTP (multi-user)

```bash
AUTH_ISSUER=https://login.example.com/ \
ADMIN_EMAILS=you@example.com \
  my-app-mcp serve
```

With persistent storage:

```bash
AUTH_ISSUER=https://login.example.com/ \
ADMIN_EMAILS=you@example.com,ops@example.com \
APP_USERS_PATH=/data/my-app/users \
  my-app-mcp serve --host 0.0.0.0 --port 8080
```

Runs uvicorn on `0.0.0.0:8080` by default. Override with `--host`
and `--port`. `serve` honors `X-Forwarded-Proto` from the front
door, so behind TLS termination the server knows its public URL is
`https`.

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
deployment (the issuer URL, `APP_USERS_PATH` paths,
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
deployed URL for each app, so returning
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
- **`AUTH_ISSUER` and `ADMIN_EMAILS` env vars** — the identity
  provider and the administrators. Neither is a secret; mcp-app
  holds no key (see Environment Variables above)
- **`APP_USERS_PATH` env var** — must point to persistent storage
  for any durable deployment. The default writes to the local
  filesystem, which is ephemeral in containers (see Environment
  Variables above)
- **MCP endpoint:** `/` (root path). MCP clients connect to
  `https://host:port/`, not `/mcp`
- **Discovery:** `GET /.well-known/oauth-protected-resource` — no
  auth; MCP clients read it to find the issuer
- **Health check:** `GET /health` — no auth, returns
  `{"status": "healthy" | "degraded" | "unhealthy", "checks": {...}}`
- **Admin API:** `/admin/users` (POST, GET),
  `/admin/users/{email}` (DELETE), `/admin/users/{email}/profile`
  (GET, PATCH), `/admin/safe-tool` (GET), `/admin/health` (GET)
- **Auth model:** mcp-app validates the identity provider's tokens
  itself. If the platform has an auth gate (IAM, API gateway, etc.),
  configure it to pass unauthenticated traffic through to the app
  and to forward the `Host` header unchanged — the public URL and
  token audience derive from it
- **Build root:** the repo root where `pyproject.toml` lives

### Bare metal

```bash
pip install -e .
AUTH_ISSUER=https://login.example.com/ ADMIN_EMAILS=you@example.com my-app-mcp serve
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
  -e AUTH_ISSUER=https://login.example.com/ \
  -e ADMIN_EMAILS=you@example.com \
  -v /persistent/path:/data \
  -e APP_USERS_PATH=/data/users \
  my-app
```

The Dockerfile works on any container platform. The volume mount
ensures user data survives container restarts.

### Cloud platforms

Deploy from source or a container image using your platform's
tooling. Set `AUTH_ISSUER` and `ADMIN_EMAILS` as plain environment
variables and `APP_USERS_PATH` to a persistent volume. Ensure the
platform allows unauthenticated HTTP traffic through to the app.
Register the service's public URL as the API identifier at the
identity provider (see [Authentication](#authentication)).

Deployment tools like [gapp](https://github.com/echomodel/gapp)
can automate infrastructure, volumes, and container builds.

### Post-deploy verification

**1. Connect** the admin CLI to the URL:
```bash
my-app-admin connect https://your-service
```

It saves the URL and prints the deployment's endpoints (MCP, admin,
discovery, health). No credential is involved.

**2. Probe** — confirm the front door without signing in:
```bash
my-app-admin probe
```

Output:
```
URL: https://your-service
  Endpoints:
    MCP        https://your-service/           JSON-RPC, bearer token from the identity provider
    Admin      https://your-service/admin/*    admin REST, an administrator's token
    Discovery  https://your-service/.well-known/oauth-protected-resource  public
    Health     https://your-service/health     public
Health: healthy
OAuth: ok — issuer https://login.example.com/, resource https://your-service/
  Unauthenticated requests get the 401 challenge; an MCP client can
  discover the issuer and sign the user in. Add the URL in a client to go further.
```

Probe hits `/health`, reads the discovery document, and checks that
an unauthenticated MCP request gets the `401` challenge pointing at
it. If all three pass, the framework layer is up and an MCP client
can sign a user in. `resource` must be the URL users type; if it
isn't, the front door is rewriting `Host` — fix the proxy, or pin
`AUTH_AUDIENCE`.

**3. Sign in as the administrator.** Generate the registration
commands for your MCP client and run the one for yours:
```bash
my-app-admin register
```

It outputs the commands for Claude Code and Antigravity CLI (`agy`)
and the URL to add in Claude.ai; none carries a credential. The
client discovers the issuer from the URL, sends you to sign in, and
your `ADMIN_EMAILS` entry is admitted on first use. Call a tool.
That is the end-to-end check: identity provider, token validation,
user record, MCP layer, and tool wiring all work.

**4. Register other users** — see [User Management](#user-management).
They sign in the same way, with their own account.

## User Management

### Who can sign in

Three kinds of email reach a deployment:

- **Administrators** (`ADMIN_EMAILS`): admitted on first sign-in,
  record created automatically, may call `/admin`.
- **Registered users**: anyone an administrator has registered via
  `POST /admin/users`, with an optional profile.
- **Everyone else**: the identity provider signs them in, mcp-app
  answers `403`.

Revoking a user deletes the record; the next request with their
token is a `403`. Re-registering admits them again.

### Connect

**Prefer the per-app admin CLI** (`my-app-admin`) over the
generic CLI (`mcp-app`) whenever possible. The per-app CLI
stores connection config per app — each app remembers its own
target (local or remote) independently in
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
my-app-admin connect https://your-service
my-app-admin connect local     # switch to the local store; the remote stays saved
my-app-admin connect remote    # switch back to the saved remote

# Generic CLI — remote only, single connection
mcp-app connect https://your-service
```

`connect` takes a URL and nothing else: there is no key to supply.
Switching to `local` keeps the saved remote URL, so `connect remote`
returns to it.

`connect local` is only available on the per-app admin CLI
because it needs the app name to locate the filesystem store
(`~/.local/share/{name}/users/`). The generic CLI doesn't know
which app it's managing, so it only supports remote targets.

Connection config is set once and never repeated. No other
command accepts `--url`.

**Note:** the framework tracks one saved remote per app plus the
local store. If you deploy the same app to staging and production,
connecting to one replaces the saved remote for the other.

### App-specific admin commands

Apps can add their own commands to the per-app admin CLI with
`app.admin_cli.add_command(...)`. To read or write users on the target
selected by `connect` — exactly where the built-in `users` commands do —
use the public helpers:

```python
from mcp_app import admin_store, admin_target

store = admin_store("my-app")        # local store or remote adapter
target = admin_target("my-app")      # "local" or "remote"
# ... await store.update_profile(email, {...}) ...
# remote adapters hold an HTTP client: await store.aclose() when done
```

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

# Revoke a user (their next request is a 403)
my-app-admin users revoke alice@example.com

# Health check (remote only)
my-app-admin health
```

These commands run against the local store after `connect local`.
Against a deployment the CLI does not yet sign in, so the remote
forms exit with a message to that effect (see [Admin
Endpoints](#admin-endpoints) for how `/admin` is reached today).
No command prints a token: a user's credential is the sign-in their
MCP client performs with the identity provider.

## MCP Client Configuration

### stdio (local)

No identity provider involved — stdio has no auth; `--user` names the local record.

**CLI registration:**
```bash
claude mcp add my-app -- my-app-mcp stdio --user local
agy mcp add my-app -- my-app-mcp stdio --user local
```

**Manual config** (`~/.claude.json`, or agy's `~/.gemini/config/mcp_config.json`):
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

The client needs the URL and nothing else. On first use it reads the
discovery document, registers itself with the identity provider, and
signs the user in. `my-app-admin register` prints exactly these
forms for the connected deployment.

**CLI registration:**
```bash
claude mcp add --transport http -s user my-app https://your-service/

# agy: one user-level config, no scopes
agy mcp add my-app https://your-service/
```

**Manual config** (`~/.claude.json` shown; agy's `~/.gemini/config/mcp_config.json`
uses the same layout but names the URL key `serverUrl`):
```json
{
  "mcpServers": {
    "my-app": {
      "url": "https://your-service/"
    }
  }
}
```

**Claude.ai / Claude mobile:** Settings → Connectors → Add custom
connector, with the URL:
```
https://your-service/
```

Remote MCP servers added through Claude.ai are available across
all Claude clients — web, mobile, and Claude Code. No token ever
appears in a config file; the client holds what the identity
provider issued and refreshes it itself.

## Architecture

mcp-app wraps `MCPServer` from the [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) (2.x; the class was named `FastMCP` in SDK 1.x) and [Starlette](https://www.starlette.io/) (ASGI framework). Solutions never import these directly — mcp-app handles all wiring.

```
App(name="my-app", tools_module=tools)
    → discovers async functions in tools module
    → registers each as an MCPServer tool (with identity enforcement)
    → creates data store from app name
    → HTTP (serve): wraps with identity middleware + admin endpoints → uvicorn
    → stdio (--user): loads user record from store → MCPServer over stdin/stdout
```

## Free Tests for Your App

mcp-app ships reusable test modules that check auth, user admin,
token validation, CLI wiring, and tool protocol compliance against
your specific app. They run against a stand-in identity provider
(`mcp_app.testing.issuer.TestIssuer`), so no real issuer and no
network is involved. Import them in two files, provide your `App`
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

One agent skill ships with this repo:
**[`mcp-app`](skills/mcp-app/SKILL.md)**. It guides agents through
the whole life of an app built on this framework: authoring,
migration, review, framework upgrades, testing, the deploy
boundary, and operating a deployed instance (connect, verify,
users, MCP client registration, troubleshooting).

The skill follows the [agentskills.io](https://agentskills.io)
format with progressive disclosure. `SKILL.md` is short: a fit
check, the rules that hold in every task, the lifecycle, and a
routing table. Detail lives one level down in
`skills/mcp-app/references/`, and an agent reads only the file its
task needs. All auth-model material is isolated in
`references/auth.md`.

### Installing the skill

Use one channel per machine; installing the same skill two ways
makes it appear twice.

```bash
# Claude app (claude.ai, desktop, mobile): save it to your account
# as a .skill bundle. Build the bundle from a clean checkout:
cd skills && zip -r ../mcp-app.skill mcp-app -x '*.DS_Store'
# then open the .skill file with the Claude desktop app, or save it from a
# file card in a Claude conversation.
# Skills saved to the account also reach the desktop app's Code tab.

# Claude Code CLI, user scope: symlink from a local clone so edits
# go live immediately
ln -s $(pwd)/skills/mcp-app ~/.claude/skills/mcp-app

# Antigravity CLI (agy): symlink into its skills folder. Run from inside
# that folder with a path relative to it, so the link holds no absolute path:
cd ~/.gemini/config/skills
ln -s <relative-path-to-clone>/skills/mcp-app mcp-app

# Gemini CLI
gemini skills link <path-to-clone>/skills/mcp-app
```

### When it activates

The description is deliberately broad: it fires on most work on an
MCP server project, and on symptoms such as a 401 or tools not
listed. The first thing the skill does is check fit. It steps aside
silently for non-Python servers, stdio-only servers with no hosting
plans, client-side configuration, and projects on another framework
when no migration or major new scope is in play. It continues for
apps already on mcp-app, for new servers, and for major new scope
such as adding hosting, multi-user, or auth.

### Design goal: the solution repo outgrows the skill

Authoring, reviewing, upgrading, deploying, redeploying, and
administering recur for the life of an app; that work never becomes
obsolete. What *can* become unnecessary, per solution repo, is the
skill. An authoring or review pass must leave the solution repo's
own `README.md`, `CONTRIBUTING.md`, and agent context files
(`CLAUDE.md`, `AGENTS.md`) carrying the complete process, authoring
and operating, in the app's real CLI names, real profile fields, and
real deployment posture.

After that pass, an agent opening the solution repo with **no skill
loaded** must be able to install, run, deploy, redeploy, connect the
admin CLI, manage users, rotate credentials, register MCP clients,
add or modify tools, and run tests from the repo's own files.

The skill stays useful for lifecycle events on any repo, for repos
not yet brought under this discipline, for operating instances whose
repos don't document the admin journey, and as a reference that
tracks framework changes before any one repo's docs catch up.

### The three-stage lifecycle and where deployment fits

An mcp-app solution moves through three stages from working
tree to operating service:

1. **Author**: write, structure, and locally validate the
   solution's code. Covered by the skill.
2. **Deploy**: turn the validated working tree into a reachable
   URL whose `GET /health` reports `healthy` or `degraded`.
   **Not owned by mcp-app or its skill.** This is intentionally
   external. The *operator* (the human running the deploy, or
   the agent environment standing in for them) chooses the
   route, using whatever deployment tooling, skills, plugins,
   scripts, or context that environment brings. A solution
   *may* prescribe a particular mechanism (e.g., a Dockerfile
   plus opinionated CI workflows in the repo), but it need
   not, and echomodel first-party solutions deliberately do
   not. The skill requires only that this stage exists in some
   form and yields a healthy URL.
3. **Operate**: connect the admin CLI, verify the deployment
   end-to-end, manage users, rotate credentials, register MCP
   clients, troubleshoot. Covered by the skill. Assumes stage 2
   already produced a healthy URL.

**Where stage-2 guidance comes from.** Because mcp-app
deliberately does not own the deploy step, an agent reaching
the author → deploy boundary looks for guidance in (in order):

1. **The operator's agent environment**: a deployment skill
   or plugin loaded for the cloud platform, container
   orchestrator, or deployment automation the operator uses;
   any global or user-level context (e.g., agent context
   files) that describes how this operator deploys mcp-app
   solutions. This is the primary source for solutions that
   don't prescribe deployment, and it's where first-party
   echomodel deployments live.
2. **The solution's own repo**: if the app prescribes a
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

The guidance, wherever it comes from, must let the agent:

- Initiate or trigger deployment with the chosen tooling.
- Discover the URL of an existing or freshly-produced
  deployment.
- Confirm the URL passes the `/health` check before moving
  on to the operate stage.

**Implementing apps should recommend the skill and pair it with
a deployment route.** A short footer in the app's README pointing
at the `mcp-app` skill, plus a note that the operator's
environment must supply a deployment route (a skill, a plugin,
or documented manual steps), tells a returning operator how the
lifecycle fits together. The skill is not a prerequisite (the
app's docs must be self-sufficient), but when it is loaded *and*
a deployment route is arranged, the agent moves through the
lifecycle with much less prompting.

**Why this split.** mcp-app aspires to a clean separation:
the framework opinions stop at the runtime contract, and
deployment opinions live with the operator. Folding the
deploy step into the skill would couple the framework to a
specific deployment posture, defeating the agnostic-by-default
goal, and pushing it onto each implementing app would force
every solution to carry deployment opinions it doesn't
otherwise need. The skill decides when authoring is "done" and
what counts as a verified operating instance, but it doesn't own
what happens between them.

## Further Reading

- [docs/custom-middleware.md](docs/custom-middleware.md) — advanced middleware configuration
- [CONTRIBUTING.md](CONTRIBUTING.md) — architecture, design decisions, testing
