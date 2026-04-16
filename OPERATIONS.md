# Operations

> **Status: ROADMAP / DESIGN.** This document describes the
> intended operator experience for building, deploying, and
> managing mcp-app solutions. Most of it is not yet implemented;
> [#7](https://github.com/echomodel/mcp-app/issues/7) tracks the
> fleet/deploy implementation. Sections are marked **(today)**
> when they describe behavior that exists in the current release,
> and **(design)** for everything else.
>
> This document supersedes [FLEET.md](FLEET.md). Where the two
> diverge, OPERATIONS.md is authoritative going forward. FLEET.md
> remains as a historical design artifact until the replacement
> is confirmed complete.

## Overview

Operating an mcp-app solution — deploying, managing users, checking
health, rotating tokens — follows a unified model regardless of
which solution, how you deploy, or how many solutions you manage.

### Three layers, three owners

| Layer | Where it lives | Who owns it |
|-------|---------------|-------------|
| **App definition** | `App` object in solution package | Solution author |
| **Fleet manifest** | `fleet.yaml` (local or git repo) | Operator |
| **Deploy provider** | pip-installable package (or builtin) | Anyone |

Solution authors don't know how the operator deploys. Operators
don't know how the provider works internally. Providers don't know
which fleet they're in. Each layer is independently owned and
independently replaceable.

A single substrate (a "fleet") scales invisibly from a solo operator
with one solution to a team managing many solutions across multiple
environments. Simple cases never encounter fleet vocabulary. Complex
cases extend naturally through the same commands.

The default and most universal pattern is the **`manual` provider**:
mcp-app stores just the admin URL and a reference to the signing
key, and the operator deploys however they want (ssh+tarball,
`gcloud run deploy`, `docker compose`, a private CI pipeline, a
custom web UI — anything). More opinionated providers
(gapp, cloudrun, k8s, github-actions) exist and plug into the
same mechanism. Echomodel advocates gapp as a polished deployment
experience on top; every solution works with `manual` without it.

Two universal concerns apply to every solution regardless of
provider: **url** and **signing-key**. Both get first-class CLI
verbs. Every provider reports how it supports (or doesn't support)
setting each — manual-backed providers store locally, cloud-backed
providers resolve from the cloud, and the CLI surface is identical
for both.

## Operator Experience

### Solo, single solution — manual provider (the universal path)

You have one mcp-app solution. You've deployed it somewhere yourself
(or you're about to), and you want mcp-app to handle user and token
management.

```bash
cd ~/projects/echofit
mcp-app url set echofit https://my-service.example.com
mcp-app signing-key set echofit
  → "signing key for echofit: ___"    (prompts hidden; stored opaquely)

mcp-app users add echofit alice@example.com
  → (returns token)

mcp-app health echofit
  → {"status": "ok"}
```

No provider install, no fleet vocabulary, no yaml editing. The
first `url set` creates the fleet entry (manual provider implicit).
Each universal verb writes to wherever the provider puts it —
operator doesn't have to know or care.

### Solo, single solution — with a deploy provider

You want mcp-app to run your deploys, not just manage users.

```bash
cd ~/projects/echofit
mcp-app deploy
  → "deploy not configured for echofit. run 'mcp-app deploy configure'."

mcp-app deploy configure
  → wizard:
      Which provider? (installed: manual, local-docker)
      [any provider-declared config fields, prompted with hints/defaults]
      Source [echomodel/echofit]            (inferred from git remote)
      Ref [main]                            (inferred from default branch)
      Multi-environment? [n]

mcp-app deploy
  → pre-deploy summary, confirm, provider runs
```

Wizard's prompts come from the chosen provider's self-described
schema. mcp-app itself knows nothing about GCP projects or k8s
namespaces — the provider declares what it needs, the wizard asks.

### Solo, multiple solutions

```bash
cd ~/projects/echofit && mcp-app deploy configure && mcp-app deploy
cd ~/projects/gwsa   && mcp-app deploy configure && mcp-app deploy

mcp-app users add echofit alice@example.com
mcp-app users add gwsa bob@example.com
```

Same commands. Each solution gets its own entry in the same invisible
default fleet.

### Multi-environment

```bash
cd ~/projects/echofit
mcp-app deploy configure --env dev
mcp-app deploy configure --env prod

mcp-app deploy --env dev
mcp-app deploy --env prod --ref v1.2.3

mcp-app users add alice@example.com --env prod   # prod users only
mcp-app users add alice@example.com --env dev    # dev users (separate roster)
```

`--env` is only needed when the solution has multiple environments.
When a `default_env` is set, bare commands target the default.

### Multi-fleet

```bash
mcp-app fleets register https://github.com/acme/team-infra --name team
mcp-app fleets use team

mcp-app deploy echofit                   # deploys team's echofit
mcp-app deploy echofit --fleet personal  # one-off cross-fleet op
```

`mcp-app fleets` commands appear only when an operator has use for
multiple fleets. Before that, the default local fleet is the only
one and is invisible.

## CLI Reference

### Url — first-class universal

```bash
mcp-app url show <target>
mcp-app url set <target> <url>
mcp-app url refresh <target>
```

Every solution has a URL. The verbs always run; the provider decides
what's supported (see [Provider capabilities](#provider-capabilities)).
For `manual`, all three succeed and store/read the URL from the fleet
entry. For cloud-backed providers (`gapp`, `cloudrun`), `show` and
`refresh` fetch the URL from the cloud; `set` errors with a pointer
to the right verb (usually `deploy`).

### Signing-key — first-class universal

```bash
mcp-app signing-key show <target>             # opaque — shows "set" + sha256 fingerprint
mcp-app signing-key set <target> [--stdin]
mcp-app signing-key rotate <target>           # provider-dependent
```

Every solution has a signing key. Set prompts hidden (or reads stdin
for CI); rotate asks the provider to generate a new one if supported.
Show is opaque — never displays where the key lives or its value.

### Show — current state readout

```bash
mcp-app show [target]
```

Prints everything currently known about a target: provider, url,
signing-key status (opaque), source, ref, runtime, provider config,
env, secrets (set/unset), notes, and any named environments. Not a plan,
not a diff — just the facts. Target optional with cwd inference.

### Deploy

```bash
mcp-app deploy [target] [--ref <ref>] [--fleet <name>] [--env <name>]
mcp-app deploy [target] --dry-run                       # preview; no changes
mcp-app deploy configure [target]                       # first-time wizard
mcp-app deploy config <field> set <value> [target]      # per-attribute tweak
mcp-app deploy config show [target]
```

`target` is the solution name. When omitted, cwd inference resolves
it if the current directory is an mcp-app solution (its
`pyproject.toml` declares `[project.entry-points."mcp_app.apps"]`).
Use `--env <name>` to target a specific environment when the
solution has multiple.

### Admin

```bash
mcp-app users add <target> <email>
mcp-app users list <target>
mcp-app users revoke <target> <email>
mcp-app tokens create <target> <email>
mcp-app health <target>
```

All admin verbs resolve URL from the fleet entry (or via
`provider.status()`) and signing key from the provider's resolver
(keyring, cloud secret store, etc.).

### Providers

```bash
mcp-app providers list
mcp-app providers describe <name>                       # JSON schema
mcp-app providers add <name> --package <pip-spec>
mcp-app providers config <name> <field> set <value>
mcp-app providers remove <name>
```

The `manual` builtin appears in `list` without declaration.
Pip-installable providers appear once installed.

### Environments

```bash
mcp-app envs list [solution]
mcp-app envs add <solution> <env-name>                  # alias of 'deploy configure --env X'
mcp-app envs remove <solution> <env-name>
```

### Fleets (advanced)

```bash
mcp-app fleets list
mcp-app fleets current
mcp-app fleets use <name>
mcp-app fleets register <url> --name <name> [--path <path>]
mcp-app fleets remove <name>
```

### Config (secrets and machine-level settings)

```bash
mcp-app config secrets list
mcp-app config secrets set <target> <field> [--stdin]
mcp-app config secrets show <target> <field>            # references only; values redacted
mcp-app config secrets export [--out <path>]
mcp-app config secrets import <path>

mcp-app config signing-key-store set [keyring|file|env]
```

Use `--stdin` for CI/non-interactive secret injection:

```bash
echo "$CI_KEY" | mcp-app config secrets set echofit signing_key --stdin
mcp-app deploy echofit
```

No magic environment variable name schemes.

### Overrides

| Flag | Effect |
|------|--------|
| `--fleet <name>` | Use a specific fleet for this invocation. |
| `--env <name>` | Target a specific environment when solution has multiple. |
| `--ref <ref>` | Deploy a specific git ref. Overrides fleet-entry ref. |

No `--source` flag, no `--use-working-tree`. Source is locked to
the fleet entry for reproducibility. See [Source locking](#source-locking).

### cwd inference

When cwd is an mcp-app solution, `target` is optional on every
command. pyproject's `mcp_app.apps` entry-point name resolves the
solution. When a solution has multiple environments and no
`default_env` is set, the CLI errors with the list of
available environments — cwd never silently picks one.

## Schema Reference

### Top level

```yaml
providers:                  # pip-installable provider declarations (builtins omitted)
  <name>:
    package: <pip-spec>     # reserved; pip install target
    <any other key>: ...    # passed to provider as base config

defaults:                   # optional fleet-wide defaults
  deploy: <provider-name>
  runtime: mcp-app          # mcp-app | none

solutions:
  <solution-name>:
    source: <source>
    ref: <ref>              # optional
    deploy: ...             # see below
    runtime: ...            # optional; overrides default
    vars: {...}             # optional; runtime environment variables
    secrets: {...}          # optional
    envs:                   # optional; named environments (dev, prod, etc.)
      <env-name>: ...
    default_env: <name>     # optional
```

### Flattened `deploy:` block

Under `deploy:`, only `provider:` and `notes:` are reserved.
Everything else is provider config (what the provider's `describe()`
declares):

```yaml
deploy:
  provider: <name>          # reserved; which provider
  notes: |                  # reserved; optional operator context
    ...any hints for humans and agents...
  <any other key>: ...      # provider config field
  <another key>: ...        # provider config field
```

If `provider:` is omitted, defaults to the value from
`defaults.deploy`, and if that's unset, to the `manual` builtin.

The same flattening applies to top-level `providers.<name>:`:
`package:` is reserved, every other key is base provider config.

### `notes:` — operator context for any provider

Optional free-form text on any `deploy:` block (solution or
env level). Not consumed by mcp-app. Printed in the pre-deploy
summary and shown to agents and humans running a deploy. Useful for:

- **`manual` provider**: operator explains how to deploy, because
  mcp-app won't do it.
- **Any provider**: operator leaves hints, skill names to invoke, or
  contingencies.

Examples:

```yaml
# manual with instruction for the next human/agent
deploy:
  provider: manual
  url: https://my-service.example.com
  notes: |
    To deploy, run ./deploy from the repo root. Hits our internal
    build pipeline.
```

```yaml
# manual acknowledging no agent-friendly path exists
deploy:
  provider: manual
  url: https://my-service.example.com
  notes: |
    Deployed via the internal thingamigger (no CLI or API). Agents
    should stop here and let the human take over.
```

```yaml
# hint for an agent with additional skills available
deploy:
  provider: cloudrun
  project: my-proj
  region: us-central1
  notes: |
    If the my-company-deploy skill is installed, prefer that over
    direct cloudrun provider invocation — it handles our internal
    approval workflow.
```

### Solution fields

| Field | Required | Default | Inherits? |
|-------|----------|---------|-----------|
| `source` | yes | — | to envs |
| `ref` | no | repo default branch | to envs |
| `deploy.provider` | no | `defaults.deploy` → `manual` | to envs |
| `deploy.<config field>` | depends on provider's schema | provider's own default (if any) | to envs (merged) |
| `deploy.notes` | no | — | to envs (overrideable) |
| `runtime` | no | `defaults.runtime` → `mcp-app` | to envs |
| `vars` | no | — | to envs (merged) |
| `secrets` | no | — | to envs (merged) |
| `envs` | no | single-target deploy | — |
| `default_env` | no | — | — |

### Inheritance order

Every attribute cascades lowest → highest precedence:

1. Defaults and root provider config
2. Solution-level
3. Env-level
4. CLI override flags

Provider `config` fields merge across levels (env overrides
solution overrides root). `vars` and `secrets` also merge.

`vars:` is never allowed at fleet `defaults` or root `providers:`
level — it's always solution-specific. Similarly, `source:` only
makes sense at solution or env level.

### Minimum valid fleet.yaml

Just enough for manage-only (manual provider implicit):

```yaml
solutions:
  echofit:
    deploy:
      url: https://my-service.example.com
```

Three lines. No `providers:` block, no `defaults:`, no
`provider:` field. Signing key lives in keyring.

For a deployed-through-mcp-app solution using cloudrun:

```yaml
providers:
  cloudrun:
    package: mcp-app-cloudrun
    region: us-central1

defaults:
  deploy: cloudrun

solutions:
  echofit:
    source: echomodel/echofit
    deploy:
      project: my-proj      # cloudrun config field; region inherited
```

### Source field forms

```yaml
source: owner/repo                              # GitHub (clone fresh)
source: git+https://github.com/owner/repo.git   # arbitrary git remote
source: registry.io/image:tag                   # pre-built image
source: /absolute/path/to/source                # local path (dev)
```

### Source locking

`source` lives only in the fleet entry. There is no `--source` or
`--use-working-tree` flag. Every deploy corresponds to a real
commit in the configured source. Operators can't accidentally
deploy the wrong thing from the wrong directory. Image tagging
follows from resolved commit sha — reproducible and auditable.

To deploy an unpushed branch: `git push origin HEAD:wip-branch && mcp-app deploy --ref wip-branch`.

## Config Ownership

Three layers own different kinds of configuration. Mixing them
causes drift. The rule: **each piece of config lives with the layer
that varies it.**

| Layer | Owns | Examples | Where it lives |
|-------|------|----------|----------------|
| Solution author | Config intrinsic to the app | Feature flags, fixed behaviors, API schema versions | Solution repo (App constructor args, pyproject) |
| Operator | Config that varies by operator or environment | `LOG_LEVEL`, per-env credentials, deploy target, refs | fleet.yaml |
| Provider | Config the provider needs to deploy | GCP project, k8s namespace, region, build args | `providers:` block or `deploy:` block in fleet.yaml |

Don't lift into fleet.yaml what doesn't actually vary. Operator-
varying config belongs in fleet; solution-intrinsic config stays
in the repo; provider-specific settings belong in provider config.

Signing keys are the exceptional case: they always vary (unique
per environment) but never touch disk in plaintext. Keyring or
cloud secret store holds them, resolved on demand.

## Provider Plugin Model

### The sandwich

**With a deploy provider (gapp, cloudrun, local-docker, etc.):**

```
mcp-app deploy configure    ← mcp-app (prompts from provider schema)
    ↓
provider.deploy()           ← provider (cloud/tool-specific)
    ↓
mcp-app health              ← mcp-app (verify it's up)
mcp-app users add           ← mcp-app (manage users via admin API)
```

**With manual provider (operator deploys externally):**

```
operator deploys however    ← their tools, their process
    ↓
mcp-app url set             ← mcp-app (records where it landed)
mcp-app signing-key set     ← mcp-app (records the admin key)
    ↓
mcp-app health              ← mcp-app (verify it's up)
mcp-app users add           ← mcp-app (manage users via admin API)
```

mcp-app owns everything except the deploy step. With a provider,
that step is delegated. With manual, the operator handles it and
tells mcp-app the result. The admin layer below is identical
either way.

### Builtin providers

Ship with mcp-app itself. No `providers:` declaration needed.

- **`manual`** — stores URL and signing-key reference; does nothing
  at deploy time. Supports `notes:` for operator context. Most
  lightweight and most universal pattern — every solution works
  with it.
- **`local-docker`** — build image, run container on the operator's
  machine (or remote docker host). For personal / homelab /
  always-on-laptop use. Details in [Builtin Provider Details](#builtin-provider-details).

All other providers are separately installable. The README's
"Integrated deployment" section walks through the common setup
steps for widely-used providers like `gapp`, so operators who want
a polished GCP experience can install and configure in one pass.
mcp-app itself stays lean — no provider ships as a hard dependency.

### Pip-installable providers

Anyone can publish one as a pip package that registers under
`entry_points(group="mcp_app.providers")`. Operator installs via
`mcp-app providers add <name> --package <pip-spec>`. Community or
vendors publish whatever bridges they want.

### Anticipated providers — future roadmap

Not committed to a timeline; documenting the shape of the ecosystem
as currently envisioned. Echomodel will publish a subset; others
are open to community authorship.

**For managed platforms (zero-ops):**

- **`mcp-app-cloudrun`** — direct `gcloud run deploy --source` with
  no intermediaries. Least opinionated GCP path. Config: project,
  region, artifact-registry, gcs-build-bucket.
- **`mcp-app-gapp`** — bridge to gapp; operator gets gapp's full
  feature set. Neither mcp-app nor gapp know about each other
  (third-party-looking provider). Richer than cloudrun for
  echomodel workflows (approval gates, env-specific overrides,
  build caching). Published separately as `echomodel/mcp-app-gapp`
  on PyPI. Install via `mcp-app providers add gapp --package mcp-app-gapp`.
  README's "Integrated deployment" section documents the full gapp
  setup path — a natural fit for operators who want a one-command
  polished GCP experience.
- **`mcp-app-flyio`** — fly.io deploys. Config: app name, region.
- **`mcp-app-railway`** / **`mcp-app-render`** — similar for those PaaS.
- **`mcp-app-k8s`** — render a manifest, `kubectl apply`. Config:
  namespace, context, chart values.

**For bring-your-own-infrastructure:**

- **`mcp-app-systemd`** — SSH to a VM, install a venv, write a
  systemd unit, `systemctl enable`. Most ubiquitous reliable option
  for bring-your-own-VM deployments (Linux + systemd is universal).
  Config: host, user, install_path, port.
- **`mcp-app-docker`** — richer than the `local-docker` builtin:
  supports docker-compose files, healthchecks, restart policies,
  remote docker hosts. Good for "always-on box, containerized,
  docker already there."
- **`mcp-app-ssh`** — rsync/tar a checkout to a VM, run a restart
  hook. Minimal dependency; works when systemd isn't desired.

**For CI-driven deploys:**

- **`mcp-app-github-actions`** — dispatch a GitHub Actions workflow
  and wait for completion, parse the run for the deployed URL.
  Config: workflow filename, ref, inputs, wait-mode.

### Builtin: `local-docker`

Ships with mcp-app. For personal / homelab / always-on-laptop use.

```yaml
solutions:
  echofit:
    deploy:
      provider: local-docker
      image_tag: echofit:latest        # defaults to <solution>:latest
      port: 8080                       # host port
      host: unix:///var/run/docker.sock  # defaults to local daemon
      restart: unless-stopped          # docker restart policy
```

Behavior: `docker build -t <image_tag> .` from the source checkout,
`docker rm -f <solution>` to clean up the previous container,
`docker run -d --name <solution> --restart=<policy> -p <port>:8080 -e SIGNING_KEY=<resolved> <image_tag>`.
URL auto-derived: `http://<host-or-localhost>:<port>`.

When to pick this vs the richer `mcp-app-docker` provider: the
builtin is opinionated for single-container single-machine use. If
you need docker-compose, healthchecks, volume config, or remote
docker hosts with proper ops, install `mcp-app-docker`.

### Choosing a deployment target

High-level guidance for which path fits which use case. See
[Deployment Target Tradeoffs](#deployment-target-tradeoffs) for
deeper comparison.

| Use case | Recommended target | Provider |
|----------|-------------------|----------|
| Solo developer iterating on tools, agent in Claude Code / Gemini | stdio (no provider) | — |
| Personal daemon, same operator, single machine, always-on | local-docker builtin, or `mcp-app-systemd` on the same machine | `local-docker` |
| Homelab box serving family/household on LAN | local-docker (bind to LAN) | `local-docker` |
| Bring-your-own VM in the cloud, single-user, bulletproof | VM + systemd on the VM | `mcp-app-systemd` |
| Multi-service homelab, everything containerized | Docker / compose on the box | `mcp-app-docker` |
| Spike-traffic or idle-heavy app, managed platform | Managed container (Cloud Run, Fly) | `mcp-app-cloudrun`, `mcp-app-flyio`, etc. |
| Team with GCP infra, standardized workflow | Cloud Run via gapp | `mcp-app-gapp` |
| CI-driven, team-visible deploys | GitHub Actions | `mcp-app-github-actions` |

### `package:` field accepts any pip install target

```yaml
providers:
  cloudrun:
    package: mcp-app-cloudrun                                  # PyPI
  cloudrun-pinned:
    package: "mcp-app-cloudrun>=1.2,<2.0"                      # version constraint
  custom:
    package: git+https://github.com/me/my-provider.git@v1.2.0  # git
  custom-dev:
    package: ~/projects/my-provider                            # local path
```

mcp-app passes the value unmodified to `pip install`.

### Self-describing schema

Every provider exposes its config requirements via `describe()`:

```python
class ManualProvider(DeployProvider):
    @classmethod
    def describe(cls):
        return ProviderSchema(
            name="manual",
            description="No deployment; operator deploys externally",
            config_fields=[
                Field("url",         type="string", required=True,
                      hint="admin endpoint URL"),
                Field("signing_key", type="secret", required=True,
                      hint="admin signing key"),
            ],
        )
```

The skill and CLI use this to prompt operators. `type: "secret"`
fields are stored via the machine's configured secret backend
(keyring / file / env) and referenced, not embedded, in fleet.yaml.

### Provider capabilities

Every provider declares what universals it supports via a
capabilities block returned from `describe()`. The CLI reads this
to decide whether `url set`, `signing-key rotate`, etc. will be
accepted or will return a provider-aware error.

```python
@dataclass
class Capability:
    get: bool = True        # can read this value
    set: bool = False       # can the operator supply a value
    refresh: bool = False   # can re-resolve from provider's source
    rotate: bool = False    # can provider generate a new value

capabilities = {
    "url":         Capability(get=True, set=True,  refresh=True),
    "signing_key": Capability(get=True, set=True,  rotate=False),
}
```

Example matrix:

| Provider | url.get | url.set | url.refresh | sk.get | sk.set | sk.rotate |
|----------|---------|---------|-------------|--------|--------|-----------|
| manual | ✓ | ✓ | ✓ (no-op) | ✓ | ✓ | ✗ |
| local-docker | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |
| gapp | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ |
| cloudrun | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ |
| systemd | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |

When the operator requests an unsupported capability, the CLI
returns a clean error with a pointer at the right alternative
verb. No command "not found," no silent failure.

### Provider interface

```python
class DeployProvider:
    @classmethod
    def describe(cls) -> ProviderSchema:
        """Return config schema and capabilities. Used by CLI and skill."""

    def deploy(self, request: DeployRequest) -> DeployResult:
        """Execute a deploy. Provider gets fully-resolved context."""

    def status(self, solution: str, env: str | None) -> Status:
        """Return current URL, last deployed ref/sha, health."""

    def get_signing_key(self, solution: str, env: str | None) -> str:
        """Fetch signing key on demand."""

    def set_signing_key(self, solution, env, value) -> None:
        """Only called if capability sk.set is True."""

    def rotate_signing_key(self, solution, env) -> None:
        """Only called if capability sk.rotate is True."""
```

Providers receive fully-resolved configuration — fleet handles
inheritance and merging. Providers don't read fleet.yaml.

### DeployRequest shape

```python
DeployRequest(
    solution="echofit",
    env="dev" | None,
    source=Source(
        url="echomodel/echofit",
        ref="main",
        sha="a3f1c2e",
        checkout="/tmp/mcp-app-XXX" | None,   # fresh clone, if fleet did one
    ),
    config={...},                             # resolved provider config
    env={...},                                # merged runtime env vars
    secrets={...},                            # refs; provider resolves values
    runtime="mcp-app",
    notes="...",                              # if set, for logs/summary
    fleet_name="default",
)
```

## Builtin Provider Details

### `manual`

```yaml
solutions:
  echofit:
    deploy:
      provider: manual                            # optional; default
      url: https://my-service.example.com
      notes: |                                    # optional
        To redeploy, run `./scripts/deploy.sh` from repo root.
```

`describe()` reports:

| Field | Type | Required | Hint |
|-------|------|----------|------|
| url | string | yes | admin endpoint URL |
| signing_key | secret | yes | admin signing key |

`deploy()` does nothing — raises or returns success with "manual
deploy; operator handles it externally." `notes:` content prints
to the terminal when someone runs `mcp-app deploy echofit`, so
both humans and agents see it.

`status()` returns the stored URL. `resolve_signing_key()` fetches
from keyring.

## Operational Flows

### First deploy (from a clean machine)

```bash
$ cd ~/projects/echofit
$ mcp-app deploy
  → "deploy not configured for echofit. run 'mcp-app deploy configure'."

$ mcp-app deploy configure
  # silently creates the default fleet if none exists
  # discovers installed providers via entry_points
  # prompts: Which provider? [manual / local-docker / (other installed) / other]
  # [provider-declared fields follow, each prompted with hint and default]
  # prompts: Source [echomodel/echofit] (from git remote)
  # prompts: Ref    [main]              (from default branch)
  # prompts: Multi-environment? [n]
  → "Configured. Run 'mcp-app deploy'."

$ mcp-app deploy
  → Pre-deploy summary:
      Deploy echofit
        source:   echomodel/echofit @ main → a3f1c2e
        provider: cloudrun (project=my-proj, region=us-central1)
        runtime:  mcp-app
        notes:    (if set)
      Proceed? [y/N]
  → Provider runs. Output streams to terminal.
  → CLI prints next-step hints (users add, health).
```

### First-time manage-only (no mcp-app deploy)

You deployed echofit yourself via your own tooling. Now you want
mcp-app to handle users.

```bash
$ mcp-app url set echofit https://my-service.example.com
  → Stored.

$ mcp-app signing-key set echofit
  → signing key for echofit: ****
  → Stored.

$ mcp-app users add echofit alice@example.com
  → (returns token)
```

The first command creates the fleet entry implicitly (manual
provider is the default). Equivalent fleet.yaml under the hood:

```yaml
solutions:
  echofit:
    deploy:
      url: https://my-service.example.com
```

### Redeploy

```bash
$ git push
$ mcp-app deploy
  → Pre-deploy summary (new sha)
  → Confirm, run.
```

### Lazy prompt for missing fields

First use of a command on a new machine (e.g., cloned team fleet,
new laptop):

```bash
$ mcp-app users add echofit alice@example.com
  → "signing key for echofit not found on this machine."
  → "enter signing key: ___"
  → (stored in keyring, runs the admin call)
```

Non-secret missing fields prompt the same way but write back to
fleet.yaml.

Non-interactive contexts (CI, `--yes`, no tty): the CLI errors
with a clear instruction on how to supply the value via
`mcp-app signing-key set --stdin` or `mcp-app deploy config ... set`.

### Multi-env deploy

```bash
$ mcp-app deploy configure --env dev
$ mcp-app deploy configure --env prod

$ mcp-app deploy --env dev
$ mcp-app deploy --env prod --ref v1.2.3
```

Each environment has its own URL, signing key, and user roster.

### Pre-deploy summary

Always printed before deploy executes:

```
Deploy echofit
  source:   echomodel/echofit @ main → a3f1c2e
  provider: cloudrun (project=my-proj, region=us-central1)
  target:   https://echofit-xxx.a.run.app   (or: "new deployment")
  runtime:  mcp-app
  env:      LOG_LEVEL=INFO
  secrets:  signing_key (stored), third_party_api_key (stored)
  notes:    To rollback, run scripts/rollback.sh from repo root.

Proceed? [y/N]
```

### Safety checks

Before the summary:

- **Unpushed commits** — if the source is a remote ref and local
  branch is ahead of origin, warn.
- **Uncommitted changes** — if the source is a local path, warn
  about dirty working tree.
- **Stale refs** — if the requested ref doesn't exist in the
  remote, error.

Warnings are non-blocking by default. `--strict` promotes them to
errors (CI). `--yes` skips the confirm (scripts).

## Secret Storage

Secrets never appear in fleet.yaml, and operator-facing output
never reveals where they live — it only reports whether a value
is set and a fingerprint. Storage backend is configurable but
invisible in normal operation.

Three backends, operator-selectable:

- **Default** — OS-native credential store on the operator's machine.
- **File** — encrypted-at-rest file under mcp-app's config directory,
  used when the OS store is unavailable (headless Linux, servers).
- **Env** — read from a named env var at resolution time, for CI /
  ephemeral containers.

`mcp-app` falls back **loudly** if the default backend is
unavailable — never silently to plaintext. Operator picks a mode
explicitly when the default doesn't fit:

```bash
mcp-app config signing-key-store set file
```

Canonical storage coordinates are derived deterministically from
(fleet, solution, env, field_name). Operator never types or
sees them. Reattaching (new machine, cloned fleet) works
automatically — mcp-app checks the store and prompts if missing.

Non-interactive secret injection uses CLI verbs:

```bash
echo "$KEY" | mcp-app signing-key set echofit --stdin
```

## State Ownership

mcp-app does **not** store per-solution runtime state locally.
Everything it persists is configuration (intent). Runtime state
(what's deployed, where, at what revision) lives with the provider.

**Local files:**

```
~/.config/mcp-app/
  fleets.yaml                          # registry: which fleets, which active
  fleets/<fleet-name>/
    fleet.yaml                         # manifest (config, not state)
```

**Runtime state** (URL, last sha, image tag, health):

- Owned by the provider.
- Fetched via `provider.status(solution, env)` on demand.
- Signing keys resolved via `provider.resolve_signing_key(...)`,
  never cached on disk in plaintext.
- Provider-internal caching (in-session memoization, its own cache
  file) is the provider's choice.

Admin ops always ask the provider for fresh values. Cached local
state (fleet entry URL for manual, for example) is treated as an
operator-supplied hint, not as source of truth.

## Skills and Agent Integration

### The agent's open/closed configure flow

`deploy-mcp-app` (or any agent) figures out how to configure a
provider by asking mcp-app, not by knowing providers itself:

1. `mcp-app providers list --format json` → names of installed providers
2. Operator picks one
3. `mcp-app providers describe <name> --format json` → schema
4. Agent prompts operator for each `config_field`, showing hint and
   default
5. Agent calls `mcp-app deploy configure <target> --provider <name> --config-json '...'`

The agent has no provider-specific knowledge. New providers plug
in without skill changes.

### `deploy-mcp-app` skill

Fires on user intents like "deploy this." Thin orchestrator:

1. Detect mcp-app solution via pyproject entry point.
2. Run `mcp-app deploy`. On "not configured," branch to configure.
3. Configure flow above; then run `mcp-app deploy` for real.
4. Surface `notes:` to the user when the configure already has
   manual-with-notes, so they understand how the deploy happens.

No tool-specific knowledge. Providers handle the mechanics.

### `manage-mcp-app` skill

Fires on post-deploy intents: "add a user," "check health," "rotate
a token." Maps to `mcp-app users/tokens/health <target> ...`.

### Framework test — README conformance

Every mcp-app solution's README should mention the `deploy-mcp-app`
skill so operators cloning the repo discover the pattern:

```python
def test_readme_references_deploy_skill(app_root):
    content = (app_root / "README.md").read_text()
    assert "deploy-mcp-app" in content or "# mcp-app:no-deployment-section" in content
```

Opt-out marker for stdio-only or personal solutions.

## Design Principles

1. **Solution repo stays deploy-agnostic.** No Dockerfile required,
   no deploy config, no cloud references in the solution.
2. **CLI simplicity is the invariant.** New features extend through
   defaults/inference, never by requiring new mandatory CLI
   arguments for the simple case.
3. **Manual is the universal default.** Every mcp-app can be
   managed without installing any provider.
4. **Url and signing-key are first-class universals.** Every
   solution has both; every provider declares how it supports them
   via capabilities. Admin ops call universal verbs; provider
   specifics are opaque to operators.
5. **One substrate.** Fleet is the only state layer. No parallel
   setup.json, deploy.yaml, or per-solution state files.
6. **Invisible until needed.** Solo operators never see fleet
   concepts. Vocabulary surfaces only when the operator reaches
   for the capability.
7. **No silent cwd influence on deploys.** cwd is a CLI ergonomic
   shortcut for target identification; it never changes what
   gets deployed.
8. **Source locked, ref overridable.** Every deploy maps to a real
   commit. No working-tree escape hatch.
9. **Providers own runtime state.** mcp-app orchestrates; providers
   know where things are deployed.
10. **Secret storage is opaque.** Operator-facing output never
    reveals backend names, paths, or coordinates. Default secure,
    explicit fallback only when the default is unavailable.
11. **CLI is the only writer of config files.** Agents and skills
    call CLI verbs, not yaml directly.
12. **Self-describing providers.** Schema and capabilities come
    from the provider. mcp-app and skills stay open/closed.
13. **Operator can always leave a note.** `notes:` on any `deploy:`
    block documents context for future humans and agents.

## Deployment Target Tradeoffs

High-level comparison of the realistic options. Not prescriptive —
operator picks what fits. See [Choosing a deployment target](#choosing-a-deployment-target)
for a quick-match table.

### stdio (no provider, no deployment)

Solution runs as a subprocess launched by an MCP client (Claude
Code, Gemini CLI, Agent SDK). Ephemeral, single-client, zero
always-on cost. Right choice for solo operators iterating on tools
or running personal apps they only touch in one agent.

Does not use mcp-app's deploy/admin machinery. No URL, no signing
key, no fleet entry — client's config launches `my-solution-mcp stdio --user local`.

### Local Docker on the operator's machine (builtin provider)

Builds a container from the solution, runs it on the operator's
machine with `--restart=unless-stopped`. Survives host reboots.
URL is `http://localhost:<port>`.

Fits: homelab / always-on laptop / single-machine multi-client use.
Multiple agent clients (Claude Code + Claude.ai mobile + Gemini CLI)
can hit the same instance. LAN sharing by binding to `0.0.0.0`.

Limits: your machine's uptime is the service's uptime. No auto-
scaling. Image rebuilds on each deploy.

### VM + systemd (pip provider, bring-your-own-infra)

SSH to a cloud VM, install a venv, write a systemd unit, enable.
Native reliability primitives: `Restart=on-failure`, `WantedBy=multi-user.target`
survives reboots.

Fits: single-user / small-team always-on service, bulletproof,
lowest cost at sustained use (~$5-10/mo on Hetzner/DigitalOcean/etc).
Portable across any Linux VM on any cloud. Full control over OS,
side processes, observability.

Backups: provider VM snapshots daily + Litestream or cron-scheduled
`sqlite3 .backup` if using SQLite + optional restic/rclone to
offsite object storage.

### VM + Docker (pip provider)

Similar shape to systemd but via docker-compose. Richer than the
local-docker builtin: healthchecks, volume config, remote docker
hosts, multi-container setups.

Fits: operators who already run docker everywhere and want the
image-based reproducibility without the systemd-native path.

### Managed container platform (pip provider: cloudrun, gapp, flyio, etc.)

Provider-managed autoscaling, TLS termination, log aggregation.
Scales to zero when idle (in some platforms), scales up on demand.

Fits: spike traffic, multi-user, teams with existing managed-platform
relationships. Zero infra ops, more dollars per sustained request.

Cold starts (seconds) affect first-request latency on infrequent
traffic. Persistent storage requires external services (Cloud SQL,
Cloud Storage, etc.), re-introducing network round-trips.

### Comparison of disk I/O and data patterns

A non-obvious difference: **VM + local SSD enables SQLite** as the
data store, which is 100-1000x faster than object-store-backed
patterns for small-file access.

| Pattern | Read latency (small file/row) | Write latency | Per-op cost | Transactions | Indexed queries |
|---------|------------------------------|---------------|-------------|--------------|-----------------|
| JSON-per-file on local SSD | ~0.1 ms | ~0.1 ms | none | no (FS rename is atomic) | no |
| JSON-per-file on GCS FUSE | 50-200 ms | 100-300 ms | GCS Class A/B per op | no | no |
| SQLite on local SSD | ~0.01 ms | ~0.1 ms (WAL) | none | yes | yes |
| Cloud-managed SQL (Postgres, etc.) | 1-5 ms (same region) | 1-10 ms | connection / query cost | yes | yes |

Implications for mcp-app solutions:

- **Cloud Run / managed containers** typically need external state:
  Cloud SQL, Cloud Storage, or bucket-backed JSON patterns. Every
  read is a network round-trip. The "small JSON files by user/date"
  pattern common in mcp-app data stores works, but slowly.
- **VM + SQLite** replaces that pattern entirely. The data store
  becomes a proper database with transactions, indexed queries,
  and point-in-time backups via Litestream.
- **stdio / local-docker** give you local SSD too, so SQLite works
  there as well.

For single-user apps with non-trivial data (food logs, note apps,
journals), VM + systemd + SQLite + Litestream is genuinely the
pragmatic sweet spot: fast, reliable, cheap, portable, backed up
offsite, minimal ops.

### Quick decision table

| If your situation is... | Target |
|-------------------------|--------|
| Solo dev, iterating on tools, one agent | stdio |
| Personal always-on app, single machine, one or a few clients | local-docker builtin |
| Personal always-on app on a cloud VM, bulletproof, cheap | VM + systemd (`mcp-app-systemd` provider) |
| Family/household LAN service | local-docker on a homelab box, bind LAN |
| Multi-user app, moderate scale, willing to pay for zero-ops | managed container (`mcp-app-cloudrun`, `mcp-app-gapp`, `mcp-app-flyio`) |
| Team with existing GCP workflow | `mcp-app-gapp` |
| CI-driven deploys | `mcp-app-github-actions` |
| Bursty traffic, scale to zero | managed container platform |
| Data-intensive (SQLite matters) | VM + systemd, or local-docker with a bind-mounted data volume |

## Open Design Questions

Tracked for resolution during implementation.

### Provider invocation: checkout vs cwd vs image

When a provider deploys, does it operate in the operator's cwd,
a fresh clone, or an image? Different providers have different
needs. Resolution: provider's `describe()` also declares its
invocation contract (needs checkout / needs image / self-clones).

### `package:` field pass-through

Explicitly support git URLs, local paths, version constraints in
addition to PyPI names? Leaning yes, pass through to pip verbatim.
Needs to be ratified in implementation.

### Non-happy-path UX contract

Provider errors (auth missing, secret not found, quota) currently
pass through as raw subprocess output. Typed error hints vs passthrough
— leaning passthrough, because agents can match on known tool errors
and operators get the tool's own error text.

### Concurrency

Two operators editing the same shared team fleet with `generate: true`
signing keys could race at first deploy. Provider secret stores
typically have conditional-create semantics, but the fleet-level
contract hasn't defined concurrency behavior.

### State surfacing cost

`mcp-app fleet list` and similar will call `provider.status()` for
every solution. Providers may have rate limits or latency. Need:
caching policy, timeout behavior, degraded display.

### Default provider suggestions on empty machine

When `mcp-app deploy configure` runs with no providers installed
beyond the `manual` and `local-docker` builtins, what options does
the wizard offer? Hardcoded list couples mcp-app to specific
providers. Leaning on a community-maintained directory or just
asking operator for a pip spec.

## Relationship to Existing Documents

- **FLEET.md** (prior design): this document supersedes it.
  FLEET.md's provider plugin model, source field semantics, and
  fleet-registry concepts carry forward. FLEET.md's
  fleetless-vs-fleet distinction,
  and nested `config:` shape are revised here.
- **CONTRIBUTING.md**: architectural decisions remain. The
  "admin tooling rationalization" (#17), "agent-composed over
  provider-coupled" decisions, and "credentials are the SDK's
  concern" principles are unchanged.
- **README.md**: will link to this document once implemented.
- **author-mcp-app** skill: describes the authoring loop; this
  document describes the operating loop.

## Related Issues

- [#7](https://github.com/echomodel/mcp-app/issues/7) — Implement
  fleet commands
- [#9](https://github.com/echomodel/mcp-app/issues/9) — Deployment
  matrix (closed)
- [#17](https://github.com/echomodel/mcp-app/issues/17) — Admin
  tooling rationalization
- [#19](https://github.com/echomodel/mcp-app/issues/19) — Bundling
  skill, tests, and version awareness
