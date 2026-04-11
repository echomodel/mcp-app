# Fleet Management

mcp-app evolves from a framework for building individual MCP servers into the full lifecycle tool: build, deploy, manage, and fleet-track mcp-app services across any cloud or local environment.

## Three Layers, Three Owners

| Layer | Where it lives | Who owns it |
|-------|---------------|-------------|
| **App definition** | `App` object in solution package | Solution author |
| **Fleet manifest** | `fleet.yaml` in a git repo | Operator |
| **Deploy provider** | pip-installable package | Anyone |

## Solution Repo — Unchanged

A solution repo contains only the app definition. No deploy config, no provider references, no coupling to any cloud:

```python
# echofit_mcp/__init__.py
from mcp_app import App
from echofit_mcp.diet import tools

app = App(name="echofit", tools_module=tools)
```

> **Note:** This design doc predates the removal of `mcp-app.yaml`.
> App configuration is now via Python args (`App` class), not yaml.
> Some sections below still reference the old yaml pattern and need
> updating when fleet is implemented.

## Fleets

A fleet is a git repo (or a directory within one) containing a `fleet.yaml`.
Each fleet is self-contained — its own providers, its own solutions, its own
config. No layering, no merging, no overrides between fleets.

An operator registers fleets and switches between them:

```bash
mcp-app fleets register https://github.com/jim/infra.git --name work
mcp-app fleets register https://github.com/jim/personal-fleet.git --name personal
mcp-app fleets register ~/dotfiles/local-fleet --name local

mcp-app fleets list
#   * work      https://github.com/jim/infra.git
#     personal  https://github.com/jim/personal-fleet.git
#     local     ~/dotfiles/local-fleet

mcp-app fleets use personal
```

The fleet repo can be a remote GitHub URL, a local git repo (e.g., in
dotfiles), or a private repo — mcp-app doesn't care. If the fleet file
isn't at the repo root, specify the path on registration:

```bash
mcp-app fleets register https://github.com/jim/infra.git --path ops/fleet.yaml --name work
```

All fleet commands operate on the active fleet implicitly. Override with
`--fleet`:

```bash
mcp-app fleet list                    # uses active fleet
mcp-app fleet list --fleet personal   # explicit
```

### What's stored locally

Only the fleet registry — `~/.config/mcp-app/fleets.yaml`:

```yaml
active: work
fleets:
  work:
    url: https://github.com/jim/infra.git
    path: fleet.yaml
  personal:
    url: https://github.com/jim/personal-fleet.git
  local:
    url: ~/dotfiles/local-fleet
```

Everything else is in the fleet repos themselves.

### Why separate fleets instead of local overrides?

An earlier design used a gitignored `.fleet.local.yaml` that extended the
shared fleet manifest with local-only solutions. This was rejected because
any mechanism that layers config on top of shared state risks silently
mutating it — even "additive" property changes on existing objects can be
destructive (e.g., changing a provider region, adding a config field that
alters behavior, overriding a secret reference).

Separate fleets eliminate this entirely. Each fleet is its own world. Want
local docker instances? Put them in a `local` fleet. Want shared Cloud Run
services? They're in `work`. They never mix, never merge, never conflict.

## Fleet Schema

```yaml
# fleet.yaml

providers:
  cloudrun:
    package: mcp-app-cloudrun
    config:
      project: my-project
      region: us-central1
  hackerhost:
    package: mcp-app-hackerhost
    config:
      team: jim-team
      tier: starter                   # cheap scaled-down infra
  local-docker:
    package: mcp-app-local-docker

defaults:
  deploy: cloudrun
  runtime: mcp-app

solutions:
  my-app:
    source: owner/repo
```

**`providers`** — named deploy providers, configured once. Each entry has a
`package` (pip package name for auto-install or documentation) and optional
`config` (provider-specific defaults).

**`defaults`** — inherited by all solutions unless overridden.
- `deploy` — which deploy provider to use (references a key in `providers`)
- `runtime` — how to manage the running service. `mcp-app` means full admin
  lifecycle (user management, signing key resolution, and any future mcp-app
  features). `none` means deploy and track only.

**`solutions`** — the fleet. Each entry needs at minimum a `source`. Everything
else is inherited from defaults or provider config.

**Two orthogonal axes per solution:**

| Axis | What it controls | Default | Examples |
|------|-----------------|---------|----------|
| `deploy` | Where and how to deploy | From `defaults.deploy` | `cloudrun`, `hackerhost`, `local-docker` |
| `runtime` | How to manage once running | From `defaults.runtime` | `mcp-app`, `none` |

**Source field supports three shapes:**
- `owner/repo` — GitHub repo, mcp-app clones and builds
- `registry.io/image:tag` — pre-built container image, deploy directly
- `./local-path` — relative to fleet repo or absolute, for dev/testing

**Per-solution overrides** merge into the provider's base config:

```yaml
solutions:
  special:
    source: owner/repo
    deploy:
      provider: cloudrun
      config:
        region: asia-east1          # overrides just this field
```

## Deploy Providers — pip Packages, Entry Point Discovery

A provider is a pip-installable package that implements the deploy interface. It declares itself via Python entry points — a standard plugin discovery mechanism used by pytest, pip, Flask, and many other tools.

### How entry points work

Entry points are a **metadata registry**, not a module path. The group name
`mcp_app.providers` is just a string label — like a key in a phone book. It
looks like a Python module path but it isn't one. You could call it
`"fleet-deploy-backends"` and it would work identically. The dotted name is
convention to signal who owns the namespace.

When a provider package is pip-installed, it registers a name under this group.
When mcp-app needs a provider, it looks up the name in the registry. That's the
entire mechanism — no hardcoded mappings, no imports by convention, no magic.

A provider package declares itself in its own pyproject.toml:

```toml
# Provider's pyproject.toml
[project.entry-points."mcp_app.providers"]
cloudrun = "mcp_app_cloudrun:CloudRunProvider"
```

This says: "I'm registering the name `cloudrun` under the `mcp_app.providers`
group. When someone asks for `cloudrun`, give them the `CloudRunProvider` class
from the `mcp_app_cloudrun` module."

mcp-app discovers providers at runtime:

```python
from importlib.metadata import entry_points
providers = entry_points(group="mcp_app.providers")
provider_cls = providers[name].load()  # name comes from fleet.yaml
```

The group name `mcp_app.providers` is the only thing hardcoded in mcp-app. Provider names (`cloudrun`, `hackerhost`, `local-docker`) come from fleet.yaml at runtime. mcp-app never references any specific provider in its code. If a provider isn't installed, mcp-app errors: "no provider named X — pip install one that provides it."

### Provider interface

```python
class DeployProvider:
    def deploy(self, image: str, name: str, config: dict) -> str:
        """Deploy an image. Returns the service URL."""
        ...

    def status(self, name: str, config: dict) -> dict:
        """Return current status: {url, status}."""
        ...

    def resolve_signing_key(self, name: str, config: dict) -> str:
        """Retrieve the signing key from the provider's secret store."""
        ...
```

### Who publishes providers?

Three scenarios, all identical to mcp-app:

1. **Framework author** (echomodel) publishes `mcp-app-cloudrun` because Cloud Run is the primary target
2. **Community developer** publishes `mcp-app-hackerhost` because they use both platforms and built a bridge
3. **Cloud vendor** (HackerHost) publishes their own provider because mcp-app adoption makes native support worthwhile

All three declare the same entry point. The operator `pip install`s whichever one and puts the name in fleet.yaml. mcp-app doesn't know or care who wrote it.

## Environment Variables and Secrets

Solutions need two kinds of runtime configuration: plain env vars and secrets.
Both are deployment concerns — they belong in the fleet manifest, not the
solution repo.

```yaml
solutions:
  sales-tools:
    source: jim/sales-tools
    env:
      LOG_LEVEL: INFO
      MAX_RESULTS: "50"
    secrets:
      SIGNING_KEY:
        generate: true              # provider auto-generates at first deploy
      THIRD_PARTY_API_KEY:
        value: secret-name-in-store # reference, not the actual value
```

**`env`** — plain key-value pairs. Passed to the container as environment
variables. Safe to store in fleet.yaml (version controlled).

**`secrets`** — references to values in the provider's secret store (e.g., GCP
Secret Manager). Fleet.yaml never contains actual secret values — only
references or generation directives. The provider resolves them at deploy time
and injects them into the container's environment.

`SIGNING_KEY` with `generate: true` is special: the provider generates a
random key at first deploy, stores it in its secret store, and injects it. On
subsequent deploys it reuses the stored value. This is how mcp-app services
bootstrap their admin auth without the operator ever seeing the key.

### No local secrets

Secrets never touch the operator's disk. When admin commands need the signing
key, the deploy provider resolves it on demand using the operator's existing
cloud auth (e.g., ADC via `gcloud auth application-default login`):

```
mcp-app users add --app echofit user@example.com
  → reads fleet.yaml → echofit uses cloudrun provider, runtime is mcp-app
  → provider fetches signing key from Secret Manager (via ADC)
  → mcp-app mints admin JWT in memory
  → calls /admin/users on the deployed URL
  → key is garbage collected, never written to disk
```

This only applies to solutions with `runtime: mcp-app`. Solutions with
`runtime: none` have no signing key and no admin API.

### Provider auth

Providers handle their own authentication. Fleet.yaml never contains provider
credentials. Examples:

- **cloudrun** — uses Application Default Credentials (ADC). The operator runs
  `gcloud auth application-default login` once. The provider picks it up
  automatically via the GCP SDK.
- **hackerhost** — might use its own CLI login (`hh auth login`), an env var,
  or whatever auth mechanism HackerHost provides.
- **local-docker** — no auth needed.

This is the same model as Terraform providers: the provider is responsible for
its own auth. The fleet manifest configures what to deploy and where, not how
to authenticate.

## CLI Design

### Command groups

| Group | Who uses it | What it does |
|-------|------------|-------------|
| `mcp-app serve` | Solution developer | Run the app locally from cwd |
| `mcp-app build` | Solution developer | Build a Docker image from cwd |
| `mcp-app fleets` | Operator | Register, list, switch fleets |
| `mcp-app fleet` | Operator | Deploy, list, health-check solutions in active fleet |
| `mcp-app users` | Operator | Manage users on a deployed instance |
| `mcp-app tokens` | Operator | Manage tokens on a deployed instance |
| `mcp-app health` | Operator | Health-check a deployed instance |
| `mcp-app admin-tools` | Agent/MCP client | Stdio MCP server for admin operations |

### cwd is never used for deploy or admin

App-specific CLIs (`my-app-mcp serve`) get their config from the `App`
object in Python — no file discovery, no cwd dependency.

All other commands ignore the current directory entirely. Deploy reads from
the fleet's source refs. Admin commands talk to a remote URL. The operator's
cwd is irrelevant and must never influence behavior. This is a hard rule,
not a default.

### Target resolution for admin commands

Admin commands (`users`, `tokens`, `health`) need a URL and signing key.
Two modes, no fallback between them:

**Fleetless** — point at a URL directly:
```bash
mcp-app set-base-url https://my-app-xxx.a.run.app
export MCP_APP_SIGNING_KEY=...
mcp-app users add user@example.com
```

**Fleet** — resolve by name from active fleet:
```bash
mcp-app fleets use work
mcp-app users add --app echofit user@example.com
```

`--app` is fleet-only. No active fleet means `--app` is an error.
No `--app` with an active fleet means error — the fleet has multiple
solutions, you must specify which one.

Explicit `--url` and `--signing-key` flags always work regardless of mode.

## Lifecycle

```bash
# One-time setup
gcloud auth application-default login
pip install mcp-app mcp-app-cloudrun
mcp-app fleets register https://github.com/me/my-fleet.git --name work
mcp-app fleets use work

# Ongoing
mcp-app fleet list
mcp-app fleet deploy echofit
mcp-app fleet health
mcp-app users add --app echofit user@example.com
mcp-app tokens create --app echofit user@example.com
```

## The Sandwich

```
mcp-app build           ← mcp-app (knows the app structure)
    ↓
provider.deploy()       ← provider (cloud-specific)
    ↓
mcp-app health          ← mcp-app (knows the health endpoint)
mcp-app users add       ← mcp-app (knows the admin API, provider resolves signing key)
```

mcp-app owns everything except the one cloud-specific step in the middle. That step is delegated to a pip-installable provider that anyone can publish.

## Ecosystem Example

Jim runs a small company. He uses mcp-app services from multiple sources,
deployed across different platforms. He has three fleets: a shared team fleet,
a personal fleet, and a local dev fleet.

### Jim's solution repos

Jim wrote one app himself. The others are open source or third-party:

```python
# jim/sales-tools/sales_tools_mcp/__init__.py
from mcp_app import App
from sales_tools_mcp import tools
app = App(name="sales-tools", tools_module=tools)
```

He also uses `echomodel/echofit` (open source), a commercial MCP service from
Acme Corp that publishes a pre-built image (built with mcp-app), and a partner
service that doesn't use mcp-app at all.

### Jim's work fleet (shared with team)

```yaml
# jim/infra/fleet.yaml

providers:
  cloudrun:
    package: mcp-app-cloudrun
    config:
      project: jim-prod
      region: us-central1
  hackerhost:
    package: mcp-app-hackerhost
    config:
      team: jim-team
      tier: starter                   # cheap scaled-down infra

defaults:
  deploy: cloudrun
  runtime: mcp-app

solutions:
  sales-tools:
    source: jim/sales-tools
  echofit:
    source: echomodel/echofit
  acme-crm:
    source: ghcr.io/acmecorp/crm-mcp:v3.1
  experiments:
    source: jim/mcp-experiments
    deploy: hackerhost
  partner-api:
    source: ghcr.io/partner/their-service:latest
    runtime: none
```

### Jim's local fleet (his machine only)

```yaml
# ~/dotfiles/local-fleet/fleet.yaml

providers:
  local-docker:
    package: mcp-app-local-docker

defaults:
  deploy: local-docker
  runtime: mcp-app

solutions:
  sales-tools-dev:
    source: ~/ws/sales-tools
  echofit-dev:
    source: ~/ws/echofit
```

### Fleet registration

```bash
mcp-app fleets register https://github.com/jim/infra.git --name work
mcp-app fleets register ~/dotfiles/local-fleet --name local

mcp-app fleets list
#   * work   https://github.com/jim/infra.git
#     local  ~/dotfiles/local-fleet
```

### Jim's CI for the work fleet

**Option A: handles provider install himself**

```yaml
# jim/infra/.github/workflows/deploy.yml
name: Deploy fleet
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install mcp-app mcp-app-cloudrun mcp-app-hackerhost
      - run: mcp-app fleet deploy --all
```

**Option B: uses echomodel's reusable workflow**

```yaml
# jim/infra/.github/workflows/deploy.yml
name: Deploy fleet
on:
  push:
    branches: [main]

jobs:
  deploy:
    uses: echomodel/fleet-actions/.github/workflows/deploy.yml@v1
    with:
      providers: mcp-app-cloudrun mcp-app-hackerhost
```

**Option C: fleet.yaml declares provider packages**

The `package` field in each provider entry tells mcp-app what to install.
CI only needs to install mcp-app itself:

```yaml
# jim/infra/.github/workflows/deploy.yml
name: Deploy fleet
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install mcp-app
      - run: mcp-app fleet deploy --all
        # mcp-app reads provider packages from fleet.yaml, installs if missing
```

### Jim's day-to-day

```bash
# Work fleet
mcp-app fleets use work
mcp-app fleet list
#   sales-tools   cloudrun     https://sales-xxx.a.run.app      healthy
#   echofit       cloudrun     https://echofit-xxx.a.run.app     healthy
#   acme-crm      cloudrun     https://acme-xxx.a.run.app        healthy
#   experiments   hackerhost   https://exp.hackerhost.app         healthy
#   partner-api   cloudrun     https://partner.example.com        (unmanaged)

# Switch to local dev
mcp-app fleets use local
mcp-app fleet list
#   sales-tools-dev  local-docker  http://localhost:8080   healthy
#   echofit-dev      local-docker  http://localhost:8081   healthy

# JSON output includes full metadata:
# mcp-app fleet list --format=json
# [
#   {"name": "echofit-dev", "deploy": "local-docker", "runtime": "mcp-app",
#    "url": "http://localhost:8081", "status": "healthy",
#    "source": "~/ws/echofit"},
#   ...
# ]

# Deploy one app
mcp-app fleet deploy echofit-dev

# Manage users — same commands regardless of fleet
mcp-app users add --app echofit-dev user@example.com
```

### What each person touches

| Person | What they publish | What they configure |
|--------|------------------|-------------------|
| **Solution author** (echomodel, Jim, Acme) | `App` object in their package, or a container image | Nothing deployment-related |
| **Provider author** (echomodel, Bob, HackerHost) | pip package with entry point | Nothing fleet-related |
| **Operator** (Jim) | fleet.yaml per fleet + CI workflow | Provider config, solution list |

No one touches anyone else's stuff. Solution authors don't know about Jim's
fleets. Provider authors don't know about Jim's solutions. Each fleet.yaml is
the single place where providers and solutions meet.

## Design FAQ

### Why is provider `config` unstructured?

mcp-app doesn't validate the contents of a provider's `config` block. It passes
the dict straight through to the provider, which validates its own config.

This is intentional. Cloud Run needs `project` and `region`. HackerHost needs
`team` and `tier`. A future provider might need fields that don't exist yet.
mcp-app's schema defines the outer structure (`providers`, `config`, `solutions`)
but the provider-specific contents are opaque — defined and documented by the
provider package, not by mcp-app.

This is the same pattern as Terraform provider blocks, Kubernetes custom
resources, and Docker Compose driver options.

### Why don't provider credentials appear in fleet.yaml?

Providers handle their own authentication. Fleet.yaml configures *what* to deploy
and *where*, not *how to authenticate*. Examples:

- **cloudrun** uses Application Default Credentials (ADC). The operator runs
  `gcloud auth application-default login` once. The GCP SDK picks it up.
- **hackerhost** might use its own CLI login, an env var, or whatever auth
  HackerHost provides.
- **local-docker** needs no auth.

This keeps secrets out of version control entirely. Auth is machine state
(a login session, a token in a keyring), not config.

### Why two axes (deploy + runtime) instead of a single `managed` flag?

`deploy` and `runtime` are independent concerns:

- A solution can use Cloud Run for deploy and mcp-app for runtime management
- The same solution could move to HackerHost for deploy without changing runtime
- A non-mcp-app service can still be deployed and tracked (`runtime: none`)

A single `managed: true/false` conflates "is this an mcp-app service?" with
deployment details. Separating the axes means each can evolve independently.
Today `runtime` is either `mcp-app` or `none`. If mcp-app adds features later
(metrics, log aggregation, config push), every `runtime: mcp-app` solution
gets them automatically — no new flags needed.

### Why separate fleets instead of local override files?

An earlier design used a gitignored `.fleet.local.yaml` that extended the
shared fleet manifest with local-only solutions. This was rejected because
any mechanism that layers config on top of shared state risks mutating it —
even "additive" changes to existing objects can be destructive (e.g., changing
a region, adding a config field that alters provider behavior, overriding a
secret reference).

Separate fleets eliminate this entirely. Each fleet is its own world. Want
local docker instances? Put them in a `local` fleet. Want shared Cloud Run
services? They're in `work`. They never mix, never merge, never conflict.
Switch between them with `mcp-app fleets use`.
