# Runtime contract, storage, health, and the deploy boundary

Read this when running a solution locally over HTTP, containerizing it,
deploying it, choosing where its data lives, reading `/health`, or deciding
how to get from a validated working tree to a deployed URL. Auth variables
(`AUTH_*`, `SIGNING_KEY`, `JWT_AUD`, `TOKEN_DURATION_SECONDS`) are in `auth.md`.

mcp-app describes what an app needs from its environment and leaves the
deployment to the operator's tooling. This file is that contract.

## Environment variables

| Var | Required | If missing | Purpose |
|-----|----------|------------|---------|
| `AUTH_ISSUER` | For OAuth mode | Shared-secret mode | Authorization server issuer; setting it selects OAuth resource-server mode (`auth.md`) |
| `AUTH_AUDIENCE` | With `AUTH_ISSUER` | Startup fails | Required `aud` value, the API identifier at the issuer (`auth.md`) |
| `MCP_RESOURCE_URL` | With `AUTH_ISSUER` | Startup fails | Public URL of this server as users type it (`auth.md`) |
| `AUTH_EMAIL_CLAIM` | No | `email` | Claim carrying the user's email (`auth.md`) |
| `AUTH_JWKS_URI` | No | OpenID discovery | Issuer key set location (`auth.md`) |
| `SIGNING_KEY` | For HTTP, shared-secret mode | Startup fails | JWT signing key (`auth.md`) |
| `JWT_AUD` | No | Audience not validated | Expected JWT `aud` claim, shared-secret mode (`auth.md`) |
| `TOKEN_DURATION_SECONDS` | No | ~10 years | Token lifetime (`auth.md`) |
| `APP_USERS_PATH` | No | `~/.local/share/{name}/users/` | Per-user data directory |
| `REQUIRED_FS_TYPE` | No | No assertion | Opt-in startup check that the data dir is on a given filesystem type |

**`APP_USERS_PATH`** is critical for any deployment where the
filesystem is not persistent. The default (`~/.local/share/{name}/users/`)
works on a developer's laptop. In a container, this path is
ephemeral — the app starts, users get registered, tools execute,
and then user data is silently lost on container restart. No error,
no warning. For any persistent deployment, this must point to a
mounted volume or persistent storage path. Make the user aware of
this and confirm the path is durable before considering deployment
complete.

## Data storage and the startup check

The default store writes per-user records under one root:
`APP_USERS_PATH` if set, else `${XDG_DATA_HOME:-~/.local/share}/{app-name}/users/`.
Anything mcp-app writes for a user lives there.

On every start (HTTP or stdio) mcp-app logs one line under the
`mcp_app.startup` logger:

```
INFO mcp_app.startup data_dir path=/var/lib/my-app/users exists=true writable=true fs_type=fuse.gcsfuse free_bytes=137438953472 required_fs_type=<unset>
```

`fs_type` is the raw OS value. `overlay`/`overlayfs` (container layer) and
`tmpfs` lose data on restart. `fuse*`, `nfs`, `cifs`/`smbfs`, and local
disks (`ext4`, `xfs`, `apfs`, `btrfs`, `zfs`) are durable.

`REQUIRED_FS_TYPE` turns that report into a guard. It takes a
comma-separated list matched on `.` boundaries (`fuse` matches
`fuse.gcsfuse`). When set and the data dir doesn't match, isn't writable,
or is missing, the process logs `fs_type_check=mismatch` (or
`path_missing`/`not_writable`) and exits non-zero, so a broken revision
never serves traffic. Recommend it for any durable deployment: it's the
only thing that catches a volume mount that silently didn't happen. It is
opt-in because ephemeral storage is correct on a laptop.

## Health endpoints

`GET /health` needs no auth and returns only a verdict:

```json
{"status": "healthy", "checks": {"persistent_storage": "verified"}}
```

| `status` | HTTP | Meaning |
|---|---|---|
| `healthy` | 200 | All checks pass |
| `degraded` | 200 | Safe to serve; e.g. storage `unverified` because `REQUIRED_FS_TYPE` is unset |
| `unhealthy` | 503 | A required check failed; the platform should pull the instance |

`checks.persistent_storage` is `verified`, `unverified`, or `unavailable`.
The public body never carries paths, filesystem types, or free space;
`GET /admin/health` (admin JWT) returns that detail. Treat
`status in ("healthy", "degraded")` as "serving". Older versions returned
`{"status": "ok"}`; don't match that literal.

## Running locally

**stdio** — no auth, no signing key. The MCP client launches the
process:
```bash
my-solution-mcp stdio --user local
```

**HTTP**: requires `SIGNING_KEY` at minimum (`auth.md`):
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

## Runtime contract

Any deployment target must provide:

- **Start command:** `my-solution-mcp serve` (optional `--host` and
  `--port`, default `0.0.0.0:8080`). The `App` object is also a plain ASGI
  callable, so `uvicorn my_solution:app` or any ASGI host runs the same
  stack, but `serve` is the documented form for deployment configs.
- **Environment variables:** `SIGNING_KEY` from a secret store, and
  `APP_USERS_PATH` on persistent storage for any durable deployment.
- **MCP endpoint path:** `/` (root), not `/mcp`. Clients connect to
  `https://host:port/`. If a previous deployment served another path,
  client URLs must change.
- **Health check:** `GET /health`, no auth (above).
- **Admin API:** `POST/GET /admin/users`, `DELETE /admin/users/{email}`,
  `GET/PATCH /admin/users/{email}/profile`, `POST /admin/tokens`,
  `GET /admin/safe-tool`, `GET /admin/health`. All require an admin JWT.
- **Auth model:** the app does its own auth. A platform auth gate (IAM, API
  gateway) must let unauthenticated traffic through to the app.
- **Build root:** the repo root where `pyproject.toml` lives.

**Docker example:**
```bash
docker build -t my-solution .
docker run -p 8080:8080 \
  -e SIGNING_KEY=your-key \
  -v /persistent/path:/data \
  -e APP_USERS_PATH=/data/users \
  my-solution
```

## Containerizing

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

## Deployment routes

mcp-app does not prescribe a deployment tool. Common options:

- **Bare metal / VPS** — `pip install -e . && my-solution-mcp serve`
  with env vars set in the shell or a process manager
- **Docker** — build the image, run it with `-e SIGNING_KEY=...`
  and a volume mount for `APP_USERS_PATH`
- **Cloud Run / similar** — deploy from source or from a container
  image, set env vars and secrets through the platform
- **A deployment tool with its own skill or plugin** (gapp is one
  example: it handles infrastructure, secrets, and data volumes for
  Cloud Run). If one is loaded, invoke it; it guides setup, secret
  configuration, and deployment. Map the runtime contract above onto
  its configuration.

When using a deployment skill, invoke it now. The runtime
contract, env var requirements, and auth model are already in
your context — map them to the deployment tool's configuration.
After deployment completes, continue with "After deploy" below.

Regardless of route, the agent must ensure:
1. `SIGNING_KEY` is sourced from a secrets store or generated by
   the deployment tool — never hardcoded or checked in
2. `APP_USERS_PATH` points to persistent storage — not the
   container's ephemeral filesystem
3. The platform allows unauthenticated HTTP traffic through to
   the app (mcp-app handles auth internally)

## The deploy boundary

The solution lifecycle has three stages:

1. **Author**: write, structure, and validate locally. This skill.
2. **Deploy**: turn the validated tree into a reachable URL that passes
   `/health`. Owned by the operator's environment, not by mcp-app.
3. **Operate**: connect, verify, manage users, register clients. This
   skill again (`operate.md`), once a URL exists.

Stage 2 (deploy and discover-deployment) is owned by the
operator's environment, not by mcp-app's skills and not
necessarily by the solution's repo. A solution *may* prescribe a
deployment mechanism, but it need not — and most do not. When the
agent needs to drive a deployment or discover an existing
deployment's URL, it consults — in this order:

1. **The operator's agent environment.** A deployment skill or
   plugin loaded for the cloud platform / orchestrator / deploy
   automation the operator uses; any global or user-level
   context describing how this operator deploys mcp-app
   solutions. This is the primary source for solutions that
   don't prescribe deployment. If a relevant deployment skill
   is loaded, drive it — the skill's responsibility is to
   produce a URL and confirm liveness.
2. **The solution's own repo guidance** — `CONTRIBUTING.md`,
   `CLAUDE.md`, `README.md`, in-repo deployment scripts with
   documented usage. Only relevant for solutions that
   prescribe a route. Follow whatever guidance the repo gives.
3. **Ask the user.** If neither (1) nor (2) yields a clear
   path, ask the user to direct the next step. Do not
   improvise with raw cloud CLI commands or guessed
   credentials. The absence of stage-2 guidance is a signal
   that the operator's environment has not been set up for
   agent-driven deploys on this solution, and the user must
   make the call.

Once the URL answers `GET /health` with `healthy` or `degraded`, move to
`operate.md` and run its verification ladder. Don't substitute raw cloud
CLI inspection or `curl` probes for that ladder: `/health` proves the
process is up, not that it serves tools to a real user.

## After deploy

Connecting the admin CLI, verifying end-to-end, adding users, rotating
credentials, and registering clients are in `operate.md`. The signing key
for `connect` comes back out of whatever store the deployment used
(`auth.md`).
