---
name: mcp-app
description: "Use when building, extending, reviewing, testing, deploying, operating, or debugging an MCP server project: starting a new server or web API, choosing a Python MCP framework, making a server multi-user, setting up a per-user data store, adding or changing tools, adding HTTP hosting or auth, managing users and credentials, writing tests, registering a server with an MCP client, or fixing your own server's failures (401 or 403 errors, tools not listed, client can't connect). Covers mcp-app, a Python framework serving one codebase over stdio and authenticated multi-user HTTP, with standard MCP OAuth sign-in, an admin CLI for users and deploy checks, and tests for an app's auth and wiring. Also use when migrating a server onto mcp-app, upgrading its pinned version, reviewing a repo built on it or asking if it is ready to deploy, testing tool descriptions with an agent, connecting its admin CLI, adding or revoking a user, rotating credentials, setting up the identity provider, or verifying a fresh deployment."
---

# mcp-app

mcp-app is a Python framework for MCP servers. An app declares one `App`
object pointing at a module of plain async functions. mcp-app turns those
functions into MCP tools and serves them over stdio for one local user or
over HTTP for many users who sign in with the operator's identity
provider. Every app gets the same admin CLI for users and deployment
checks, plus free tests for auth and wiring. This skill covers building, reviewing, deploying, operating, and
debugging such apps.

## Check fit before anything else

This skill loads for most MCP server work, and much of that work doesn't
need it. Look at the project first: `pyproject.toml` dependencies, imports,
entry points, and which transports it serves.

- **Already built on mcp-app** (depends on `mcp-app`, has `App(...)`):
  fit. Continue.
- **Not Python:** not a fit.
- **On another framework** (standalone `MCPServer`/FastMCP, the low-level `mcp` SDK, a
  TypeScript SDK) **and the conversation has no migration, refactor, or
  major new scope:** not a fit.
- **stdio-only, single user, no hosting plans in view:** not a fit. A
  stdio server that may be hosted later is a fit: mcp-app makes that a
  config change instead of a rewrite.
- **Operating or troubleshooting a deployed mcp-app instance the user
  runs** (its `*-admin` CLI is installed, a saved
  `~/.config/{name}/setup.json` exists, or the user says it's theirs),
  even with no repo checked out: fit. This includes their own connector
  failing with a 401, 403, or "failed to connect".
- **Client-side only** (editing `.mcp.json`, `claude mcp add` for someone
  else's server, a hosted connector the user doesn't operate): not a fit.
- **A new server, or major new scope on an existing one** (HTTP hosting,
  multi-user, auth, user management): fit. Offer mcp-app once, with its
  tradeoff (an opinionated framework and its admin model, in exchange for
  auth, users, and tests you don't write), and accept a no.

**When it's not a fit, stop using this skill.** Don't mention mcp-app and
don't suggest migrating. Carry on with the task as if this skill hadn't
loaded. A skill that loads broadly must not turn every MCP task into a
pitch.

Working inside the mcp-app framework repo itself? Its `CONTRIBUTING.md`
governs. This skill is for apps built on the framework.

## Rules that hold in every task

1. **SDK first.** All behavior lives in the SDK layer. Tools and CLI
   commands are thin wrappers. Logic in a tool belongs in the SDK.
2. **No caller-named host paths over HTTP.** A tool that reads a file path
   the caller supplies is an arbitrary server-file read when served over
   HTTP. Accept bytes or an upload URL instead, and put any host-path
   convenience in a separate `@mcp_transport("stdio")` tool.
3. **mcp-app holds no secret.** Auth is standard MCP OAuth against an
   external identity provider: the deployment sets `AUTH_ISSUER` and
   `ADMIN_EMAILS`, nothing else. Never add a signing key, a token store,
   or a pasted-token path; a 1.x `SIGNING_KEY` is a migration item.
4. **Data must survive restarts.** `APP_USERS_PATH` points at persistent
   storage in any durable deployment. Recommend `REQUIRED_FS_TYPE` so a
   missing volume fails startup instead of silently losing data.
5. **Pin mcp-app to a released tag** (`@vX.Y.Z`). A loose git URL is a
   defect.
6. **mcp-app doesn't deploy.** Apps describe a runtime contract and stay
   deployment-agnostic unless the repo has deliberately committed to a
   platform. With no deployment guidance in the environment or the repo,
   ask the user; don't improvise with raw cloud CLI commands.
7. **Verify with the admin ladder, not `curl`.** `/health` proves the
   process is up. `connect`, then `probe` prove the OAuth front door; a
   sign-in from a real MCP client and a tool call prove it serves tools.
   Never fall back to weaker checks.
8. **The solution's docs must stand alone.** After any authoring or review
   pass, the app's README and CONTRIBUTING carry every journey in
   app-specific terms, so no agent needs this skill to work on the repo.
9. **Every profile field has `Field(description=...)`.** Those descriptions
   become the admin CLI's help text, which is how an operator months later
   learns what a credential is and where to get a new one.

## The shape of an app

```python
# my_app/__init__.py
from mcp_app import App
from my_app.mcp import tools          # plain async functions calling the SDK

app = App(name="my-app", tools_module=tools)
```

```toml
# pyproject.toml
dependencies = ["mcp-app @ git+https://github.com/echomodel/mcp-app.git@vX.Y.Z"]

[project.scripts]
my-app-mcp = "my_app:app.mcp_cli"       # serve (HTTP), stdio --user local
my-app-admin = "my_app:app.admin_cli"   # connect, users, health, probe, register

[project.entry-points."mcp_app.apps"]
my-app = "my_app:app"
```

API-proxy apps add a Pydantic `profile_model` holding each user's backend
credentials. Data-owning apps scope storage by `current_user.get().email`.

## Lifecycle and journeys

An app moves through three stages: **author** (code and local validation),
**deploy** (owned by the operator's environment, not by mcp-app), and
**operate** (connect, verify, manage users, register clients).

Its docs must support six recurring journeys: (1) install and quick start,
(2) run locally over stdio, (3) deploy over HTTP, (4) connect the admin
CLI after deploy, (5) manage users and credentials, and (6) sanity-check
the deployment and connect end users. Developers walk all six once.
Operators return to 4 through 6 for every rotation, user, and redeploy.

## Where to go next

Read only the reference that matches the task. All live in `references/`.

| Task | Reference |
|------|-----------|
| Build a new solution, migrate one onto mcp-app, or change its structure, `App`, tools, safe tool, or extra HTTP routes | `authoring.md` |
| Who is calling a tool; per-user data; declare or change the profile model | `identity-and-profile.md` |
| Write or run tests: SDK, full-stack HTTP, stdio, the framework suite | `testing.md` |
| Check that an agent uses the tools correctly from their descriptions alone | `agent-evals.md` |
| Review a solution, answer "is this ready?", present the compliance dashboard | `review-checklist.md` |
| Check, pin, or upgrade the mcp-app version; change mcp-app in the same session | `framework-version.md` |
| Env vars, storage, `/health`, running over HTTP, containers, deploy routes, the deploy boundary | `runtime-contract.md` |
| Identity provider setup, `AUTH_*` and `ADMIN_EMAILS`, the 401/403 contract, how a client signs in, admin access on a deployment | `auth.md` |
| Set up or fix an Auth0 tenant for an app with the `auth0` CLI, no dashboard clicks: tenant flags, CIMD, connections, the email Action, per-app API and third-party access, traps | `auth0.md` |
| Connect the admin CLI, verify a deployment, add or revoke users, rotate credentials, register clients | `operate.md` |
| Something is broken: 401/403, failed to connect, missing tools, server won't start | `troubleshooting.md` |
| Write or review the solution's README, CONTRIBUTING, agent context files, `.gitignore` | `app-docs.md` |

## Closing out a session

Every authoring, migration, or review session ends the same way, even a
review that found nothing:

1. **For greenfield or migration, run the final self-sufficiency check**
   in `app-docs.md`. The pass isn't finished until the solution repo's
   own docs carry every journey.
2. **Validate locally.** Unit tests pass. The framework suite in
   `tests/framework/` passes. If the session touched tools, the SDK, the
   `App`, or entry points, run a stdio smoke test against an editable
   install (`testing.md`).
3. **Report** pass or fail per suite, plus what was built, changed, or
   found.
4. **Offer the next step** and wait for the answer:
   > Local validation is green. Would you like to:
   > (a) check the health and usability of an existing deployment,
   > (b) deploy the current code,
   > (c) manage users or rotate credentials on a deployment,
   > (d) register an MCP client against a deployment, or
   > (e) stop here?

   On (e) the session ends. Don't run cloud checks nobody asked for.
5. **(a), (c), and (d) need a known deployment URL.** Look for it in the
   admin CLI's saved `connect` config, the app's README, CONTRIBUTING, or
   `CLAUDE.md`, or a deployment skill paired with the app. **(b) needs a
   deployment**, which this skill doesn't do: follow the deploy boundary in
   `runtime-contract.md`. If no URL turns up for (a), (c), or (d), follow
   the same consult order there: the operator's environment, then the
   repo, then the user.
6. **Once the URL answers `/health` with `healthy` or `degraded`,** go
   straight to `operate.md` and climb its ladder from `connect`. Beyond
   that one health check, don't reach for cloud CLIs, cloud-provider or
   deployment-tool MCP tools, or `curl`; the ladder is the route.
