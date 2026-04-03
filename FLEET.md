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

```yaml
# fleet.yaml
provider: cloudrun
provider_config:
  project: my-project
  region: us-central1

solutions:
  echofit:
    source: echomodel/echofit
  monarch-mcp:
    source: echomodel/monarch-access
    provider_config:
      region: us-east1              # per-solution override
  third-party:
    source: ghcr.io/someone/their-app:v2
    managed: false                  # deploy only, no admin
```

**Source field supports three shapes:**
- `owner/repo` — GitHub repo, mcp-app clones and builds
- `registry.io/image:tag` — pre-built container image, deploy directly
- `./local-path` — relative to fleet repo or absolute, for dev/testing

**Provider config** has defaults at the top level, overridable per-solution.

**`managed: false`** marks solutions that aren't mcp-app services (no `/admin`, no `/health`). Deploy and track only.

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

## No Local Secrets

Signing keys are generated at deploy time and stored in the provider's secret store (e.g., GCP Secret Manager). They never touch the operator's disk.

When the operator runs admin commands, the provider resolves the signing key on demand using the operator's existing cloud auth (e.g., ADC via `gcloud auth application-default login`):

```
mcp-app users add --app echofit user@example.com
  → reads fleet.yaml → echofit uses cloudrun provider
  → provider fetches signing key from Secret Manager (via ADC)
  → mcp-app mints admin JWT in memory
  → calls /admin/users on the deployed URL
  → key is garbage collected, never written to disk
```

## Lifecycle

```bash
# One-time setup
gcloud auth application-default login
pip install mcp-app-cloudrun
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

He also uses `echomodel/echofit` (open source) and a commercial MCP service
from Acme Corp that publishes a pre-built image.

### Jim's fleet repo

```yaml
# jim/my-fleet/fleet.yaml

# Default provider for most things
provider: cloudrun
provider_config:
  project: jim-prod
  region: us-central1

solutions:

  # Jim's own app — GitHub repo, build from source
  sales-tools:
    source: jim/sales-tools

  # Open source app — different org, same provider
  echofit:
    source: echomodel/echofit

  # Commercial app — pre-built image, no build step
  acme-crm:
    source: ghcr.io/acmecorp/crm-mcp:v3.1

  # Jim's experimental app — runs on HackerHost instead of Cloud Run
  experiments:
    source: jim/mcp-experiments
    provider: hackerhost
    provider_config:
      api_key_secret: jim-hh-key
      region: eu-west

  # Local dev instance — runs in Docker on Jim's machine
  sales-tools-dev:
    source: ./sales-tools-local
    provider: local-docker
    provider_config:
      port: 9090

  # Third-party service Jim doesn't manage — just tracks the URL
  partner-api:
    source: ghcr.io/partner/their-service:latest
    managed: false
```

Six solutions. Three source types (GitHub repos, container images, local path).
Three providers (Cloud Run, HackerHost, local Docker). One fleet manifest.

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

```yaml
# jim/my-fleet/fleet.yaml (provider section expanded)
providers:
  cloudrun:
    package: mcp-app-cloudrun
  hackerhost:
    package: mcp-app-hackerhost
  local-docker:
    package: mcp-app-local-docker

# ... rest of fleet.yaml same as above
```

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
#   sales-tools      cloudrun   https://sales-xxx.a.run.app      healthy
#   echofit          cloudrun   https://echofit-xxx.a.run.app     healthy
#   acme-crm         cloudrun   https://acme-xxx.a.run.app        healthy
#   experiments      hackerhost https://exp.hackerhost.app         healthy
#   sales-tools-dev  local      http://localhost:9090              healthy
#   partner-api      —          https://partner.example.com        unmanaged

# Deploy one app
mcp-app fleet deploy echofit

# Health check everything
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
