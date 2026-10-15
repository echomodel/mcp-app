# Troubleshooting

Read this when an mcp-app server misbehaves: a client says "failed to
connect", a 401 or 403, tools missing from the list, a server that won't
start, or a tool that errors. First confirm the server is an mcp-app
solution the user runs. A hosted connector the user doesn't operate (a
third-party Gmail or Jira connector, say) is outside this guide.

## Deployed (HTTP) server: start with probe

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

## Decision tree

| Probe outcome | Likely cause | Next step |
|---|---|---|
| `Health: failed` / connection error | Service not running, wrong URL, networking | Check the deploy (logs, process, ingress). Not an auth problem. |
| `Health: healthy` but admin calls fail (e.g. `users list`) | Admin signing chain broken — the CLI's `SIGNING_KEY` doesn't match the deployed server's | Re-retrieve the signing key (`auth.md`) and reconnect. |
| `Health: healthy`, admin works, but MCP round-trip returns 401/403 | User auth: either the user is revoked, or the solution's backend credential on the user's profile is invalid or expired | Check `my-solution-admin users update-profile --help` for the solution-specific profile field names, then rotate with `my-solution-admin users update-profile alice@example.com <field> <new-value>`. If the user was revoked, issue a new token via `tokens create`. |
| Probe succeeds (`MCP: ok`, tools listed) | Deployed service is fully functional | Failure is client-side: stale connector config, wrong URL, wrong header format, or a claude.ai / Claude Code probe idiosyncrasy. Re-register the client from scratch (`operate.md`, register MCP clients) and compare against a fresh `register --user EMAIL` output. |

If `/health` reports `degraded` or `unhealthy`, read `GET /admin/health`
(admin-authenticated) or the startup `data_dir` log line for the storage
detail the public endpoint deliberately omits (`runtime-contract.md`).

## Why probe first

The server returns the same `{"error": "Invalid or revoked
token"}` body for at least three distinct causes: (a) JWT
signature doesn't verify, (b) the user has been revoked,
(c) the solution-specific backend credential on the user's
profile is invalid or expired. Curl output alone cannot
distinguish these. Probe exercises each layer with known-good
inputs (the admin CLI's own signing key, a freshly minted
token) and isolates the failing layer without ambiguity.

## Scope: what mcp-app does and doesn't own

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


## Symptoms that don't need a deployment

| Symptom | Likely cause | Check |
|---|---|---|
| A tool is missing from `tools/list` | The function is sync, starts with `_`, isn't in the tools module the `App` was given, or is `@mcp_transport`-restricted to the other transport | Read the tools module against the discovery rules in `authoring.md`. A stdio-only tool is correctly absent over HTTP. |
| An SDK function shows up as a tool | It was imported into the tools module as a public async function | Use a class-based SDK, or import it with an underscore alias (`authoring.md`). |
| HTTP server exits at startup | `SIGNING_KEY` unset or empty, or `REQUIRED_FS_TYPE` set and the data dir's filesystem doesn't match | Read the startup log; the `mcp_app.startup data_dir` line shows `fs_type_check`. |
| stdio client reports "failed to connect" | `--user` missing, the `*-mcp` command not on the client's `PATH`, or the user record doesn't exist in the local store | Run the registered command by hand in a terminal; add the user with `connect local` then `users add` (`operate.md`). |
| A fix in the working tree has no effect | The installed CLI is a snapshot, not editable | `pipx list` must show `(editable)` for the package (`testing.md`, Step 0). |
| Tool calls work but return upstream errors | The backend credential on the user's profile is stale | `users get-profile`, then `users update-profile` (`operate.md`). |
