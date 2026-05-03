# Contributing to mcp-app

## Terminology: the test suite mcp-app ships

mcp-app ships reusable test modules (`mcp_app.testing`) that any
implementing app imports and runs against itself to check auth, user
admin, JWT enforcement, CLI wiring, and tool protocol compliance.

**In user-facing prose, lead with the value:** "free tests that check
auth and user admin work for your app." Don't lead with jargon. The
formal industry term is "conformance suite" (also called "compliance
suite" or "TCK" — Test Compatibility Kit). Use these terms
parenthetically at most, never as the primary label. The test modules
are organized by what they check (`iam/`, `wiring/`, `tools/`,
`health/`), not by abstract testing methodology.

**Avoid:** "contract tests" (implies Pact-style consumer-driven
testing, which this is not), "verification tests" (redundant — all
tests verify), "framework tests" (sounds like it tests the framework
rather than the app).

**Prefer:** "tests from mcp-app that check [specific thing]" or
"free tests for auth and admin" or just reference the subsystem
package name directly.

### Every mcp-app change must be reviewed against both skills

This repo ships two skills under `skills/`:

- **`author-mcp-app`** — the primary guide agents and developers
  use to build, migrate, and review apps on this framework.
- **`mcp-app-admin`** — the guide for operators and agents
  managing deployed mcp-app solutions (connect, verify, users,
  tokens, MCP client registration).

Any change to mcp-app — new features, API changes, behavioral
changes, new configuration, new testing patterns, new CLI
commands, changed admin endpoints — must be accompanied by a
review of both skills to ensure they capture the change. If
the skills don't reflect the current framework, agents will
build or operate apps wrong.

This includes changes to: the `App` class, `mcp_app.testing`
modules, CLI factories, middleware, store protocol,
identity enforcement, admin endpoints, entry point conventions,
and deployment patterns. If it affects how an implementer
integrates, configures, tests, deploys, or operates — the
relevant skill(s) must be updated in the same change.

The skills are part of the product. Changes to mcp-app that
don't update the skills should be treated as incomplete — the
skills are what agents use to build correctly and operate
safely on the framework.

## Documentation hygiene

mcp-app's documentation lives in three tiers. Each tier has a
specific audience and a non-negotiable self-sufficiency rule.
Maintaining these tiers correctly across changes is how the
framework stays usable without an agent having every piece of
context loaded.

### The three tiers

**1. Framework docs (this repo)** — `README.md` and
`CONTRIBUTING.md`. Audience: framework users (app authors),
operators of mcp-app solutions, and framework contributors.
The README covers: what mcp-app is, quick start, env vars,
identity and profiles, admin endpoints, testing, running,
deployment, user management, MCP client configuration,
architecture. CONTRIBUTING covers: terminology, architectural
decisions, skill maintenance (this file), testing patterns,
and dependencies.

**2. Skills (this repo, `skills/`)** — `author-mcp-app` and
`mcp-app-admin`. Audience: agents (Claude Code, Gemini CLI,
any agentskills.io-compatible environment) working with
implementing apps. These are installed into an agent's skill
directory, typically as symlinks back to this repo. They
operate in *other* repos (the implementing app's repo) and
therefore **must not assume the framework README or
CONTRIBUTING is loaded into the agent's context**. Every piece
of information a skill needs to act correctly must be in the
skill itself.

**3. Implementing app docs (external repos)** — every app
built on mcp-app has its own `README.md` and `CONTRIBUTING.md`.
Audience: users installing the app, operators running and
managing it, and contributors modifying it. **Implementing
app docs must be self-sufficient without any mcp-app skill
loaded** — a reader arriving cold must be able to install,
configure, run, deploy, verify, administer, and contribute.
Skills are an optional accelerant referenced in a footer at
most, never a prerequisite.

### Maintenance rules

**Deployment-agnostic default posture is maintained across all
three tiers.** The framework README, the `author-mcp-app`
skill, and implementing app docs all default to describing a
runtime contract rather than prescribing a deployment target.
The three-part framing (agnostic default / where deployment
config actually lives / opinionated-tooling alternative) lives
in the framework README and must be mirrored in the
`author-mcp-app` skill. If one drifts, the other will too.

**skill-author guidelines govern skill frontmatter and
cross-references.** Both skills must comply with the
agentskills.io-based `skill-author` guidelines: imperative
"Use when..." descriptions with synonym coverage, no
disqualifying platform language in the description, pure
instructions (no bundled scripts), and hint-level cross-skill
references (never dependencies). The two skills in this repo
are co-packaged and may reference each other, but references
to external skills (e.g., `setup-agent-context`) must be
hint-level with self-contained fallback content inline.

**Skills must be self-contained.** When adding content to a
skill that sits alongside content in the README, do not write
"see the README for details" — the agent won't have it.
Duplicate the essential content into the skill. The README can
stay the authoritative source for framework contributors; the
skill is the authoritative source for agents authoring or
operating apps elsewhere.

### Audiences

Each artifact serves a primary audience. Cross-audience
content is fine but secondary — the artifact's *primary*
audience determines tone, depth, and what counts as
"complete." The legend used in the charter table below:

- **H** — humans reading the README to evaluate, install, and
  use mcp-app or an mcp-app solution. They are looking at the
  rendered repo on GitHub or in their editor.
- **AA** — *author agents*: AI coding agents loading the
  `author-mcp-app` skill while working on an implementing app's
  repo. They do not have mcp-app's README in context.
- **OA** — *operator agents*: AI coding agents loading the
  `mcp-app-admin` skill to operate a deployed mcp-app instance.
  They also do not have mcp-app's README in context.

The skills are self-contained because of AA and OA: an agent
loaded into a different repo cannot follow "see the README"
links — the README isn't there. So duplication between README
and skills is intentional. The charter assigns one *canonical
source of truth* per topic; other artifacts may carry "Full"
treatment too if their audience needs the full content
in-context, "Summary" if a compressed version suffices, or
"Pointer" if the audience is co-located with the canonical
source.

### Charter — single source of truth per topic

This is the explicit charter for which artifact owns each
topic. The "SoT" (source of truth) column is authoritative for
maintenance: when content changes, the SoT moves first; other
artifacts are reconciled to it. Each row represents an
identifiable topic an agent or human might look up.

Legend for the per-artifact columns:

- **Full** — complete, self-contained treatment.
- **Summary** — compressed but actionable; reader can act
  without needing the SoT in front of them.
- **Pointer** — brief mention plus a forward link/section
  reference. Only works when the consuming audience has the SoT
  loaded (e.g., human reading the same repo).
- **Referenced** — the artifact mentions the topic exists but
  defers to the SoT. Equivalent to "Pointer" but for cases
  where the audience may not have the SoT loaded — the
  reference is informational only.
- **Implicit** — the topic is enforced by the artifact's
  posture or examples, not stated explicitly.
- **—** — not present (and the audience doesn't need it).

| Topic | SoT | README | `author-mcp-app` | `mcp-app-admin` |
|-------|-----|--------|------------------|-----------------|
| Value proposition / what mcp-app is | README | Full | Pointer | — |
| Install (the framework) | README | Full | — | — |
| Quick start (minimal app) | README | Full | Full | — |
| Two app patterns (data-owning vs API-proxy) | README | Full | Full | Implicit |
| Tool discovery rules | README | Full | Full | — |
| Environment variables (canonical table) | README | Full | Full | Referenced |
| Data storage (path resolution + storage contract) | README | Full | Summary | Referenced |
| Startup `data_dir` log line + fields | README | Full | Summary | Referenced |
| `REQUIRED_FS_TYPE` assertion (matching, behavior, opt-in posture) | README | Full | Summary | Summary |
| User Identity and Profile (concept + ContextVar) | README | Full | Full | Referenced |
| Profile model declaration (`profile_expand`, fields) | README | Full | Full | — |
| Admin REST endpoints (the API contract) | README | Full | Referenced | Referenced |
| `SafeTool` declaration (`App.safe_tool`) | README | Summary | Full | Referenced |
| `SafeTool` authoring rules (low-info-density) | `author-mcp-app` | Summary | Full | Pointer |
| `tools` subcommand group (CLI shape) | README | Summary | Referenced | Full |
| Local testing (httpx ASGI transport) | README | Full | Full | — |
| Running the server (stdio + HTTP) | README | Full | Summary | — |
| Runtime contract (start command, ports, endpoints) | README | Full | Full | Referenced |
| Deployment posture (agnostic-default, opinionated alt.) | README | Full | Full | Implicit |
| Docker / Cloud platform examples | README | Full | Pointer | — |
| Post-deploy verification ladder (probe → tools → safe-tool) | `mcp-app-admin` | Summary | Summary | Full |
| Six-journey map | `author-mcp-app` | — | Full | Journeys 4–6 |
| Connect — local vs remote, generic vs per-app CLI | `mcp-app-admin` | Summary | Pointer | Full |
| User management CLI commands (operational) | `mcp-app-admin` | Summary | Pointer | Full |
| Token lifecycle (issuance, revocation, rotation) | `mcp-app-admin` | — | — | Full |
| Signing-key retrieval per deploy tool | `mcp-app-admin` | — | Pointer | Full |
| Troubleshooting decision tree | `mcp-app-admin` | — | — | Full |
| MCP client configuration (stdio + HTTP examples) | README | Full | Pointer | Referenced |
| `register` command output handling | README | Full | Full (auth-side) | Full (ops-side) |
| Architecture (FastMCP+Starlette wrap, ASGI) | README | Full | Pointer | — |
| Free tests / conformance suite (how to adopt) | README | Full | Full | — |
| Conformance suite internals (how it's built) | CONTRIBUTING | — | — | — |
| Architectural decisions and rationale | CONTRIBUTING | — | — | — |
| Framework contributor workflow (release, tests) | CONTRIBUTING | — | — | — |
| Skill installation, scope, when to invoke | README | Full | — | — |
| Skill self-obsolescence design goal | `author-mcp-app` | Summary | Full | Implicit |
| Compliance checklist for implementing apps | `author-mcp-app` | — | Full | — |
| Repository structure for implementing apps | `author-mcp-app` | — | Full | — |
| Implementing app README skeleton + skeleton rules | `author-mcp-app` | — | Full | — |
| Implementing app `CONTRIBUTING.md` guidance | `author-mcp-app` | — | Full | — |
| Test patterns (httpx ASGI walk-throughs) | `author-mcp-app` | Summary | Full | — |
| Pre-deploy `gitignore` baseline | `author-mcp-app` | — | Full | — |

When changing the SoT for a topic, the change must reach every
other artifact that carries "Full" or "Summary" treatment in
the same PR. "Pointer" and "Referenced" cells track the SoT
naturally when contributors update the link target, and
"Implicit" cells need only be reviewed when the change shifts
the artifact's posture.

When a topic is missing from the table, that's a charter gap —
the contributor adding the topic must update this table in the
same PR.

### Single-sourced where feasible

Not everything duplicates. These live in exactly one place:

- **Architectural decisions and rationale** — CONTRIBUTING.md
  only. Skills reference outcomes ("signing key has no
  default"), not the decision history.
- **Conformance suite internals** — CONTRIBUTING.md only.
  Skills teach how to adopt the suite, not how it's built.
- **Framework contributor workflow** (running tests, releasing,
  version bumps) — CONTRIBUTING.md only. Agents authoring
  apps don't need this.
- **Skill-author guidelines** — a separate cross-cutting skill
  (`skill-author`). Neither of this repo's skills duplicates
  those rules; they inherit them.

### Every change touches the docs layer

When reviewing a PR to mcp-app, ask:

1. Does this change affect how app authors integrate, configure,
   test, or deploy? → `author-mcp-app` skill must be updated.
2. Does this change affect how operators connect, verify, or
   manage a deployed instance? → `mcp-app-admin` skill must be
   updated.
3. Does this change alter the runtime contract, env vars,
   endpoints, or admin API? → Framework README must be updated,
   and both skills reviewed for the same changes.
4. Does this change introduce or remove a known duplication?
   → Update the table above.

The skills are symlinked into agent skill directories in
development setups, so edits land live — there's no reason to
defer a skill update to "after the code change merges."

### The test suite is the acceptance criteria

Any change to mcp-app must pass `make test` (which runs both
mcp-app's own unit tests AND the test suite against the fixture
app). If a change breaks a test module in `mcp_app.testing`, it
breaks every implementing app's test run — that's the point.

For implementing apps, the test suite passing is the definitive
confirmation that the app is correctly built. The `author-mcp-app`
skill uses this as its final step: adopt the test suite, run it,
confirm zero failures. If it passes, auth works, admin works,
tools are wired, identity is enforced.

## Version Management

**Single source of truth:** `mcp_app/__init__.py` contains
`__version__`. `pyproject.toml` mirrors it. Both must move
together in the same commit.

### When to bump

Bump in the same commit as the change. `pip install --upgrade`
and `pipx install --upgrade` only re-install when the version
number rises, so without a bump downstream installs stay on the
old code.

| Change type | Bump |
|-------------|------|
| Bug fix, internal cleanup | patch (0.3.0 → 0.3.1) |
| New endpoint, new CLI command, new framework feature | minor (0.3.0 → 0.4.0) |
| Removed/renamed admin endpoint, change to `App` constructor signature, change to admin REST contract, breaking change in `mcp_app.testing` | major (0.3.0 → 1.0.0) |

Documentation-only changes don't need a bump.

The conformance suite (`mcp_app.testing`) is part of the public
contract — implementing apps import its modules in their
framework tests. Any change that breaks an existing import or
test name is a major bump.

### Catch-up bumps

If a runtime-touching change shipped without a bump (the rule was
missed), fix it with a small follow-up commit titled
`Bump version to X.Y.Z`. No `chore:` prefix, no Conventional
Commits ceremony — mcp-app does not run `semantic-release` or
similar tooling. The commit body should briefly note what
unreleased changes the bump covers.

### Release workflow

```bash
# 1. Update __version__ in mcp_app/__init__.py
# 2. Update version in pyproject.toml to match
# 3. Commit (bump together with the change, OR as a catch-up commit)
git add mcp_app/__init__.py pyproject.toml <other-files>
git commit -m "<change description>"

# 4. Tag (annotated)
git tag -a vX.Y.Z -m "vX.Y.Z"

# 5. Push (with tags)
git push origin main && git push origin vX.Y.Z
```

## Architectural Decisions

### Agent-composed over provider-coupled (admin tools)

The original design proposed a provider plugin system where mcp-app internally
discovers deployment backends. This was rejected in favor of stateless admin
tools that the AI agent orchestrates externally.

**Reasoning:**
- The agent IS the orchestrator — building a second integration layer in code
  adds coupling for no benefit
- MCP's design intent: tools are stateless, self-describing, composed by the
  caller
- Unix philosophy: small tools, agent-composed. Neither mcp-app nor deployment
  tools know about each other
- The deploy→verify→manage workflow happens naturally when agents call tools
  in sequence

**What this means in practice:**
- RemoteAuthAdapter is stateless — takes a URL and signing key, makes REST calls
- MCP admin tools take `base_url` and `signing_key` as explicit parameters
- No internal references to gapp, Cloud Run, or any deployment tool
- The admin tools don't know how the service was deployed or where the signing
  key came from

### cwd is never used for deploy or admin

App-specific CLIs (`my-app-mcp serve`, `my-app-admin`) get their config
from Python args — they work from any directory. The `mcp-app` generic
CLI is for remote admin (connect, users, health) when you don't have the
app's own admin CLI installed locally. No command depends on the current
working directory.

### Connection config is set once, used everywhere

Both the generic CLI (`mcp-app connect`) and per-app admin CLI
(`my-app-admin connect`) store the service URL and signing key
in a config file. Every subsequent command reads from that file.
No command except `connect` accepts `--url` or `--signing-key`
flags.

The per-app CLI also supports `connect local` for direct
filesystem store access. The generic CLI does not — it doesn't
know the app name, so it can't locate the store path
(`~/.local/share/{name}/users/`).

This is a deliberate design constraint. Repeating connection
credentials on every command is error-prone, clutters help text,
and teaches operators to paste secrets into shell history. The
`connect` command is the single entry point for connection
config — all other commands assume it's already configured.

The same principle extends to future CLI design (see
OPERATIONS.md's design principles on "url and signing-key as
first-class universals"). When adding new admin commands, they
read connection details from the existing config. They do not
accept their own `--url` or `--signing-key` overrides.

### Config vs problem-domain resources

`config` subcommands are for tool preferences (output format, storage backend,
keychain settings). Problem-domain resources (fleets, users, tokens) get their
own top-level command groups with CRUD operations. Never mix them.

**Test:** "If I deleted this, would I lose work or just a preference?"
- Preference → `config`
- Managed resource → its own command group

### Signing key storage

The fleetless admin path needs to persist a signing key locally.

- **Default:** OS keychain via `keyring` library (macOS Keychain, Windows
  Credential Manager, Linux Secret Service). Zero config on desktop platforms.
- **Fallback:** file-based storage in XDG config dir, chosen explicitly via
  `mcp-app config signing-key-store file`. Never a silent fallback — fail
  with an actionable hint if keychain is unavailable.
- **Escape hatch:** `MCP_APP_SIGNING_KEY` env var or `--signing-key` flag
  always work.
- **Fleet mode:** the deploy provider resolves the signing key from the cloud's
  secret store on demand. Nothing stored locally.

Note: current code writes to `active.json` in plaintext. This should migrate
to keychain-first once `keyring` is added as a dependency.

### Separate fleets over local override files

An earlier design used a gitignored `.fleet.local.yaml` that extended the
shared fleet manifest with local-only solutions. This was rejected because
any mechanism that layers config on top of shared state risks mutating it —
even "additive" changes to existing objects can be destructive (changing a
region, adding a config field that alters provider behavior, overriding a
secret reference).

Separate fleets eliminate this entirely. Each fleet is self-contained. Want
local docker instances? Put them in a `local` fleet. Shared Cloud Run
services? They're in `work`. They never mix, merge, or conflict.

### Credentials are the SDK's concern, not the framework's

Earlier designs had credential proxy middleware (`bearer-proxy`,
`google-oauth2-proxy`) that loaded backend credentials, refreshed
OAuth2 tokens, and rewrote HTTP Authorization headers. This was
built, shipped, and removed after deeper analysis:

- MCP tool functions don't read HTTP headers. The middleware rewrote
  a header nobody consumed.
- The SDK already knows what credentials it needs. An API-proxy SDK
  calls an external API — it knows whether it needs a bearer token
  or Google OAuth2. The framework adding a layer between "credential
  in store" and "credential in SDK" added coupling without value.
- Google's `google-auth` library handles OAuth2 refresh natively.
  The middleware was reimplementing what the SDK's own dependencies
  provide.

Credentials are stored in the user profile (loaded once at auth time
with the auth record). The SDK reads `current_user.get().profile` and
interprets the contents. mcp-app doesn't know what's in the profile.

### One user record, one store read

Auth fields (email, created, revoke_after) and profile data are
stored together in one record per user. The verifier loads the whole
record in one store read and sets `current_user` — no second read
for credentials or profile. The SDK reads what it needs from the
already-loaded record.

### Three CLI entry points per app

Apps generate three separate CLI entry points from one codebase:

- `my-app` — the app's own business CLI (optional, app-specific)
- `my-app-mcp` — `serve` and `stdio` (from `create_mcp_cli`)
- `my-app-admin` — `connect`, `users`, `tokens`, `health`
  (from `create_admin_cli`)

**Why three, not one:** The app's business CLI, MCP server commands,
and admin operations are different concerns with different audiences.
Mixing them in one CLI creates a confusing top-level command space.
Separating them lets each be self-contained — `my-app-admin` can be
used by an operator who doesn't need the app's business commands.

**Why `admin` is separate from `mcp`:** Admin manages users (add,
list, revoke). MCP runs the server (serve, stdio). An operator
managing users on a deployed instance doesn't need serve/stdio. A
developer running the server locally doesn't need user management
commands in the same CLI. Different jobs, different tools.

**Why `admin` is separate from the app CLI:** Admin has its own
config (`connect local` or `connect <url>`). If admin commands
shared the app's CLI, that config could conflict with or leak into
the app's own configuration. `gwsa admin connect https://...`
should never affect `gwsa drive search`. Separate entry points
mean separate config scopes — admin writes to its own setup file,
the app CLI never reads it.

### Only admin operations use a remote service URL

Admin operations (the admin CLI) are the only mcp-app component
that talks to a deployed instance's URL. Everything else works
without any knowledge of a deployment URL:

- **`my-app-mcp serve`** — IS the server. Listens on a port.
- **`my-app-mcp stdio`** — local process, no network.
- **`my-app` (business CLI)** — calls the SDK directly. For
  data-owning apps, reads/writes the local store. For API-proxy
  apps, calls external APIs (Google, etc.) directly. No mcp-app
  server involved.
- **The SDK** — business logic only. Reads `current_user` for
  identity, calls external APIs or the local store. Never calls
  back to an mcp-app service.

The admin CLI learns the URL from `connect <url>` — the user
provides it once, it's saved to `~/.config/{app-name}/setup.json`,
and all subsequent admin commands use it. Neither the business
CLI nor the MCP server ever reads this config.

### UserAuthStore protocol — one interface, two backends

User management operations (add, list, revoke) go through the
`UserAuthStore` protocol. Two implementations:

- `DataStoreAuthAdapter` — wraps any `UserDataStore` for local
  filesystem (or any custom store). Direct store writes.
- `RemoteAuthAdapter` — wraps HTTP calls to a deployed instance's
  `/admin` endpoints.

The CLI calls `_get_auth_store()` which returns the right adapter
based on the `connect` config (local or remote URL). All user
management commands use the same interface — no branching in CLI
command code.

### `connect local` vs `connect <url>`

Both CLIs use `connect` to configure the admin target. Two modes:

- `connect local` — write directly to the local filesystem store.
  For stdio apps running on this machine. **Per-app CLI only** —
  requires the app name to locate the store path
  (`~/.local/share/{name}/users/`).
- `connect <url> --signing-key xxx` — talk to a deployed instance
  via HTTP admin API. For managing users on a remote server.
  Available on both the generic and per-app CLIs.

Both CLIs share a single `_connect_handler` implementation. The
generic CLI passes `app_name=None`, which gates off `local` mode
with a clear error message directing the user to the per-app CLI.

This is configured once and remembered in
`~/.config/{app-name}/setup.json`. Subsequent `users` commands
route automatically. The user doesn't think about local vs remote
on every command.

### Profile registration is optional

`register_profile(Model)` declares a Pydantic model for typed
profile validation. This is for API-proxy apps that need structured
per-user credentials. Data-owning apps (no per-user credentials)
skip it entirely — `user.profile` is `None`.

When registered with `expand=True`, the admin CLI generates typed
flags from the model fields (e.g., `--token`). When registered with
`expand=False`, the CLI accepts the profile as a JSON string or
`@file`.

### Partial-update validation runs against the merged profile

`users update-profile` is a partial-update operation: the user
provides one (or a few) field(s) to change, and the rest of the
stored profile is preserved. To make this work for profile models
with multiple required fields (and for cross-field
`model_validator`s), the CLI loads the existing stored profile,
merges the patch on top, and validates the **merged** result —
not the patch dict alone.

This means model validators see the actual post-update state and
can correctly reject patches that would leave the profile in an
invalid combined shape. Conversely, patches missing other required
fields are not rejected when the existing record already supplies
them.

The store layer still receives only the delta — the merge happens
again at the storage layer, where it has always merged correctly.
The CLI's merge is purely about validation.

### SIGNING_KEY has no default

Earlier versions defaulted to `"dev-key"`. This was removed because
the code is in a public repo — anyone who reads it can forge JWTs.
`SIGNING_KEY` must be explicitly set as an environment variable for
HTTP mode. Missing or empty raises `RuntimeError` at startup.

### /health is a liveness check, not a readiness check

The `/health` endpoint returns `{"status": "ok"}` with no auth
required. It exists for Cloud Run (and similar platforms) to confirm
the process is alive and accepting HTTP requests.

It does not check store connectivity, tool module loading, or
middleware wiring. Those happen at startup — if any of them fail,
the process crashes and the platform restarts it. A deeper readiness
check (e.g., "can I reach my database") would mean hitting the
store on every health ping, which is unnecessary I/O for a probe
that fires every 10 seconds. App-specific readiness checks belong
in the app, not the framework.

### Framework reports facts about its environment; it does not enforce policy

The startup `data_dir` log line and the optional `REQUIRED_FS_TYPE`
assertion follow a deliberate split: mcp-app reports — in plain
fields — what it found when it inspected the data directory at
startup (path, fs_type, free space, writable). It does not decide
whether the result is acceptable. The optional `REQUIRED_FS_TYPE`
env var is the operator's mechanism for declaring acceptability;
when set, mcp-app aborts on mismatch.

This split is the framework's general posture: any future
environment introspection (mount source, network reachability,
upstream credential validity, anything mcp-app could plausibly
inspect at startup) follows the same pattern. The fact gets
reported. A separate, opt-in operator declaration turns reporting
into enforcement. Defaulting to enforcement would tie the
framework to a particular deployment shape — `overlayfs` is
correct on a developer laptop running Docker for iteration, and
the framework cannot tell that situation apart from a production
deployment that meant to mount a volume but didn't.

The reverse principle is just as important: do not omit the fact
on the grounds that "we can't enforce it anyway." A reported fact
in the log is what lets an operator (or a log-scraping monitor) build
their own policy on top, even when the framework deliberately ships
no policy of its own.

### stdio identity comes from --user, not yaml

`mcp-app stdio --user local` specifies the user identity. There is
no config file for stdio identity. Identity is a runtime
argument, not a versioned config setting — putting it in yaml would
mean committing user choices to version control.

## What mcp-app Is

A config-driven framework for building and running MCP servers as HTTP
services (and eventually stdio). Solutions define tools as pure Python
functions. The framework handles everything else: FastMCP setup, tool
discovery, middleware, auth, admin endpoints, data stores, and serving.

### Core principle: zero framework imports in tool code

Tools are plain async functions. Docstrings become MCP tool descriptions.
Type hints become tool schemas. No `@mcp.tool()` decorators. The framework
discovers and registers tools automatically from the module passed to
`create_mcp_cli`.

How this works: `App` receives the tools module, finds all public
async functions via `inspect`, and calls `mcp.tool()(func)` on each one
(each wrapped with `_require_identity` first). The decorator still
runs — mcp-app just calls it for you so your tools module has no
framework coupling.

### What mcp-app provides

- `create_mcp_cli()` / `create_admin_cli()` CLI factories
- `create_app_cli()` factory for app-specific CLIs with typed profile flags
- Tool discovery from module path (public async functions)
- Store abstraction (`filesystem` built-in, custom via module path)
- Identity middleware (`user-identity`) — runs by default in HTTP mode
- Admin REST endpoints at `/admin` (register with profile, list, revoke, tokens)
- `current_user` ContextVar — `User` object with `.email` and `.profile`
- `register_profile()` — typed profile validation via Pydantic
- `UserAuthStore` protocol
- `UserDataStore` protocol + `FileSystemUserDataStore`
- `DataStoreAuthAdapter` bridge
- `JWTVerifier`
- `RemoteAuthAdapter` — stateless REST client for deployed instances
- MCP admin tools server (`mcp-app admin-tools`)

### What mcp-app does NOT provide

- Deployment (gapp or any container platform handles this)
- CLI scaffolding (solutions use Click directly)
- SDK scaffolding (solutions write their own)
- Dockerfile generation (gapp handles this)

## Two Transports: HTTP and stdio

A solution built with mcp-app works over both transports without code
changes. Same yaml, same tools module, same SDK.

### HTTP mode (`mcp-app serve`)

The full production stack:
- FastMCP wrapped with identity middleware (runs by default)
- Admin REST endpoints at `/admin`
- `current_user` set by verifier: full user record (auth + profile) in one store read
- uvicorn runs internally (port 8080 by default)
- Store wired and accessible via `get_store()`

### stdio mode (`mcp-app stdio`)

Local single-user mode:
- FastMCP runs over stdin/stdout
- No middleware, no admin endpoints, no ASGI layer
- `current_user` loaded from store using `--user` flag
- Store still wired — `get_store()` works the same way
- Tool discovery identical to HTTP — same module, same functions

**Why mcp-app matters for stdio:** Without it, solutions that want stdio
must use FastMCP directly with `@mcp.tool()` decorators and manual setup.
With `mcp-app stdio`, the same yaml-driven tool discovery works for both
transports. One build, two commands.

**When raw FastMCP is fine for stdio:** If the solution is stdio-only, has
no store, no identity concerns, and no plans for HTTP — raw FastMCP with
decorators is simpler. mcp-app adds value when the solution needs both
transports or uses the store/identity infrastructure.

### stdio identity

Identity in stdio mode is a simple string — there is no authentication.
The MCP client launches the process directly; if you can run the command,
you're in. The `--user` flag specifies which user record to load from
the store:

```bash
mcp-app stdio --user local
my-app-mcp stdio --user alice@example.com
```

`--user` is required. There is no yaml config for stdio identity —
it's a runtime argument, not a versioned setting. `mcp-app stdio`
refuses to start without it.

### Solution entry points

Solutions declare console scripts that invoke the `App`'s CLIs:

```toml
[project.scripts]
my-solution-mcp = "my_solution:app.mcp_cli"
my-solution-admin = "my_solution:app.admin_cli"
```

Users register with: `claude mcp add my-solution -- my-solution-mcp stdio --user local`

## Tool Discovery

The tools module is a Python module passed to `create_mcp_cli`. All
public async functions in it are registered as MCP tools:

```python
# my_solution/mcp/tools.py
from my_solution.sdk.core import MySDK

sdk = MySDK()

async def do_thing(param: str) -> dict:
    """Do the thing for the current user."""
    return sdk.do_thing(param)
```

- Function name → tool name (`do_thing`)
- Docstring → tool description shown to agents
- Type hints → input schema
- Functions starting with `_` are skipped
- Sync functions are skipped (only async)

This is the mechanism that eliminates `@mcp.tool()` decorators. The
decorator still runs internally — `App` calls `mcp.tool()(func)`
for each discovered function.

## Middleware and Identity

### How identity works

Identity middleware (`user-identity`) runs by default in HTTP mode. It:
1. Extracts JWT from Authorization header or `?token=` query param
2. Validates JWT signature and claims via `JWTVerifier`
3. Loads the full user record from the store (auth + profile, one read)
4. Hydrates the profile with the registered Pydantic model if available
5. Sets `current_user` ContextVar — available to all tool functions

The SDK reads `current_user.get()` and gets a `UserRecord` with `.email`
and `.profile`. One import, one call, typed access.

### Default behavior

If `middleware` is omitted from yaml (the common case), `user-identity`
runs automatically. To add custom middleware or disable auth:

```yaml
# Custom middleware — must include user-identity explicitly
middleware:
  - my_app.auth.RateLimiter
  - user-identity

# Explicitly no auth
middleware: []
```

### Why no credential proxy middleware

Earlier designs had `bearer-proxy` and `google-oauth2-proxy` middleware
that resolved backend credentials and rewrote HTTP Authorization headers.
These were removed because:

- **MCP tool functions don't read HTTP headers.** The middleware rewrote
  a header that nobody read. Tools call SDK methods, not HTTP endpoints.
- **Credentials are the SDK's concern.** The SDK knows what kind of
  credential it needs (bearer token, Google OAuth2, etc.) and how to
  use it. The framework shouldn't interpret credential contents.
- **One record, one read.** The user profile (which includes credentials)
  is loaded alongside the auth record by the verifier. No second store
  read needed. The SDK reads `current_user.get().profile` — already in
  memory.
- **Token refresh is the SDK's concern.** Google's `google-auth` library
  handles OAuth2 token refresh. The SDK refreshes explicitly before API
  calls and writes back to the store. mcp-app doesn't need to know about
  Google tokens.

The identity middleware handles authentication (who is this user?). The
SDK handles authorization and credential usage (what can this user do?
what backend token do they have?).

### Why pure ASGI middleware, not FastMCP's built-in auth

FastMCP provides `TokenVerifier`, `BearerAuthBackend`, and `ctx.client_id`.
We rejected these because:

- It couples the framework to FastMCP — mcp-app should work with any ASGI
  app
- `ctx.client_id` is only available inside MCP tool functions, not in the
  SDK layer
- The SDK would need to import FastMCP or bridge from `ctx.client_id` to a
  ContextVar per tool function

Pure ASGI middleware owns the ContextVar and sets it before any app code
runs. The SDK reads it. No bridging. No FastMCP imports in the SDK.

### Two app patterns — same middleware, different SDK behavior

Both data-owning and API-proxy apps use `user-identity` middleware (the
default). The difference is what the SDK reads from `current_user`:

**Data-owning** (echofit — food logs, notes):
```python
user = current_user.get()
store = get_store()
store.save(user.email, "daily/2026-04-10", entries)
```

**API-proxy** (some-third-party-api — wraps external API):
```python
user = current_user.get()
token = user.profile["token"]
resp = httpx.get("https://api.example.com/...",
                 headers={"Authorization": f"Bearer {token}"})
```

**API-proxy with OAuth2 refresh** (gwsa — wraps Google APIs):
```python
user = current_user.get()
creds = Credentials.from_authorized_user_info(user.profile)
if creds.expired:
    creds.refresh(Request())
    get_store().update_profile(user.email, json.loads(creds.to_json()))
service = build("gmail", "v1", credentials=creds)
```

## Store Architecture

### UserDataStore protocol

Generic per-user JSON storage: `load(user, key)`, `save(user, key, data)`,
`list_users()`, `delete(user, key)`.

### UserAuthStore protocol

What the auth framework needs: `get(email)`, `list()`, `save(record)`,
`delete(email)`. Operates on `UserAuthRecord` (email, created,
revoke_after).

### DataStoreAuthAdapter

Bridges `UserDataStore` → `UserAuthStore`. The full user record (auth
fields + profile) is stored under one key per user. One store read gets
everything — the verifier loads auth + profile together, sets
`current_user` with the complete record.

### Why two protocols

Auth doesn't know about app data. A MySQL app can implement
`UserAuthStore` against its customers table without ever using
`UserDataStore`. The bridge is optional convenience for simple
filesystem-based apps.

### User record structure

The adapter stores one record per user containing both auth fields and
the app profile:

```json
{
  "email": "alice@example.com",
  "created": "2026-04-01T00:00:00",
  "revoke_after": null,
  "profile": {"token": "some-third-party-api-pat-xxx"}
}
```

Auth fields (`email`, `created`, `revoke_after`) are managed by the
framework. The `profile` field is opaque to mcp-app — the SDK interprets
it. Both are loaded in one store read at auth time.

## Relationship to Other Packages

### gapp (deployment)

gapp deploys containers to Cloud Run. It doesn't know about mcp-app's
internals. mcp-app doesn't know about gapp. Neither imports the other.

### Skill and documentation decoupling

The `author-mcp-app` skill guides agents through building apps on
this framework. It must remain agnostic to deployment tools. It
may mention a deployment tool (e.g., gapp) parenthetically as one
option among several, but must never contain deployment-tool-specific
configuration, commands, or workflows. The skill describes the
app's runtime contract — what it needs from any environment — and
leaves the deployment tool's skill to handle the rest.

The same rule applies to README.md and all other documentation:
never make mcp-app docs intimately aware of any specific
deployment tool's internals. At most, a passing reference as an
example. Universal tools like Docker are the exception — Docker
examples serve both practical and illustrative purposes and don't
create coupling to a specific deployment platform.

The agent is expected to carry context between skills — it reads
the app's runtime requirements from the mcp-app skill, then reads
the deployment tool's skill, and maps one to the other. Neither
skill needs to know about the other's details.

### app-user (archived)

`app-user` was the original standalone auth library. mcp-app absorbed all
its code. The `app-user` repo is archived. Solutions use
`from mcp_app import ...`.

### gapp_run (legacy)

`gapp_run` is gapp's ASGI runtime wrapper that handled credential
mediation for API-proxy solutions. It's legacy — credential management
moved to the SDK layer (profile on `current_user`, SDK handles token
refresh). `gapp_run` remains for backward compatibility with solutions
that haven't migrated to mcp-app.

## SDK-First Architecture

All business logic lives in the core layer, not in CLI or MCP wrappers.

- `admin_client.py` — RemoteAuthAdapter, UserAuthStore over HTTP
- `cli.py` — thin Click wrapper, calls SDK, formats output
- `admin_tools.py` — thin MCP wrapper, calls SDK, handles tool schema

If you're writing logic in a CLI command or MCP tool handler, stop and move
it to the SDK.

## Testing and Local Validation

### The pattern: httpx ASGI transport

mcp-app and solutions built on it validate locally without running a
server, without Docker, and without any cloud dependencies. The key is
httpx's ASGI transport — it runs the full ASGI app in-memory:

```python
from my_app import app
import httpx

transport = httpx.ASGITransport(app=app)
client = httpx.AsyncClient(transport=transport, base_url="http://test")
```

`App` is the ASGI callable directly — the same object that
`my-app-mcp serve` gives to uvicorn and `uvicorn my_app:app` would
invoke. Giving it to httpx instead means the full stack runs
in-process: tool discovery, middleware, admin endpoints, store
wiring. No server process, no port binding, no cleanup.

**If it works in httpx ASGI transport, it works in uvicorn, it works in
Docker.** The ASGI app is the app. Transport is just how bytes get in
and out.

httpx is already a direct dependency of mcp-app (used by RemoteAuthAdapter),
so solutions get it for free. No extra dependencies to write tests.

### What to test in solutions

Solutions should validate their tools and auth flow locally:

```python
import os
import pytest
import httpx
from my_app import app

@pytest.fixture
def app_client(tmp_path):
    """Return an httpx client that runs the full ASGI app in-process."""
    os.environ["APP_USERS_PATH"] = str(tmp_path / "users")
    os.environ["SIGNING_KEY"] = "test-key"
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")

@pytest.mark.asyncio
async def test_admin_register_and_list(app_client):
    """Register a user via admin API, verify they appear in list."""
    # Mint an admin token
    import jwt as pyjwt
    from datetime import datetime, timezone, timedelta
    admin_token = pyjwt.encode(
        {"sub": "admin", "scope": "admin",
         "iat": datetime.now(timezone.utc),
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        "test-key", algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Register
    resp = await app_client.post(
        "/admin/users",
        json={"email": "user@example.com"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data

    # List
    resp = await app_client.get("/admin/users", headers=headers)
    assert resp.status_code == 200
    users = resp.json()
    assert any(u["email"] == "user@example.com" for u in users)
```

This tests the full stack: yaml config → tool discovery → middleware →
admin endpoints → store → filesystem. Same code path as production.

### mcp-app's own tests

mcp-app uses the same pattern internally:

```python
transport = httpx.ASGITransport(app=starlette_app)
http_client = httpx.AsyncClient(transport=transport, base_url="http://test")
client = RemoteAuthAdapter("http://test", signing_key, http_client=http_client)
```

RemoteAuthAdapter → httpx → ASGI → Starlette → admin.py → FileSystemUserDataStore → tmp_path.

### stdio validation

Register with an MCP client directly:

```bash
claude mcp add my-app -- mcp-app stdio
```

Claude Code launches the process and manages its lifecycle. No background
server, no port management, no cleanup. Call tools through the agent.

Use `--user` to select a specific user account for the session:

```bash
claude mcp add my-app -- mcp-app stdio --user alice@example.com
```

### What httpx ASGI transport validates

Everything that matters for deployment readiness:
- Tool discovery from the tools module
- Middleware auth (JWT validation, user identity)
- Admin endpoints (user registration, listing, tokens)
- Store wiring (per-user data, auth records)
- SDK business logic (your actual tools)

What it doesn't test (and doesn't need to):
- Port binding (trivial, uvicorn handles it)
- DNS/networking (transport plumbing, not app logic)
- Container startup (Dockerfile concern, not app concern)

## Dependencies

httpx is a direct dependency (used by RemoteAuthAdapter). It is also the #2 Python
HTTP client by downloads (~500M/month), maintained by Encode (author of Django
REST Framework and Starlette), and a hard dependency of every major AI SDK
(OpenAI, Anthropic, Google GenAI). It was already a transitive dependency via
starlette and mcp.
