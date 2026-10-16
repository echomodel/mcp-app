# Framework version: pinning and upgrading

Read this when an app depends on mcp-app and you are reviewing it,
upgrading it, or changing mcp-app itself in the same session.

## Checking the mcp-app framework version

For any existing app that already depends on mcp-app, ensure
the installed version is current before proceeding. Check how
the dependency is declared (e.g., in `pyproject.toml`) and
whether it pins a specific version or commit.

## Release lines

| mcp-app | MCP Python SDK | Auth model |
|---|---|---|
| `v1.0.0` (last of the 1.x line) | `mcp>=1,<2` (`FastMCP`) | Shared `SIGNING_KEY`, self-issued user tokens |
| `v2.x` | `mcp>=2,<3` (`MCPServer`) | Standard MCP OAuth only: external issuer, `ADMIN_EMAILS`, no `SIGNING_KEY` |

An app pinned to `v1.0.0` must not also pin `mcp>=2`; an app on `v2.x`
must not pin `mcp<2`. mcp-app's own `pyproject.toml` carries the SDK
bound for its line, so an app that only pins `mcp-app` gets the right
SDK automatically. Moving an app from 1.x to 2.x is a deliberate
upgrade, not a routine pin bump: the deployment gains `AUTH_ISSUER` and
`ADMIN_EMAILS` and an identity provider set up per `auth.md`; it loses
`SIGNING_KEY`, `JWT_AUD`, `TOKEN_DURATION_SECONDS`, `/admin/tokens`,
the `tokens` CLI group and `connect --signing-key`; every user's
pasted token stops working and each user re-adds the server URL in
their client and signs in; tests built on minted admin JWTs move to
the `oauth_env` fixture (`testing.md`).

## Pin discipline (mandatory)

Every mcp-app solution app's `pyproject.toml` MUST pin
`mcp-app` to a specific released tag:

```toml
dependencies = [
    "mcp-app @ git+https://github.com/echomodel/mcp-app.git@vX.Y.Z",
]
```

**A loose pin** — `"mcp-app @ git+https://github.com/echomodel/mcp-app.git"`
with no `@ref` — is a defect, not a convenience. Loose pins
silently pick up whatever `main` HEAD is at install time, so:

- A passing build today may not reproduce tomorrow if `main`
  moves between installs.
- Integration tests prove nothing about a specific version
  combination — "the app passed against mcp-app's main at
  some unknown SHA" is not a result anyone can act on.
- Operators upgrading the app on a different machine get a
  different `mcp-app` than the one the author tested with.

If you find an app loose-pinned, treat it as a regression and
fix it before doing other work: change the pin to the latest
released `mcp-app` tag, reinstall, run the integration tests,
commit the pinned `pyproject.toml`.

## Upgrading the pin

When a new `mcp-app` release lands and the app should adopt it:

1. Update the `@vX.Y.Z` in `pyproject.toml`.
2. Reinstall: `pip install -e . --upgrade` (or for pipx-installed
   tools: `pipx install -e . --force`).
3. Run `tests/framework/` — the framework-conformance suite
   imported from `mcp_app.testing`. Failures here mean the app
   needs to adapt to an API change in the new mcp-app.
4. Run the app's own integration tests at BOTH the CLI and MCP
   layers — `<app>-admin tools list`, `<app>-admin tools call`,
   plus a raw JSON-RPC call against `<base>/` for stdio or
   HTTP. Unit tests against mocked adapters are not sufficient
   here; the loop is "real deployment + real CLI + real MCP
   round-trip + real tool data."
5. Only after both layers pass against the new tag: commit the
   pin update.

```bash
pytest tests/framework/ -v             # framework conformance
# ... CLI + MCP integration checks ...
git add pyproject.toml
git commit -m "chore: bump mcp-app pin to vX.Y.Z"
```

If `tests/framework/` does not exist, that's a separate
compliance gap — adopt the framework test suite (`testing.md`, Step 5) before doing the pin upgrade.

## When you're modifying mcp-app itself in the same session

If your task touches mcp-app (e.g., fixing a framework bug
while building an app against it), the workflow is symmetric:

1. Make and commit the mcp-app change. Add or update tests
   following the SDK-layer pattern already in
   `mcp_app.testing.*` and `tests/unit/` — async adapter
   tests using `httpx.AsyncClient(transport=ASGITransport(...))`
   wrapped in `async with mcp.session_manager.run():`. HTTP
   and MCP-protocol behavior is testable in-process at the
   SDK layer; new test categories should not be introduced
   without deliberate cross-repo discussion.
2. Bump mcp-app's `__version__` + `pyproject.toml` per
   mcp-app's `CONTRIBUTING.md` versioning rules.
3. Push to `main`.
4. Tag `vX.Y.Z` per mcp-app's release workflow and push the
   tag.
5. Update this app's pin to the new tag and commit the change.
6. Reinstall this app against the new pin and run the app's
   own tests. CLI-layer bridge regressions (the CLI's
   `asyncio.run` boundary that wraps SDK calls) are structural
   patterns rather than test-covered behavior — review them
   in code review, not via a new test category.

