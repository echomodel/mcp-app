---
name: mcp-app-admin
description: "Operate and manage deployed MCP apps or solutions that use the mcp-app framework. Use when asked to verify a deployment, connect the admin CLI, retrieve a signing key, register or manage users, issue or revoke tokens, update a user's profile with a fresh credential, test a deployed service end-to-end, configure a deployed MCP server for use in Claude, Gemini, or other agent platforms, or troubleshoot post-deploy auth. Also use proactively whenever a user reports that a deployed mcp-app MCP server is misbehaving — connection failures, auth errors, 401/403 responses, tools not appearing, client says 'failed to connect', token not working, or any symptom-level report from a client or the deployed service. Triggers on: verify deployment, test the deployed service, manage users, add a user, list users, revoke a user, update a token, refresh a credential, get the signing key, connect the admin CLI, configure MCP client, issue a new token, probe, register, MCP not working, MCP failed to connect, can't connect to MCP, client reports failed, 403 from deployed MCP, 401 from deployed MCP, auth failing on MCP, token not working, tools not listed, and similar post-deploy operational tasks or failure reports on running mcp-app services."
---

# mcp-app Admin

## Overview

This skill covers operating mcp-app solutions after deployment:
connecting the admin CLI, verifying the deployment end-to-end,
managing users and credentials, and registering MCP clients. It
applies regardless of how the solution was deployed — Cloud Run,
Docker, bare metal, or any other environment.

The `author-mcp-app` skill covers building, structuring, testing,
and deploying solutions. This skill picks up where deployment ends.
The hand-off point is: the app is deployed and running, the
operator needs to connect, verify, and manage it.

## Where this skill fits — user journey map

Every mcp-app solution supports six recurring journeys across
three audiences (developer, operator, end user). The
`author-mcp-app` skill enumerates the full map. This skill owns
journeys 4–6:

- **Journey 4: Connect admin CLI post-deploy** — retrieve the
  signing key, point the admin CLI at the deployed instance
  (or the local store), persist the per-app config.
- **Journey 5: Manage users and credentials** — add, list,
  revoke, issue tokens, read profiles (`users get-profile`),
  rotate profile fields (`users update-profile`).
- **Journey 6: Verify end-to-end and register MCP clients** —
  `probe` for liveness + MCP round-trip, `register` to emit
  Claude Code, Gemini CLI, and Claude.ai URL-form commands.

Journeys 1–3 (install, run locally, deploy) are outside this
skill's scope — refer the user or agent to the app's own
README, the `author-mcp-app` skill, or their deployment tool's
skill as appropriate.

### Audiences

- **Deploying operator** — just finished a deploy, needs to
  connect, verify, and register the first user.
- **Returning operator** — coming back months later to rotate
  a credential, add a user, or investigate an issue. May not
  remember how the app was deployed. Should be able to
  reconstruct the operational state from the app's own docs
  and the per-app admin CLI config.
- **Agent-operator** — an AI agent performing admin operations
  on behalf of a human. Relies on structured output
  (`--json`), deterministic commands, and self-documenting
  CLI help (profile field descriptions).

The returning operator is the most frequently neglected
audience and the one this skill most explicitly serves. If a
workflow requires the operator to remember something not
captured in the app's docs or the admin CLI's persistent
config, flag it as a gap.

## Before You Start

**At the start of any session involving admin operations**, check
the current connection state before doing anything else:

```bash
my-solution-admin health        # remote — confirms URL and auth
my-solution-admin users list    # local or remote — confirms store access
```

Do not assume the admin CLI is pointed at the right target. The
connection may be stale from a previous session, pointed at a
different environment, or not configured at all. Verify first.

**Prefer the per-app admin CLI** (`my-solution-admin`) over the
generic CLI (`mcp-app`). The per-app CLI stores connection config
per app in `~/.config/{name}/setup.json` — each app remembers
its own target independently. The generic CLI stores one
connection at a time and overwrites on each `connect`.

The framework tracks one connection per app (a single deployment
environment, whether local or remote). If the same app is
deployed to multiple environments, `connect` switches between
them but only remembers the last one configured.

## Troubleshooting: when a client reports the MCP isn't working

Most *"my MCP connection failed"* reports do not require guessing
at signing keys, poking at curl commands, or reading framework
source. Run one command first and let its output narrow the
problem:

```bash
my-solution-admin probe
```

Probe walks the full stack: `/health` for liveness, admin signing
verification, and an MCP `tools/list` round-trip using a
short-lived token minted for an existing user. The point at which
probe fails tells you which layer is broken.

### Decision tree

| Probe outcome | Likely cause | Next step |
|---|---|---|
| `Health: failed` / connection error | Service not running, wrong URL, networking | Check the deploy (logs, process, ingress). Not an auth problem. |
| `Health: healthy` but admin calls fail (e.g. `users list`) | Admin signing chain broken — the CLI's `SIGNING_KEY` doesn't match the deployed server's | Re-retrieve the signing key (Step 1) and reconnect. |
| `Health: healthy`, admin works, but MCP round-trip returns 401/403 | User auth: either the user is revoked, or the solution's backend credential on the user's profile is invalid or expired | Check `my-solution-admin users update-profile --help` for the solution-specific profile field names, then rotate with `my-solution-admin users update-profile alice@example.com <field> <new-value>`. If the user was revoked, issue a new token via `tokens create`. |
| Probe succeeds (`MCP: ok`, tools listed) | Deployed service is fully functional | Failure is client-side: stale connector config, wrong URL, wrong header format, or a claude.ai / Claude Code probe idiosyncrasy. Re-register the client from scratch (Step 5) and compare against a fresh `register --user EMAIL` output. |

### Why probe first

The server returns the same `{"error": "Invalid or revoked
token"}` body for at least three distinct causes: (a) JWT
signature doesn't verify, (b) the user has been revoked,
(c) the solution-specific backend credential on the user's
profile is invalid or expired. Curl output alone cannot
distinguish these. Probe exercises each layer with known-good
inputs (the admin CLI's own signing key, a freshly minted
token) and isolates the failing layer without ambiguity.

### Scope: what mcp-app does and doesn't own

mcp-app is responsible for signing-chain integrity and user
access control (revocation, token issuance). The framework is
**not** responsible for whether the solution's backend
credential — the token or API key the solution uses to call its
upstream on behalf of the user — is still valid. That
credential lives on the user's profile, its schema is declared
by the solution, and its validity depends on whatever upstream
service the solution targets. When probe reports admin + MCP
working but the client still misbehaves at a tool-call level,
assume a solution-specific issue and consult the solution's
docs or admin CLI help.

## Step 1: Retrieve the Signing Key

The signing key is required for admin operations on remote
instances. Its location depends on how the solution was
deployed:

- **`mcp-app deploy` via a cloud provider** → the provider's
  own secret-resolution mechanism (typically a cloud secret
  manager); retrieve via `mcp-app signing-key show` or the
  provider's surface.
- **Bare `gcloud run deploy` with `--set-secrets=`** → stored
  directly in Secret Manager; retrieve via `gcloud secrets
  versions access latest --secret=...`.
- **Any other opinionated deploy tool** → stored wherever the
  tool puts it; consult that tool's documentation or CLI.
- **Manual deploy (any CI, docker, systemd, etc.)** →
  wherever the operator put it when setting up the deploy;
  investigate the deploy configuration.

For anything other than `mcp-app deploy`, the app admin CLI is
connected manually:
```bash
my-solution-admin connect <url> --signing-key "$(retrieve-it-somehow)"
```

### How to find it

**Start with the deployment configuration.** Look at how the
solution was deployed and how `SIGNING_KEY` was configured:

- **gapp** with a generated secret — retrieve from GCP Secret
  Manager using the secret name from gapp config:
  ```bash
  gapp secrets get <secret-name> --raw
  ```

- **Cloud secret manager** (GCP, AWS, etc.) — the key was
  stored there by the deployment tool or manually:
  ```bash
  # GCP
  gcloud secrets versions access latest --secret=SECRET_ID --project=PROJECT_ID
  # AWS
  aws secretsmanager get-secret-value --secret-id SECRET_ID
  ```

- **Terraform** managing the secret — check Terraform state:
  ```bash
  terraform output -raw signing_key
  ```

- **Docker Compose** — check `docker-compose.yml` for the
  secret source (file path, env var, Docker secret).

- **CI/CD secrets** (GitHub Actions, GitLab CI) — these are
  write-only from the UI. If this is the only copy, generate
  a new key, update the CI secret, and redeploy.

- **Environment variable set manually** — check the process
  environment or the shell/systemd/supervisor config.

### If you can't find it

Generate a new one, store it wherever the deployment expects
it, redeploy, and re-register all users (existing tokens
become invalid):

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

## Step 2: Connect the Admin CLI

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

## Step 3: Verify the Deployment

Use `probe` for single-command end-to-end verification:

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
user. If it reports tools, the app is fully operational —
health, admin auth, user auth, MCP layer, and tool wiring all
work.

If no users are registered yet, probe reports liveness only
and tells you it can't do the MCP round-trip. Register a user
first (Step 4), then probe again.

For structured output (agent consumption):
```bash
my-solution-admin probe --json
```

### Manual verification (if probe isn't enough)

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

## Step 4: Manage Users

### Register a new user

```bash
# Data-owning app — no profile needed
my-solution-admin users add alice@example.com

# API-proxy app — profile via typed flags (field names are solution-specific; see `users add --help`)
my-solution-admin users add alice@example.com --<field> <value>
```

`users add` rejects existing users. If the user already exists,
use `update-profile` instead.

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

Use this to rotate backend credentials without re-registering
the user. Only the specified field is changed — other profile
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

### Token lifecycle

- Tokens are long-lived by default (~10 years) because MCP
  clients cannot refresh tokens automatically.
- Revocation is the primary access control — `users revoke`
  sets a cutoff timestamp, and all tokens issued before that
  moment are rejected.
- After revoking, issue a new token with `tokens create` to
  reactivate the user.
- The token from `users add` or `tokens create` is what the
  user configures in their MCP client.

## Step 5: Register MCP Clients

Use `register` to generate ready-to-paste commands:

```bash
# With a real token (mints one for the user)
my-solution-admin register --user alice@example.com

# With a placeholder (operator substitutes later)
my-solution-admin register
```

This outputs commands for Claude Code, Gemini CLI, and the
Claude.ai URL form, with the URL and token already substituted.

For structured output:
```bash
my-solution-admin register --user alice@example.com --json
```

Filter by client or scope:
```bash
my-solution-admin register --user alice@example.com --client claude --scope user
```

### Manual registration (if register isn't available)

**stdio (local):**
```bash
claude mcp add my-solution -- my-solution-mcp stdio --user local
gemini mcp add my-solution -- my-solution-mcp stdio --user local
```

**HTTP (remote):**
```bash
claude mcp add --transport http my-solution \
  https://your-service/ \
  --header "Authorization: Bearer USER_TOKEN"
```

**Claude.ai / Claude mobile:**
```
https://your-service/?token=USER_TOKEN
```

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

## When to Use the Generic CLI

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

## Important Notes

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
