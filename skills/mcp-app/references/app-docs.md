# The solution's own docs

Read this when writing or reviewing an mcp-app solution's `README.md`,
`CONTRIBUTING.md`, `CLAUDE.md`, `AGENTS.md`, or `.gitignore`, and before
finishing any greenfield build or migration.

Contents: journey map and audiences · design goal: the repo outgrows the
skill · documentation posture · what the docs must cover · bridging admin
and end-user content · distilling principles · README skeleton ·
CONTRIBUTING guidance · observed patterns · agent context files ·
`.gitignore` baseline

## User journey map

Every mcp-app solution is used by three audiences across six
recurring journeys. The map serves two purposes:

1. **Authoring context.** When building or reviewing an app,
   every journey below must work end-to-end. Missing journeys
   (e.g., no `probe`, no typed profile flags, no identity-provider
   setup notes) are compliance gaps.
2. **Documentation coverage.** The implementing app's README
   and CONTRIBUTING must walk readers through each journey in
   app-specific terms (see Documentation, below). The
   journeys below are what the docs must cover.

### Audiences

- **Developer** — builds or modifies the app; needs architecture,
  tests, compliance, and local validation.
- **Operator** — deploys the app, manages users, rotates
  credentials. May be the developer wearing a different hat, or
  a separate person months later.
- **End user** — registers the app with their MCP client and
  invokes tools. May be a human or an AI agent.

### The six journeys

1. **Install / quick start** — developer clones or installs
   the package, runs tests, confirms it works locally.
2. **Run locally (stdio)** — end user registers the app for
   stdio with their MCP client. May require a local user
   profile with credentials (API-proxy apps).
3. **Deploy (HTTP)** — operator deploys the app to a target
   platform with persistent storage, `AUTH_ISSUER` and
   `ADMIN_EMAILS` set, and the service URL registered at the
   identity provider.
4. **Connect admin CLI post-deploy** — operator runs
   `my-app-admin connect <url>` (no credential). Config persists
   per-app in `~/.config/{name}/setup.json`.
5. **Manage users and credentials** — operator adds users,
   rotates backend credentials via `users update-profile`,
   revokes access. Profile field names and descriptions drive CLI
   help text. On a deployment in 2.0 this goes through `/admin`
   with an administrator's token (`auth.md`); the CLI's `users`
   group runs against the local store.
6. **Sanity-check the deployment, connect end users** — split
   into two phases with different audiences:
   - **6a. Sanity-check the deployment** (admin only) — operator
     runs `probe` to confirm the OAuth front door (health,
     discovery document, 401 challenge). Independent of any
     specific user.
   - **6b. Connect an end user** (admin → end-user handoff) —
     operator runs `register` to produce the exact commands the
     end user pastes into their MCP client (Claude Code,
     Antigravity CLI, or Claude.ai web); the user then signs in
     with the identity provider. The admin and end user may be the
     same person (self-serve) or different people; either way,
     the output of `register` is consumed by an
     end-user-on-their-laptop persona, not the admin persona.

The developer typically walks all six during initial release;
the operator returns to journeys 4–6 for every credential
rotation, user addition, or deployment update. Docs must make
the returning operator's path frictionless — they land cold,
months later, without the skills loaded.

**Persona note.** Journeys 1, 2, and 6b have an end-user audience
(the person who will actually invoke tools from their MCP client).
Journeys 3, 4, 5, and 6a have an admin/operator audience. When the
same person plays both roles (the common case for personal
deployments), the docs must make hopping between the two halves
easy — see the "Bridging admin and end-user content" guidance
below.


## Design goal: the repo outgrows the skill

Authoring, reviewing, upgrading, deploying, and administering recur for
the life of an app. What can become unnecessary, per repo, is this skill.
An authoring, migration, or review pass must leave the solution repo's own
`README.md`, `CONTRIBUTING.md`, and agent context files (`CLAUDE.md`,
`AGENTS.md`) carrying everything this skill would have told an agent, in
app-specific terms: real CLI names, real profile fields, real commands. If
other relevant skills are loaded (a deployment tool's skill, say), absorb
their guidance the same way.

After the pass, an agent opening the repo with **no skill loaded** must be
able to install, run, deploy, redeploy, connect the admin CLI, manage
users, rotate credentials, register MCP clients, add or modify tools, and
run tests from the repo's files alone. The skill stays useful for the next
lifecycle event, for repos not yet brought up to this bar, and for
framework changes that no repo's docs have absorbed yet.

### Final self-sufficiency check

Before finishing a greenfield build or a migration, verify the bar:

1. Read the solution repo's `README.md` cold. Does it walk through all six
   journeys in app-specific terms, with real CLI names, profile fields,
   commands, and env vars? Does it avoid telling the reader to load or run
   a skill?
2. Read `CONTRIBUTING.md`. Does it teach how to add a tool, add or change a
   profile field, run tests, and meet mcp-app's compliance rules, without
   pointing back to a skill?
3. Confirm `CLAUDE.md` imports `@README.md` and `@CONTRIBUTING.md`, and
   `AGENTS.md` points to both.
4. Simulate three tasks for an agent with no skill loaded:
   - Add a tool that calls a new SDK method
   - Rotate a deployed user's backend credential
   - Redeploy a code change and verify the running instance
   If any can't be done from the repo's docs, fill the gap in the docs,
   not in conversation.

The pass isn't finished until this check passes. Skill-level content
that hasn't reached the repo's own docs in app-specific form is an
uncompleted handoff.


## Documentation

The implementing app's README.md and CONTRIBUTING.md must be
self-sufficient. A user, operator, or agent landing on the repo
should be able to install, configure, run, deploy, verify,
administer, and contribute without any mcp-app skill loaded and
without being told to install one. Assume the reader has none of the framework's
context in their head.

This is non-negotiable. The skill accelerates authoring and
operation when available, but an app whose docs only work when
paired with it is a broken app — most readers (human or
agent) will arrive without them.

### Default posture: deployment-agnostic, like mcp-app itself

mcp-app describes a runtime contract — env vars, start command,
endpoint paths, health and admin APIs — and leaves the
deployment tool or environment to map to it. Apps built on
mcp-app inherit that posture by default. The framework has
already given authors everything they need to stay
deployment-agnostic: an env-var-driven runtime, no hardcoded
paths, no platform-specific code, a standard Python package
that deploys wherever Python deploys.

In **greenfield authoring**, assume the user wants this. Docs
describe what the app needs from any environment. Show Docker
as a universal illustrative example if one is needed, but do
not prescribe a platform, a secret store, or a concrete path.
This lets the app be picked up and deployed by whoever needs
it without the docs arguing with their choice.

In **migrations and reviews**, check in-repo precedent before
assuming the default. If the repo has already committed to a
specific platform — platform-specific configs checked in,
deployment commands in the README, CI workflows that only
target one environment — the user may have deliberately coupled
the app to that platform. Don't force a refactor. Offer to
factor out the coupling if context suggests that's the user's
goal, or if they haven't considered the tradeoff, frame the
opportunity: "this app is currently coupled to X; making it
platform-agnostic would let anyone deploy it anywhere. Want to
refactor, or keep the coupling intentional?"

A user who is committed to a concrete platform expression —
because their org only uses one, because the app is meant for
a specific environment, because the coupling simplifies
something they care about — is making a valid choice. The
skill's job is to articulate the tradeoff, not overrule it.

### Where deployment config lives under the agnostic route

When an app stays deployment-agnostic, deployment decisions
and configuration live *separately* from the app repo — in
CI/CD workflows, ops repos, infrastructure-as-code modules,
or wherever environment-specific (but non-secret) settings,
build scripts, and deployment tooling belong. Help the user
see that the app repo stays focused on the app; their
deployment choices live wherever they normally manage that
concern. Agentic workflows operating on the deployment
environment will typically have additional skills or plugins
loaded for the deployment tooling, separate from the mcp-app skill
and from the app itself.

Connective tissue between sessions is retained by the mcp-app
admin CLI's per-app `connect` config — the deployed URL
persisted under XDG config paths
(`~/.config/{app-name}/setup.json`), always outside the
solution app repo. That state can be managed and versioned by
a dotfile manager or lifted into a separate, private
operator-owned repo if durability beyond a single workstation
is needed. Either way, it stays external to the solution app
repo. When reviewing or authoring, never suggest persisting
deployment metadata inside the solution app repo just because
it might be convenient — that's how reusable products get
their portability quietly stolen.

### The compatibility-artifact middle ground

Between "fully agnostic" and "opinionated in-repo tooling" sits
a third valid posture: **agnostic, with minimal compatibility
artifacts** that common deploy tools can consume.

A solution built on mcp-app is also a standard Python web
service. Shipping a tiny, platform-neutral artifact doesn't
commit the repo to a platform; it just makes the app consumable
by tools that need an entry-point hint. The artifacts that
matter:

- **`Procfile`** (one line): unlocks `gcloud run deploy
  --source .`, Heroku, Render, Fly, Railway, any Procfile-aware
  PaaS. Doesn't name any cloud vendor. Example:
  ```
  web: my-app-mcp serve --host 0.0.0.0 --port $PORT
  ```
- **`Dockerfile`** (minimal, ~5 lines): unlocks local
  `docker build`, any container platform, CI-built images.
  Doesn't pick a cloud or a registry.

These are *additive*. Opinionated deploy tools (e.g., a shipped `.tf` module for one
specific platform) bring their own containerization and ignore
these artifacts. Bare `gcloud` / Heroku / etc. consume them.
Every downstream consumer is happy.

**When to suggest shipping these:** when the solution is
publicly reusable and the author wants to minimize friction for
any would-be deployer. When authors say "I want this to work
with just `gcloud run deploy --source .`" — ship a `Procfile`.

**When to skip:** stdio-only apps; truly internal apps with a
single committed deploy path; apps whose deployment tool
generates its own build and should be the only path.

### The opinionated-tooling alternative — when and when not

A secondary route is to ship opinionated build and deployment
tooling *inside* the app repo: Dockerfiles beyond a minimal
illustration, CI workflow templates, Terraform modules
(`.tf` files) or other infrastructure-as-code, platform-specific
manifests, or configs for a particular deployment tool. Done
well, this tooling remains *operator-agnostic* — environment
specifics (project IDs, secret names, domains) and secrets
stay out of the repo; the configs describe how to build and
deploy without dictating where.

When to suggest or accept this route:

- The app is **internal, personal, or has a narrow audience**
  where authors and operators are closely aligned and the
  convenience outweighs the portability loss
- The user explicitly wants an opinionated path for themselves
  or a small team
- An in-repo precedent already exists and the user wants to
  extend it

When to push back or recommend against it:

- The app is being published as a **reusable public product**
  aimed at broad adoption — every in-repo tooling assumption
  is one more thing a would-be user has to agree with or work
  around
- The user hasn't considered the tradeoff and the repo's goal
  implies broad reuse (public visibility, generic naming,
  "framework"/"library"/"solution" framing)

When in doubt, frame the tradeoff plainly: in-repo opinionated
tooling is a convenience for aligned operators and a tax on
everyone else. Public reusable products usually skip it or
keep only a minimal Docker example. Private/internal apps may
reasonably include more.

### What the app's docs must cover — the six user journeys

The user journey map at the top of this file enumerates the six journeys
every mcp-app solution supports. The implementing app's docs
must walk readers through each journey in app-specific terms —
substituting the app's real CLI names, profile fields, env var
values, and deployment target. This skill is the source for
what each journey requires. The raw material to distill from
is in `identity-and-profile.md`, `runtime-contract.md`,
`auth.md`, and `operate.md`.

**1. Understand the app (README opener — why it exists)**

One paragraph: what problem does this app solve, and who is it
for. Name the backend system if it's an API-proxy (e.g., "wraps
the Example.com API"). Name the data domain if it's data-owning
(e.g., "tracks daily food logs"). Be concrete — an agent reading
this must be able to decide in three sentences whether the tool
is what it needs. Defer "how" to later sections.

**2. Install and run locally (stdio journey)**

For users who want to run the tool on their own machine:

- How to `pipx install` (or `pip install`) the app
- How to register with MCP clients for stdio
  (`claude mcp add`, `agy mcp add`, full command)
- Whether stdio mode needs per-user credentials and how to
  provide them (if the app has a profile model, describe
  how to set profile data for the `local` user — typically
  via `my-app-admin connect local` then `users add local`
  or `users update-profile local`)
- Smoke-test command or example tool invocation

If the app is HTTP-only (no stdio), say so at the top of this
section and point to the remote journey instead.

**3. Deploy (HTTP journey for operators)**

An mcp-app HTTP solution can deploy through multiple tools in
parallel. Documentation lists the paths the solution supports
as peers, without elevating one over the others.

**The runtime contract is non-negotiable.** Deploy-agnostic doesn't
mean deploy-silent. Every HTTP-capable solution must document what
it needs from any environment, regardless of which deploy paths it
supports. A solution that omits its runtime contract isn't usable
by any deploy tool — provider, operator, CI, or human.

Start with the runtime contract, scoped to this app — what it
needs from any environment. This applies to every deploy path:

- Required env vars the app reads
  (`AUTH_ISSUER` and `ADMIN_EMAILS` always; `APP_USERS_PATH`
  pointing to persistent storage; any app-specific env vars
  for data, config, or cache paths). Name the variables and
  what they mean. Don't prescribe concrete values that only
  make sense in one environment.
- Start command (`my-app-mcp serve`, optional
  `--host`/`--port`)
- Endpoint path (`/`, not `/mcp`), health path
  (`/health`), admin path (`/admin`)
- Auth model: standard MCP OAuth against the operator's
  identity provider, validated by the app itself; the
  platform must allow unauthenticated HTTP through to the
  app and forward `Host` unchanged. What to set up at the
  identity provider (API identifier = the service URL, dynamic
  client registration, email claim)

Then document each supported deploy path as a peer
subsection. Common options:

- `gcloud run deploy --source .` (if a `Procfile` ships)
- `docker build .` (if a `Dockerfile` ships)
- Any opinionated deploy tool the author has committed to

**No deploy path is canonical unless the author explicitly
chooses one.** Every supported path gets first-class treatment
with its own section, its own runnable commands, its own
post-deploy verification notes. Use Docker as a universal
illustrative example if one is helpful — a standard multi-stage
Dockerfile reaches every container platform.

If in-repo precedent shows the user has committed to a
specific platform (platform-specific configs checked in,
deployment tool already wired up, CI targeting one
environment), document that concretely as the primary path —
this is the user's choice and the docs should match. If the
repo shows no such commitment, stay agnostic and let the
reader's environment drive.

If the app's deployment is commonly paired with a specific
tool that has its own skill (e.g., gapp), mention the tool
by name and link to it, but don't assume the reader has
that skill loaded — link to the tool's own README or walk
through the manual steps.

**4. Connect the admin CLI (operator journey — post-deploy)**

This is the section most frequently neglected and most
valuable. A reader returning to the app months later to rotate
a credential must be able to re-discover the admin workflow from
this section alone:

- `my-app-admin connect local` vs `my-app-admin connect <url>`
- That `connect` takes no credential: mcp-app holds no secret,
  and the identity provider does the sign-in
- What "local" means for this app and when to use it
- The fact that `connect` persists config in
  `~/.config/{app-name}/setup.json` — subsequent admin
  commands don't repeat `--url`
- A reminder that `connect` and deploy are independent —
  deploying doesn't auto-connect the admin CLI
- Which admin commands work against a deployment today
  (`health`, `probe`, `register`) and how users are added to a
  deployment (an `/admin` call with an administrator's token
  from the identity provider), stated plainly

**5. Manage users and credentials (admin journey)**

Concrete commands for this app's profile shape:

- `users add` with this app's actual profile flags
  (`--api-key`, `--display-name`, `--default-region`,
  whatever the Pydantic model declares — credentials,
  preferences, or anything else). Show a real-looking
  invocation.
- How to discover profile fields from the CLI itself
  (`users add --help`) — this is the self-documentation
  path for agents operating the app
- `users update-profile` to change a specific field
  without re-registering
- `users get-profile` to read what's currently stored
- `users list`, `users revoke`
- Where to obtain the backend credential for this app's
  profile fields (the URL users visit to generate an API
  token, the OAuth flow, etc.). This belongs in the docs
  AND in the `Field(description=...)` on the profile
  model. Both exist for different audiences — CLI help
  for operators mid-task, README for operators onboarding.

**6. Sanity-check the deployment, connect end users**

- `my-app-admin probe` — what it checks and what good
  output looks like (admin-only; independent of any user)
- `my-app-admin register` — generates the per-client setup
  commands the end user runs to add the deployment to their
  MCP client; the client signs them in with the identity
  provider on first use
- Who gets in after signing in (`ADMIN_EMAILS` entries and
  registered users) and what a `403` means for everyone else
- Manual MCP client config as fallback (claude/agy
  `mcp add` commands with HTTP transport and the URL only;
  the Claude.ai custom-connector form)
- **Optional: live-tool smoke test.** For verification that
  goes deeper than `probe`, the implementing app's README may
  surface `safe-tool --invoke` (when the app declares a
  SafeTool) and/or `tools call <name>` for ad-hoc invocation
  as optional steps. Both are native admin commands; the
  verification ladder is in `operate.md` and SafeTool authoring
  in `authoring.md`.

### Bridging admin and end-user content

Several journeys hand off between an admin/operator audience and
an end-user audience. The clearest example is journey 6b: the admin
registers the user and runs `register`, which produces commands the
*end user* runs on their own machine to add the deployment to their
MCP client and sign in. Other handoffs work similarly — anywhere admin-produced
output is consumed by an end user.

When admin and end user are the same person doing both jobs (the
common case for personal deployments), readers shouldn't have to
hunt across non-adjacent README sections to follow the round trip.
Use markdown anchor links to bridge the two halves:

- **From admin sections forward to end-user sections.** When an
  admin step produces output an end user runs, end the admin
  subsection with a forward link to the end-user subsection that
  explains what to do with it.
- **From end-user sections back to admin prerequisites.** The
  end-user section should stand alone for a real end user reading
  it cold, but should reference what the admin must have already
  done (e.g., "Your admin must have registered your email, or you
  must be in `ADMIN_EMAILS`").
- **Use the literal section heading** the agent will produce as
  the link target. Markdown auto-generates anchors from headings
  (lowercased, spaces to hyphens, punctuation stripped) — verify
  the link resolves after writing.

### Principles for distilling, not copying

**App-specific over generic for things the app owns.**
Framework-level prose uses placeholders like `my-app-admin`
and `do_thing`. The implementing app's README uses the real
CLI name, real tool names, real profile field names. Substitute
throughout so every command is copy-pasteable verbatim. This is
always correct — it costs nothing and the app owns these names
regardless of where it's deployed.

**Agnostic over concrete for things the deployment owns.** The
app doesn't own `APP_USERS_PATH`'s value, secret storage
location, the platform, or orchestration details. Those are
environment concerns. Describe what the app needs from the
environment — not a prescribed value — unless the repo has
deliberately committed to a specific platform. "Set
`APP_USERS_PATH` to persistent storage" is the app's language;
"set it to `/data/my-app/users` mounted from a Cloud Run
volume" is the deployment's language, which only belongs in
the README if the app is explicitly coupled to that deployment.

**This app's shape, not the framework's shape.** If the app has
no profile model (data-owning), don't document profile flags or
profile update commands — they're irrelevant. If the app is
stdio-only, don't document HTTP deployment. Show only the
journeys that apply.

**Match the mcp-app framework, don't extend it.** Don't document
env vars, endpoint paths, admin commands, or behaviors the
framework doesn't actually provide. If the app needs something
extra (a custom env var, an app-specific CLI subcommand),
document it as an app-level addition, distinct from framework
behavior. When the framework changes, only the framework-level
paragraphs need updating across the fleet.

**No references to skills as prerequisites.** Never write "see
the mcp-app skill" or "run /mcp-app" as the primary instruction
for any step. The skill is an accelerant, not a prerequisite. A
pointer to it belongs in a footer section (see the skeleton
below), and even then only as an optional optimization.

**No "why we chose mcp-app" explanations.** The framework
justifies itself in its own README. The implementing app's
README is about using THIS app, not marketing the framework.
Mention the framework once in passing ("built on
[mcp-app](https://github.com/echomodel/mcp-app)") and move on.

**No bridges, no legacy callouts.** Don't document "we used to
do X, now we do Y" unless there's an active migration the
reader needs to navigate. Coherent product, not history exposé.

### README.md structure — recommended skeleton

```markdown
# my-app

<one-paragraph: what it does, who it's for>

## Install

<pipx or pip install commands, any system prereqs>

## Run locally (stdio)

<claude mcp add / agy mcp add commands>
<profile setup for the local user if applicable>

## Deploy

<env var table — AUTH_ISSUER, ADMIN_EMAILS, APP_USERS_PATH, app-specific>
<runtime contract: start command, ports, endpoint paths,
 auth model>
<Docker example as universal illustration — or, if the repo
 is deliberately platform-coupled, the concrete deployment
 route for that platform>
<identity provider setup: API identifier = service URL, dynamic
 client registration, email claim>
<post-deploy: connect admin CLI (URL only), probe>

## Manage users

<users add with this app's actual flags>
<users get-profile, users update-profile, users list, users revoke>
<how a user is added to a deployment today: /admin with an administrator's token>
<where to obtain backend credentials if API-proxy, or what each preference field controls>
<forward anchor-link to "Connect end users" — admin's next step once a user is added>

## Sanity-check the deployment

<probe — admin-only check that health, discovery document, and the 401 challenge are right>

## Connect end users

<register command — the per-client setup commands the end user runs; run register and document what it actually prints, don't paraphrase>
<who can sign in: ADMIN_EMAILS entries and registered users; everyone else gets 403>
<manual MCP client config as fallback>

## Smoke-test a tool (optional)

<my-app-admin safe-tool --invoke if the app declares a SafeTool, or my-app-admin tools call <name> for ad-hoc invocation>

## Configuration

<env var reference table>
<XDG paths this app uses>

## Further Reading

- [CONTRIBUTING.md](CONTRIBUTING.md) — architecture, testing, development
- Built on [mcp-app](https://github.com/echomodel/mcp-app)

## For agents: optional skill accelerant

If you're a coding agent that supports skills, the
[mcp-app skill](https://github.com/echomodel/mcp-app/tree/main/skills/mcp-app)
provides step-by-step workflows for authoring and operating
apps on this framework. It is optional — this README is
self-sufficient.
```

The footer skill mention is the only place the skill appears. It's
a footnote, not a dependency.

### CONTRIBUTING.md — architecture and maintenance

Covers what a contributor needs to change the app without
breaking compliance:

- Three-layer architecture (SDK / MCP / optional CLI) and
  the rule that business logic lives in the SDK
- Profile model location and the requirement that every
  profile field include `Field(description=...)` — this is
  the re-discovery mechanism for operators
- How to add an MCP tool (add an async function to the
  tools module — no decorators, no registration)
- How to add a profile field (update the Pydantic model,
  update `Field(description=...)`, update README's user
  management section, add or extend tests that cover
  profile handling)
- How to run the test suites — SDK unit tests and the
  mcp-app framework test suite (`pytest tests/framework/`)
- Editable-vs-snapshot install distinction for the live
  validation steps. Anything that runs `<name>-mcp` or
  `<name>-admin` from the local install — stdio smoke
  tests, release checklists, "does this work for me right
  now" sanity checks — must verify the install is editable
  before trusting its output. `<cli> --version` does NOT
  detect this; use `pipx list | grep -A5 <package>` and
  look for the `(editable)` marker. Remediate with
  `pipx install -e . --force`.
- Environment variable conventions and how to add
  app-specific XDG paths
- Where deployment configuration lives and what owns it
  (the deployment tool vs. the app)
- Release process. Version comes from `vX.Y.Z` git tags
  (setuptools-scm; add `.git_archival.txt` with `export-subst`
  when the deploy builds from `git archive`), never a
  hand-edited number. Bump: patch for fixes, minor for
  features; breaking changes on 0.x are minor; a new major only
  with the author's approval. Tag the reviewed commit, push it
  and the tag, then deploy that tag: the CI deploy runs against
  the tag ref, not a local deploy or a branch. Verify with
  `probe` and a tool call.
- Any app-specific design decisions that future
  contributors need to know (stored profile fields,
  refresh behavior, custom middleware if any)

Do not repeat the README. CONTRIBUTING is for contributors;
README is for users and operators. A link from CONTRIBUTING
back to README for "how users interact with this app" is
fine — duplication isn't.

### Patterns observed across existing mcp-app solutions

Use these as a reference when drafting — they're conventions
that have emerged across multiple apps built on this framework:

- **One-paragraph opener** that names the backend system
  (for API-proxy) or the data domain (for data-owning) in
  the first sentence. Skip preamble.
- **Env var table early** — a single table of every env
  var the app reads, with `Required | If Missing | Purpose`
  columns. This is where operators land when debugging
  startup failures.
- **Configure/install/register as three distinct sections.**
  Install = getting the package. Configure = env vars,
  identity provider, profile data. Register = wiring into an
  MCP client. Conflating these confuses readers.
- **Concrete example tool call** in the Run Locally
  section — a literal tool invocation through an MCP
  client or a curl against the HTTP endpoint. Gives the
  reader confidence the thing is actually working.
- **Post-deploy verification section** — not "how to
  deploy" and not "how to manage users" but a distinct
  "how to confirm the deploy worked" section featuring
  `probe`. This is the first step a returning operator
  takes months later.
- **Rotating credentials as a named subsection** under
  user management. The credential-rotation path is the single
  most-searched workflow after initial setup. Give it a
  heading.
- **MCP client config shown for all three clients**
  (Claude Code, Antigravity CLI, Claude.ai URL). Don't make
  the reader figure out which subset their client
  supports.

### Agent context files

**CLAUDE.md:**
```markdown
@README.md
@CONTRIBUTING.md
```

**`AGENTS.md`** (Antigravity CLI loads it automatically; it
does not read `CLAUDE.md` or `.gemini/settings.json`):
```markdown
Read the [project README](README.md) and the
[contributing guide](CONTRIBUTING.md) before working in this repo.
```

These files make the README and CONTRIBUTING content
available to Claude Code and Antigravity CLI when they
operate in the repo — a user or agent working in the
repo has the full operational context without needing to
load any skill.

### Agent context setup

If the app is being onboarded for AI-assisted development for
the first time — or if `CLAUDE.md`, `AGENTS.md`, and
`.gitignore` aren't yet set up correctly — the broader
goal is: Claude Code, Antigravity CLI, and any other agent that
opens the repo should automatically load README and
CONTRIBUTING, not leak agent-specific scratch files into the
repo, and share configuration that's universally useful
across tools.

The minimum:
- `CLAUDE.md` imports `@README.md` and `@CONTRIBUTING.md`
- `AGENTS.md` points to `README.md` and `CONTRIBUTING.md`
- `.gitignore` ignores `.claude/` and `.gemini/` entirely

If the `setup-agent-context` skill is available in the
environment, it automates and standardizes this across repos.
Use it if present. If not, the minimum above is sufficient —
the skill exists to save time, not to add capability the
plain files lack.


## Gitignore

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
build/
dist/
.venv/
venv/
.eggs/

# Environment
.env

# Testing
.pytest_cache/

# Claude Code
.claude/

# Antigravity / Gemini local files
.gemini/

# OS
.DS_Store

# Logs
*.log
```

