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
is up; `probe` proves the OAuth front door; a sign-in from a real MCP
client and a tool call prove it serves tools to a real user. Don't
substitute `curl` or cloud CLI inspection.

**What the admin CLI can and cannot do against a deployment in 2.0.**
Remote mode supports `connect`, `health`, `probe` and `register`, none of
which needs a credential. `users`, `tools` and `safe-tool` need a signed-in
administrator, and the CLI does not yet sign in: against a remote they exit
with a message saying so. They work in full against the local store
(`connect local`). How an administrator reaches `/admin` on a deployment
today is in `auth.md`.

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
my-solution-admin        # connect, users, health, probe, register (tools, safe-tool once signed in)
```

## Before you start

**At the start of any session involving admin operations**, check
the current connection state before doing anything else:

```bash
my-solution-admin health        # remote — confirms the URL answers
my-solution-admin users list    # local — confirms store access
```

If `health` prints `Local mode`, the CLI is pointed at the local store;
`connect remote` switches back to the saved deployment.

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
my-solution-admin connect https://your-service

# Generic CLI (fallback) — remote only
mcp-app connect https://your-service
```

`connect local` is only available on the per-app CLI — the
generic CLI doesn't know which app's store to locate.

A remote `connect` takes the URL and nothing else; it prints the
deployment's endpoints (MCP, admin, discovery, health). `connect` saves
the target in `~/.config/{name}/setup.json`, so later commands take no
URL. `connect local` switches to the local store and keeps the saved
remote; `connect remote` switches back.


## Verify the deployment

The verification ladder has four rungs. Stop at the first one that
reveals the issue; otherwise climb until the deployment is validated.

1. **`connect`** — point the admin CLI at the deployment.
2. **`probe`** — liveness, the discovery document, and the 401
   challenge: the OAuth front door an MCP client needs.
3. **`register`, then sign in from a real MCP client** — the operator
   adds the URL in their client, signs in, and calls a tool. This is
   the end-to-end proof: identity provider, token validation, the
   user record, the MCP layer, and tool wiring.
4. **`safe-tool --invoke` / `tools call <name>`** — opinionated or
   ad-hoc tool invocation from the CLI, once the CLI can sign in
   (not in 2.0 against a remote; see above).

### Probe

```bash
my-solution-admin probe
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

Probe hits `/health`, reads `/.well-known/oauth-protected-resource`, and
sends one unauthenticated MCP request to confirm it gets a `401` whose
`WWW-Authenticate` points at that document. No sign-in and no user is
needed. If it reports `OAuth: ok`, an MCP client can sign a user in.

Read the two values it prints: `issuer` must be the identity provider
the operator intended, and `resource` must be the URL users type. A
`resource` that differs (a wrong scheme, an internal hostname) means the
front door is rewriting `Host` or not forwarding `X-Forwarded-Proto`;
fix the proxy, or pin `AUTH_AUDIENCE` (`auth.md`).

For structured output (agent consumption):
```bash
my-solution-admin probe --json
```

### Usage report

Once signed in as an administrator from an MCP client, ask for
`usage_report` (`week="current"` or `"prior"`). It returns JSON: users
(total, new, active), tool calls (total, errors, per tool) and the most
active users with masked emails and per-tool counts. Recomputed on every
call, so a scheduled agent or routine can send the same report weekly
and re-send it on demand. Non-admins never see the tool. Counters live
in `usage/` beside the user directories on the data volume; see
`runtime-contract.md`.

### Sign in from a client

```bash
my-solution-admin register
```

prints the registration command for each MCP client. The operator runs
the one for theirs, signs in when the client sends them to the identity
provider, and calls a tool. An `ADMIN_EMAILS` entry is admitted on first
sign-in, so this works on a deployment with no users. Any other email
gets a `403` until an administrator registers it (`auth.md`).

### Tools list and show

`tools list` and `tools show <name>` do an MCP `tools/list` round-trip as
a signed-in administrator:

```bash
my-solution-admin tools list
my-solution-admin tools show <name>
my-solution-admin tools list --json     # for agent consumption
```

`tools show <name>` renders the description, arguments with
type/required-ness, and a copy-pasteable `tools call` invocation example.

**Needs a sign-in.** Against a remote in 2.0 they exit with the
not-signed-in message; the equivalent check is the client sign-in above.

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

**Both forms need a signed-in administrator**: the declaration lives
behind `/admin/safe-tool`, and the invocation is an MCP call. Against a
remote in 2.0 they exit with the not-signed-in message.

#### Failure-mode table

| `probe` | `safe-tool --invoke` | Likely problem |
|---|---|---|
| ❌ | n/a | Front door — see the probe decision tree in `troubleshooting.md`. |
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

# Discovery document an MCP client reads first
curl https://your-service/.well-known/oauth-protected-resource

# The 401 challenge (look at WWW-Authenticate)
curl -i -X POST https://your-service/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 1}'

# The same call with a user's token from the identity provider
curl -X POST https://your-service/ \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 1}'
```


## Manage users

On a deployment, user management is four admin-only MCP tools called from
the administrator's own MCP client (or from a script with a machine
token; `auth.md`, admin tools):

```
users_list()                     # every record with status: pending first, then approved, blocked
user_register("alice@example.com")   # approve: in advance, or a pending sign-in, or lift a block
user_block("bob@example.com")        # refuse from now on; data stays; user_register lifts it
usage_report(week="prior")           # the weekly report
```

`user_register` prints nothing to hand the user: they sign in from
their MCP client with their own account. Under `AUTH_ADMISSION=open`
nobody needs registering at all. Backend credentials for an API-proxy
app's profile are not tool arguments; until the user-authenticated
credential surface exists, set them against the local store below or
through the deprecated REST routes with an administrator's token.

The admin CLI's local mode still works against a local store:

```bash
my-solution-admin connect local
my-solution-admin users add alice@example.com [--<field> <value>]
my-solution-admin users get-profile alice@example.com
my-solution-admin users update-profile alice@example.com <field> <value>
my-solution-admin users list
```

Field names for API-proxy apps come from `users add --help`, generated
from the app's profile model. Against a remote the CLI's `users`,
`tools` and `safe-tool` commands exit with a not-signed-in message; the
tools above are the route (`auth.md`).

## Register MCP clients

Use `register` to generate ready-to-paste commands for the connected
deployment:

```bash
my-solution-admin register
my-solution-admin register --json                      # structured output
my-solution-admin register --client claude --scope user
my-solution-admin register --detect                    # mark what's already registered
```

Output:
```
claude (user scope, status unknown):
  claude mcp add --transport http -s user my-solution https://your-service/

claude (project scope, status unknown):
  claude mcp add --transport http -s project my-solution https://your-service/

agy (user config, status unknown):
  agy mcp add my-solution https://your-service/

claude.ai (manual: Settings > Connectors > Add custom connector):
  https://your-service/

Each client signs the user in with the identity provider on first use.
```

No command carries a credential, so the same output serves every user:
hand it to anyone whose email is registered (or in `ADMIN_EMAILS`) and
they sign in with their own account.

### Manual registration (if register isn't available)

**stdio (local):**
```bash
claude mcp add my-solution -- my-solution-mcp stdio --user local
agy mcp add my-solution -- my-solution-mcp stdio --user local
```

**HTTP (remote):** the client needs the base URL (path `/`) and nothing
else; the forms are in `auth.md`.

## Pointing the admin CLI at a solution deployed outside mcp-app

However the solution was deployed — bare `gcloud`, `docker`,
`systemd`, a CI pipeline, anything — the admin flow is the
same: connect the admin CLI at the URL and use the normal commands.

```bash
my-solution-admin connect https://my-service.example.com
my-solution-admin probe
my-solution-admin register
```

The generic `mcp-app` CLI works the same way when the per-app
admin CLI isn't installed (see below). Both interfaces hit the
same admin REST API exposed by the running service.

## When to use the generic CLI

If the app's own admin CLI (`my-solution-admin`) isn't installed
— e.g., managing a deployed instance from a machine without the
app's repo — use the generic `mcp-app` CLI:

```bash
mcp-app connect https://your-service
mcp-app probe
mcp-app register my-solution
```

The generic CLI has no typed profile flags, no model-aware
`get-profile` output, and no `connect local`; its `users` group has
the same remote sign-in limit as the per-app CLI. Always prefer the
per-app CLI when available.

## Important notes

- **`connect` and `deploy` are independent.** Deploying a
  service does not automatically connect the admin CLI to it.
  After deploying, explicitly run `connect` before admin
  operations.
- **User management is an mcp-app concern**, not a deployment
  tool concern. Admin endpoints and the CLI are part of the
  framework.
- **There is no secret to retrieve after a deploy.** `connect` needs
  the URL only. If a task seems to need a signing key, the app is on
  1.x (`framework-version.md`) or the task is mis-specified.
- **Adding a user to a deployment in 2.0 is an `/admin` call with an
  administrator's token** from the identity provider, not a CLI
  command (`auth.md`). Say so rather than improvising.
