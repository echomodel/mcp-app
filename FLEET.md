# Fleet Management

mcp-app evolves from a framework for building individual MCP servers into the full lifecycle tool: build, deploy, manage, and fleet-track mcp-app services across any cloud or local environment.

## Three Layers, Three Owners

| Layer | Where it lives | Who owns it |
|-------|---------------|-------------|
| **App definition** | `mcp-app.yaml` in solution repo | Solution author |
| **Fleet manifest** | `fleet.yaml` in operator's fleet repo | Operator |
| **Deploy provider** | pip-installable package | Anyone |

## Solution Repo — Unchanged

A solution repo contains only the app definition. No deploy config, no provider references, no coupling to any cloud:

```yaml
# mcp-app.yaml
name: echofit
tools: echofit.mcp.tools
store: filesystem
middleware:
  - user-identity
```

## Fleet Repo — Operator-Scoped Registry

A git repo serving as a durable, portable registry of what's deployed and where. Like the Claude Code plugin marketplace pattern — a git repo as a registry.

### Schema

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

## Lifecycle

```bash
# One-time setup
gcloud auth application-default login
pip install mcp-app mcp-app-cloudrun
mcp-app fleet add https://github.com/me/my-fleet.git

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
deployed across different platforms. Here's his full setup.

### Jim's solution repos

Jim wrote one app himself. The others are open source or third-party:

```yaml
# jim/sales-tools/mcp-app.yaml — Jim's own app
name: sales-tools
tools: sales_tools.mcp.tools
store: filesystem
middleware:
  - user-identity
```

He also uses `echomodel/echofit` (open source), a commercial MCP service from
Acme Corp that publishes a pre-built image (built with mcp-app), and a partner
service that doesn't use mcp-app at all.

### Jim's fleet repo

```yaml
# jim/my-fleet/fleet.yaml

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
  local-docker:
    package: mcp-app-local-docker

defaults:
  deploy: cloudrun
  runtime: mcp-app

solutions:

  # Jim's own app — GitHub repo, build from source
  sales-tools:
    source: jim/sales-tools

  # Open source app — different org, same defaults
  echofit:
    source: echomodel/echofit

  # Commercial app — pre-built image, built with mcp-app
  # (runtime: mcp-app inherited — admin tools work because Acme used the framework)
  acme-crm:
    source: ghcr.io/acmecorp/crm-mcp:v3.1

  # Jim's experimental app — different deploy provider, same runtime
  experiments:
    source: jim/mcp-experiments
    deploy: hackerhost

  # Partner service — not built with mcp-app, deploy and track only
  partner-api:
    source: ghcr.io/partner/their-service:latest
    runtime: none
```

Five shared solutions. Three source types (GitHub repos, container images, local path).
Two deploy providers (Cloud Run, HackerHost). Two runtime modes (mcp-app, none).
One fleet manifest. Jim also has a `.fleet.local.yaml` with a local-docker dev
instance that only he sees.

### Jim's CI — Option A: handles provider install himself

```yaml
# jim/my-fleet/.github/workflows/deploy.yml
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

### Jim's CI — Option B: uses echomodel's reusable workflow

```yaml
# jim/my-fleet/.github/workflows/deploy.yml
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

### Jim's CI — Option C: fleet.yaml declares provider packages

The `package` field in each provider entry tells mcp-app what to install.
CI only needs to install mcp-app itself:

```yaml
# jim/my-fleet/.github/workflows/deploy.yml
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
# See everything
mcp-app fleet list
#   sales-tools      cloudrun     https://sales-xxx.a.run.app      healthy
#   echofit          cloudrun     https://echofit-xxx.a.run.app     healthy
#   acme-crm         cloudrun     https://acme-xxx.a.run.app        healthy
#   experiments      hackerhost   https://exp.hackerhost.app         healthy
#   partner-api      cloudrun     https://partner.example.com        (unmanaged)
#   sales-tools-dev  local-docker http://localhost:9090              healthy  (local)

# JSON output includes full metadata:
# mcp-app fleet list --format=json
# [
#   {"name": "echofit", "deploy": "cloudrun", "runtime": "mcp-app",
#    "url": "https://echofit-xxx.a.run.app", "status": "healthy",
#    "scope": "fleet", "source": "echomodel/echofit"},
#   {"name": "sales-tools-dev", "deploy": "local-docker", "runtime": "mcp-app",
#    "url": "http://localhost:9090", "status": "healthy",
#    "scope": "local", "source": "./sales-tools-local"},
#   ...
# ]

# Deploy one app
mcp-app fleet deploy echofit

# Health check managed services
mcp-app fleet health

# Manage users — provider resolves signing key, no secrets on disk
mcp-app users add --app sales-tools user@example.com
mcp-app users add --app echofit user@example.com
```

### What each person touches

| Person | What they publish | What they configure |
|--------|------------------|-------------------|
| **Solution author** (echomodel, Jim, Acme) | `mcp-app.yaml` in their repo, or a container image | Nothing deployment-related |
| **Provider author** (echomodel, Bob, HackerHost) | pip package with entry point | Nothing fleet-related |
| **Operator** (Jim) | fleet.yaml + CI workflow | Provider config, solution list |

No one touches anyone else's stuff. Solution authors don't know about Jim's fleet.
Provider authors don't know about Jim's solutions. Jim's fleet.yaml is the only
place all three meet.

## Local Overrides

Fleet.yaml is shared — committed, versioned, same for the whole team. But
individual operators may want local dev instances, personal provider overrides,
or experimental solutions that don't belong in the shared manifest.

A `.fleet.local.yaml` in the fleet repo (gitignored) merges on top of
fleet.yaml at runtime:

```yaml
# .fleet.local.yaml (gitignored — never committed)
providers:
  local-docker:
    package: mcp-app-local-docker

solutions:
  sales-tools-dev:
    source: ./sales-tools-local
    deploy: local-docker
  echofit:
    deploy: local-docker              # override shared solution to run locally
```

- Local-only solutions appear in `mcp-app fleet list` for that operator only
- Shared solutions can be overridden (e.g., run echofit locally instead of on Cloud Run)
- Other team members never see it
- Same pattern as `.env.local`, `docker-compose.override.yml`

The fleet repo's `.gitignore` includes `.fleet.local.yaml` by default.

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
