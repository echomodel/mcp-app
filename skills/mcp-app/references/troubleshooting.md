# Troubleshooting

Read this when an mcp-app server misbehaves: a client says "failed to
connect", a 401 or 403, tools missing from the list, a server that won't
start, or a tool that errors. First confirm the server is an mcp-app
solution the user runs. A hosted connector the user doesn't operate (a
third-party Gmail or Jira connector, say) is outside this guide.

## Deployed (HTTP) server: start with probe

Most *"my MCP connection failed"* reports do not require poking at curl
commands or reading framework source. Run one command first and let its
output narrow the problem:

```bash
my-solution-admin probe
```

Probe checks the front door an MCP client depends on: `/health` for
liveness, the discovery document at
`/.well-known/oauth-protected-resource`, and that an unauthenticated MCP
request gets a `401` pointing at it. It needs no sign-in. Where it stops
tells you which layer is broken; what it can't see is the sign-in itself,
which only a real MCP client (or a token from the identity provider)
exercises.

## Decision tree

| Probe outcome | Likely cause | Next step |
|---|---|---|
| `Health: unreachable` / connection error | Service not running, wrong URL, networking | Check the deploy (logs, process, ingress). Not an auth problem. |
| `Health: healthy` but `OAuth: error` (no discovery document, or no 401 challenge) | The URL isn't an mcp-app 2.x server, a path prefix is in the way, or the server is on 1.x | Confirm the URL is the bare base URL (path `/`) and the pinned mcp-app version (`framework-version.md`). |
| `OAuth: ok` but `resource` isn't the URL users type (wrong scheme or hostname) | The front door rewrites `Host` or doesn't forward `X-Forwarded-Proto`; tokens issued for the public URL will fail `aud` | Fix the proxy to pass `Host` through and send `X-Forwarded-Proto`, or pin `AUTH_AUDIENCE` to the public URL (`auth.md`). |
| `OAuth: ok` but `issuer` is wrong | `AUTH_ISSUER` points at the wrong provider or tenant | Fix the env var and redeploy. |
| `OAuth: ok`, client sign-in completes, then `403` | The signed-in email isn't registered and isn't in `ADMIN_EMAILS` | Register it (`auth.md`, admin access on a deployment) or add it to `ADMIN_EMAILS` and redeploy. |
| `OAuth: ok`, client loops on sign-in or reports `401` after signing in | Token rejected: `iss` mismatch (often a trailing slash), `aud` doesn't contain the server URL, opaque rather than JWT tokens, or no email claim | Read the server log's `token rejected` reason; compare `iss`/`aud` with the startup `auth` line; set the issuer's default audience and email claim (`auth.md`). |
| `OAuth: ok`, sign-in works, tools listed, a tool errors | Solution-specific: the backend credential on the user's profile is stale or missing | `users get-profile`, then `users update-profile` (`operate.md`). |
| Everything passes but one client still fails | Client-side: stale connector config, wrong URL, a leftover `Authorization` header from a 1.x registration | Remove and re-add the server from a fresh `register` output (`operate.md`). |

If `/health` reports `degraded` or `unhealthy`, read `GET /admin/health`
(administrator's token) or the startup `data_dir` log line for the storage
detail the public endpoint deliberately omits (`runtime-contract.md`).

## Why probe first

The client shows the same "failed to connect" for a service that is
down, a service whose discovery document is missing, a sign-in that the
issuer refused, and a user who isn't registered. Probe separates the
first two from the last two with known-good, credential-free requests,
so the remaining question is always about the issuer or the user list,
never about the deployment.

## Scope: what mcp-app does and doesn't own

mcp-app is responsible for validating the identity provider's
tokens and for user access control (registration, revocation). The
framework is
**not** responsible for whether the solution's backend
credential — the token or API key the solution uses to call its
upstream on behalf of the user — is still valid. That
credential lives on the user's profile, its schema is declared
by the solution, and its validity depends on whatever upstream
service the solution targets. When probe reports admin + MCP
working but the client still misbehaves at a tool-call level,
assume a solution-specific issue and consult the solution's
docs or admin CLI help.


## Symptoms that don't need a deployment

| Symptom | Likely cause | Check |
|---|---|---|
| A tool is missing from `tools/list` | The function is sync, starts with `_`, isn't in the tools module the `App` was given, or is `@mcp_transport`-restricted to the other transport | Read the tools module against the discovery rules in `authoring.md`. A stdio-only tool is correctly absent over HTTP. |
| An SDK function shows up as a tool | It was imported into the tools module as a public async function | Use a class-based SDK, or import it with an underscore alias (`authoring.md`). |
| HTTP server exits at startup | `AUTH_ISSUER` unset, or `REQUIRED_FS_TYPE` set and the data dir's filesystem doesn't match | Read the startup log; the error names the variable, and the `mcp_app.startup data_dir` line shows `fs_type_check`. |
| Startup warns `ADMIN_EMAILS is empty` | Nobody can call `/admin` or be admitted without a prior registration | Set `ADMIN_EMAILS` and redeploy. |
| 401 whose description names the email claim | The issuer doesn't put the email in access tokens, or under a different claim name | Add the claim at the issuer; set `AUTH_EMAIL_CLAIM` to its full name (`auth.md`). |
| `/admin` returns 403 with the operator's own token | The token's email claim isn't in `ADMIN_EMAILS` (case and spelling), or the claim name differs from `AUTH_EMAIL_CLAIM` | Decode the token and compare; `ADMIN_EMAILS` is compared lower-cased. |
| Remote `users list` says "signed in as an administrator" | The admin CLI has no remote sign-in in 2.0 | Expected. Use `connect local` for the local store, or `/admin` with an administrator's token for a deployment (`auth.md`). |
| `connect` or `users add` complains about `--signing-key` or `tokens` | The instructions are from 1.x | Follow the 2.x flow: `connect <url>`, `probe`, `register`, sign in (`operate.md`). |
| stdio client reports "failed to connect" | `--user` missing, the `*-mcp` command not on the client's `PATH`, or the user record doesn't exist in the local store | Run the registered command by hand in a terminal; add the user with `connect local` then `users add` (`operate.md`). |
| A fix in the working tree has no effect | The installed CLI is a snapshot, not editable | `pipx list` must show `(editable)` for the package (`testing.md`, Step 0). |
| Tool calls work but return upstream errors | The backend credential on the user's profile is stale | `users get-profile`, then `users update-profile` (`operate.md`). |
