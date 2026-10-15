# Operating a deployed mcp-app solution

Read this when connecting the admin CLI, verifying a deployment, adding or
revoking users, rotating a user's backend credential, or registering an MCP
client against an mcp-app server. It applies however the server was
deployed: Cloud Run, Docker, bare metal, Kubernetes, or anything else.

This is the operate stage. It assumes a known URL whose `GET /health`
already answers `healthy` or `degraded`. It doesn't deploy and it doesn't
discover deployments; that is the deploy stage (`runtime-contract.md`). If
there's no healthy URL yet, stop and resolve that first.

**Verification of a fresh deploy is not optional.** After any deploy, or
when the running instance may have changed, climb the verification ladder
below before calling the deploy successful. `/health` proves the process
is up; `probe` and, when declared, `safe-tool --invoke` prove it serves
tools to a real user. Don't substitute `curl` or cloud CLI inspection.

Three kinds of operator use this:

- **Deploying operator**: just deployed; needs to connect, verify, and
  register the first user.
- **Returning operator**: back months later to rotate a credential, add a
  user, or investigate, possibly with no memory of how the app was
  deployed. The app's own docs plus the admin CLI's saved `connect` config
  must be enough. This is the most neglected audience: if a workflow
  depends on something captured in neither, flag it as a gap.
- **Agent operator**: an AI agent acting for a human. It relies on
  structured output (`--json`), deterministic commands, and
  self-documenting help (profile field descriptions in `--help`).

Each solution generates three commands from one `App`:

```bash
my-solution              # the app's own CLI (optional)
my-solution-mcp          # serve (HTTP) and stdio
my-solution-admin        # connect, users, tokens, health, probe, tools, safe-tool, register
```

## Before you start

**At the start of any session involving admin operations**, check
the current connection state before doing anything else:

```bash
my-solution-admin health        # remote — confirms URL and auth
my-solution-admin users list    # local or remote — confirms store access
```

If `health` prints `Local mode`, the CLI is pointed at the local store;
`connect remote` switches back to the saved deployment without the key.

Do not assume the admin CLI is pointed at the right target. The
connection may be stale from a previous session, pointed at a
different environment, or not configured at all. Deploying, or
registering a local MCP client, never connects the admin CLI. Verify
first.

**Prefer the per-app admin CLI** (`my-solution-admin`) over the
generic CLI (`mcp-app`). The per-app CLI stores connection config
per app in `~/.config/{name}/setup.json` — each app remembers
its own target independently. The generic CLI stores one
connection at a time and overwrites on each `connect`.

The framework tracks one connection per app (a single deployment
environment, whether local or remote). If the same app is
deployed to multiple environments, `connect` switches between
them but only remembers the last one configured.


## Connect the admin CLI

Check if the app's own admin CLI is available:

```bash
which my-solution-admin
```

If not found, install the package. Check `pyproject.toml` for
`[project.scripts]` to find the entry point name:

```bash
pipx install git+https://github.com/owner/my-solution.git
# or from a local clone:
pipx install -e .
```

Then connect:

```bash
# Per-app CLI (preferred) — local or remote
my-solution-admin connect local
my-solution-admin connect https://your-service --signing-key xxx

# Generic CLI (fallback) — remote only
mcp-app connect https://your-service --signing-key xxx
```

`connect local` is only available on the per-app CLI — the
generic CLI doesn't know which app's store to locate.

A remote `connect` needs the deployment's signing key. Where to find it,
and what to do when the agent isn't allowed to read it, is in `auth.md`.
`connect` saves the target in `~/.config/{name}/setup.json`, so later
commands take no URL or key. `connect local` switches to the local store
and keeps the saved remote; `connect remote` switches back without the key.


## Verify the deployment

The verification ladder has six rungs. Stop at the first one
that reveals the issue; otherwise climb until the deployment is
fully validated.

1. **`connect`** — point the admin CLI at the deployment.
2. **`probe`** — framework layer (liveness, admin auth,
   `tools/list` round-trip).
3. **`tools list`** — confirm the solution's tools module
   loaded and tool names match expectations.
4. **`tools show <name>`** — when the schema for a specific
   tool needs a sanity check.
5. **`safe-tool --invoke`** — opinionated end-to-end smoke
   test (only if the solution declared one).
6. **`tools call <name>`** — debug a specific tool with custom
   arguments when steps 2–5 leave a gap.

### Probe

```bash
my-solution-admin probe
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

This hits `/health` for liveness, then does an MCP `tools/list`
round-trip using a short-lived token minted for an existing
user. If it reports tools, the framework layer is operational —
health, admin auth, user auth, MCP transport, and tool wiring
all work.

If no users are registered yet, probe reports liveness only
and tells you it can't do the MCP round-trip. Register a user
first (Manage users, below), then probe again.

For structured output (agent consumption):
```bash
my-solution-admin probe --json
```

### Tools list and show

`probe` confirms the framework layer. `tools list` is a quick
sanity check that the right tools are exposed:

```bash
my-solution-admin tools list
my-solution-admin tools show <name>
my-solution-admin tools list --json     # for agent consumption
```

`tools show <name>` renders the description, arguments with
type/required-ness, and a copy-pasteable `tools call`
invocation example. Useful when you don't remember a tool's
schema or want to debug a specific tool's contract before
calling it.

**Requires a registered user.** Unlike `probe`, which can
report liveness-only when the deployment has no users,
`tools list` and `tools show` mint a per-user probe token to
do the MCP `tools/list` round-trip. On a deployment with no
registered users they exit with a clean error pointing at
`users add` rather than degrading to a liveness check —
because there's no useful "tools list" output to render
without the round-trip. Run `users add` (Manage users, below) first if
you haven't.

### Safe tool (deeper than probe)

Probe stops at `tools/list`. It does **not** exercise the
solution's tool handlers, the upstream credential on the user's
profile, or the response-shape contract a real client depends
on. `safe-tool --invoke` does — when the solution declared a
safe tool:

```bash
my-solution-admin safe-tool                # show declaration only
my-solution-admin safe-tool --invoke       # full end-to-end round-trip
my-solution-admin safe-tool --invoke --json
```

The CLI prints the JSON-RPC request body **before** sending so
an operator can copy and replay it manually in a debugger or
another terminal, with a different bearer token, etc. After the
call it prints the HTTP status code and the full response body.

**`safe-tool --invoke` requires a registered user** for the
same reason as `tools list/show`: the round-trip mints a
per-user probe token. The bare `safe-tool` (no `--invoke`)
only fetches the declaration metadata and does not need a
user — handy for confirming the safe tool is declared on a
fresh deployment before you've added any users.

#### Failure-mode table

| `probe` | `safe-tool --invoke` | Likely problem |
|---|---|---|
| ❌ | n/a | Framework layer — see the probe decision tree in `troubleshooting.md`. |
| ✅ | `supported: false` | Solution didn't declare a safe tool. Either accept this and rely on probe, or declare one. |
| ✅ | non-200 status | Solution-specific tool failed. Inspect `result.body` for the JSON-RPC error. |
| ✅ | 200 but empty / missing | Tool wired but upstream credential is invalid/expired/revoked. Use `users update-profile` to rotate the credential field. |
| ✅ | 200 with expected shape | Full stack verified. Done. |

Note: `--json` is the canonical agent-consumption path. The
envelope is versioned (`schema_version: "1"`) and additive-only
— consumers must tolerate unknown fields.

#### Privacy note for agent operators

`safe-tool --invoke` returns a curated, low-PII response that
is safe for an agent to read. **`tools call` is not curated**
and may return user content. When agent-driven validation must
not see user-authored data, prefer `safe-tool --invoke` and
rely on the response envelope contract.

### Tools call (open invocation)

When `safe-tool --invoke` isn't declared, or you need to invoke
a different tool with custom arguments to isolate an issue:

```bash
my-solution-admin tools call <name> --arg k=v --arg k2=v2
my-solution-admin tools call <name> --body '{"k": "v"}'
my-solution-admin tools call <name> --body @args.json
my-solution-admin tools call <name> --user alice@example.com   # mint as alice
```

`--arg` is for scalars (booleans, numbers, strings, null) and
type-coerces from the tool schema. Use `--body` for objects
and arrays.

`tools call` may return PII or user-authored content. Operators
running it interactively are implicitly accepting that.

### Manual verification (if the CLI isn't enough)

```bash
# Liveness
curl https://your-service/health

# Admin auth
my-solution-admin users list

# User auth — tools/list with a user token
curl -X POST https://your-service/ \
  -H "Authorization: Bearer USER_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 1}'
```


## Manage users

### Register a new user

```bash
# Data-owning app — no profile needed
my-solution-admin users add alice@example.com

# API-proxy app — profile via typed flags (field names are solution-specific; see `users add --help`)
my-solution-admin users add alice@example.com --<field> <value>
```

`users add` rejects existing users, so an API-proxy user's stored
credentials can't be overwritten by accident. If the user already
exists, use `update-profile` instead. `users add` prints the user's
token; issuing, revoking, and rotating tokens is in `auth.md`.

To discover what profile fields the app expects, check the
`--help` output — field names and descriptions are generated
from the app's Pydantic profile model:

```bash
my-solution-admin users add --help
```

### Read the current profile

```bash
my-solution-admin users get-profile alice@example.com
my-solution-admin users get-profile alice@example.com --json
```

When the solution has a registered profile model, the per-app
CLI shows every declared field with its current value or
`(missing)`, and tags any extra stored keys as
`(not in profile model)`. This is how you confirm what's
actually stored before rotating, or verify a credential rotation
landed.

### Update credentials

Field names are solution-specific — discover them from
`my-solution-admin users update-profile --help`, which lists
valid keys generated from the solution's profile model.

```bash
# Typed key (expand=True apps) — key is validated, tab-completable
my-solution-admin users update-profile alice@example.com <field> <new-value>

# JSON merge (expand=False apps)
my-solution-admin users update-profile alice@example.com '{"<field>": "<new-value>"}'
```

Use this to rotate backend credentials, refresh OAuth tokens, or
change any per-user setting without re-registering the user. Only the specified field is changed — other profile
fields are preserved.

### Other user operations

```bash
# List all users
my-solution-admin users list

# Revoke a user (invalidates all their tokens immediately)
my-solution-admin users revoke alice@example.com

# Issue a new token for an existing user
my-solution-admin tokens create alice@example.com
```


## Register MCP clients

Use `register` to generate ready-to-paste commands:

```bash
# With a real token (mints one for the user)
my-solution-admin register --user alice@example.com

# With a placeholder (operator substitutes later)
my-solution-admin register
```

This outputs commands for Claude Code, Antigravity CLI (`agy`),
and the Claude.ai URL form, with the URL and token already
substituted. agy has one user-level config, so it gets a single
command with no scope.

For structured output:
```bash
my-solution-admin register --user alice@example.com --json
```

Filter by client or scope:
```bash
my-solution-admin register --user alice@example.com --client claude --scope user
```

### Manual registration (if register isn't available)

**stdio (local):** no token.
```bash
claude mcp add my-solution -- my-solution-mcp stdio --user local
agy mcp add my-solution -- my-solution-mcp stdio --user local
```

**HTTP (remote):** the client needs the URL (root path `/`) and the
user's token. The exact forms for Claude Code, Antigravity CLI, and
Claude.ai are in `auth.md`.

## Pointing the admin CLI at a solution deployed outside mcp-app

However the solution was deployed — bare `gcloud`, `docker`,
`systemd`, a CI pipeline, anything — the admin flow is the
same: connect the admin CLI at the URL, supply the signing
key, and use the normal admin commands.

```bash
my-solution-admin connect https://my-service.example.com --signing-key xxx
my-solution-admin users add alice@example.com
my-solution-admin probe
```

The generic `mcp-app` CLI works the same way when the per-app
admin CLI isn't installed (see below). Both interfaces hit the
same admin REST API exposed by the running service.

## When to use the generic CLI

If the app's own admin CLI (`my-solution-admin`) isn't installed
— e.g., managing a deployed instance from a machine without the
app's repo — use the generic `mcp-app` CLI:

```bash
mcp-app connect https://your-service --signing-key xxx
mcp-app users add alice@example.com --profile '{"<field>": "<value>"}'
mcp-app users get-profile alice@example.com
mcp-app probe
mcp-app register my-solution --user alice@example.com
```

The generic CLI works but doesn't have typed profile flags,
model-aware `get-profile` output, or `connect local`. Always
prefer the per-app CLI when available.

## Important notes

- **`connect` and `deploy` are independent.** Deploying a
  service does not automatically connect the admin CLI to it.
  After deploying, explicitly run `connect` before admin
  operations.
- **User management is an mcp-app concern**, not a deployment
  tool concern. Admin endpoints and the CLI are part of the
  framework.
- **Admin tokens are generated locally** using the signing
  key — they don't pass through the deployed service.
- **The signing key retrieval method depends on the deployment
  tooling.** This skill can't prescribe a single command —
  investigate the deployment configuration to trace where the
  key lives.
