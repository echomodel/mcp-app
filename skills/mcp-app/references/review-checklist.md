# Reviewing a solution: checklist and dashboard

Read this when reviewing an mcp-app solution against the framework's
standards, finishing a greenfield build or migration, or answering "is this
ready to deploy?"

## Review workflow

1. Check the mcp-app version and pin (`framework-version.md`).
2. Run the checklist below and present the results as a table.
3. For each failure, say what's wrong and what fixes it.
4. Run the tests (`testing.md`), then present the dashboard at the end of
   this file.
5. Close out the session as `SKILL.md` describes, even when the review
   finds nothing.

## Compliance checklist

### Structure
- [ ] Three-layer architecture: `sdk/`, `mcp/`, optional `cli/`
- [ ] All business logic in `sdk/`
- [ ] MCP tools are thin (one-liners calling SDK methods)
- [ ] `APP_NAME` constant in `__init__.py`
- [ ] `pyproject.toml` with correct dependencies and entry points
- [ ] `mcp-app` pinned to a released `@vX.Y.Z` tag, never a loose git URL

### MCP Server (mcp-app)
- [ ] `App` object declared in `__init__.py` with name and tools_module
- [ ] Tools module contains plain async functions (no decorators)
- [ ] Identity middleware runs by default (no config needed)
- [ ] Tool docstrings are clear and user-centric (also surface in
      `tools show <name>` for operators)
- [ ] **No tool reads a caller-named host path over HTTP.** Any tool that
      reads a file path supplied by the caller is `@mcp_transport("stdio")`
      (or the capability is CLI-only); the HTTP path takes bytes
      (`content_base64`) or an out-of-band upload URL. (See "File uploads &
      host-path inputs" in `authoring.md` — this is an arbitrary-server-file-read /
      cross-tenant-secret-exfiltration risk if exposed over HTTP.)
- [ ] Considered declaring a `SafeTool` for end-to-end smoke testing,
      or made a deliberate decision to opt out

### MCP Server (plain MCPServer — if not using mcp-app)
- [ ] Uses the `mcp` package 2.x (`MCPServer`) with `stateless_http=True`
      passed to `streamable_http_app()`
- [ ] DNS rebinding protection disabled (`transport_security=`) for a
      load-balanced host
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
- [ ] No app-level auth env vars, signing keys, or token stores; HTTP
      auth is `AUTH_ISSUER` + `ADMIN_EMAILS` from mcp-app (`auth.md`)

### Testing
- [ ] SDK unit tests in `tests/unit/`
- [ ] Full-stack HTTP tests using httpx ASGI transport
- [ ] No mocks unless needed for network I/O
- [ ] Tests use temp dirs and env vars for isolation
- [ ] mcp-app framework test suite — if `tests/framework/` exists,
  run `pytest tests/framework/ -v`. If it doesn't, set it up
  (`testing.md`, Step 5)
- [ ] Local install is editable before any CLI-driven validation
  runs (`testing.md`, Step 0). For reviews
  in particular: the locally-installed `<name>-mcp` may have been
  installed weeks ago as a snapshot — verify with
  `pipx list | grep -A5 <package>` for the `(editable)` marker
  before trusting any stdio smoke-test result.
- [ ] Live stdio smoke test passes against the editable install
- [ ] Tools that write, delete, or edit by position pass an agent eval
  from their descriptions alone (`agent-evals.md`)

### Documentation
- [ ] README.md with quick start, deployment, config
- [ ] CONTRIBUTING.md with architecture and testing standards
- [ ] CONTRIBUTING.md defines the release process (version from `vX.Y.Z` tags, bump rules, deploy the tag)
- [ ] CLAUDE.md: `@README.md` and `@CONTRIBUTING.md`
- [ ] `AGENTS.md` pointing to README and CONTRIBUTING (for Antigravity CLI)
- [ ] README and CONTRIBUTING cover all six journeys without any skill
      loaded (`app-docs.md`, including its final self-sufficiency check)

### Deployment Readiness
- [ ] Deployable as a standard container image
- [ ] Optionally, opinionated deployment tooling in-repo if
      the app is deliberately committed to one (see the
      opinionated-tooling alternative in `app-docs.md`)
- [ ] Optional compatibility artifacts (`Procfile`, minimal
      `Dockerfile`) shipped if the author wants the solution
      deployable via non-mcp-app tooling — these are additive,
      not a commitment to any platform
- [ ] Deployment sets `AUTH_ISSUER` and `ADMIN_EMAILS`, and the
      service's public URL is registered as the API identifier at the
      identity provider (`auth.md`)
- [ ] `APP_USERS_PATH` on persistent storage for durable deployments, and
      `REQUIRED_FS_TYPE` considered so a missing volume fails startup
      (`runtime-contract.md`)


## Compliance Dashboard

After all testing and validation steps are complete (including
the framework test suite), present the dashboard:

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
| Deploy | Runtime contract documented (Docker example or equivalent) | ❌ |

✅ = conforms  ❌ = missing/wrong  ⚠️ = partial
```

**The solution is ready when `pytest tests/` passes with zero
failures.** The mcp-app test suite is the authoritative check —
if it passes, auth works, admin works, tools are wired, identity
is enforced, and the SDK has test coverage for every tool.

After presenting the dashboard:

1. If there are ❌ or ⚠️ items: "Want me to fix these?"
2. If all ✅: "This solution is ready for deployment."
