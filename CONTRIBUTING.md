# Contributing to mcp-app

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
- AdminClient is stateless — takes a URL and signing key, makes REST calls
- MCP admin tools take `base_url` and `signing_key` as explicit parameters
- No internal references to gapp, Cloud Run, or any deployment tool
- The admin tools don't know how the service was deployed or where the signing
  key came from

### cwd is never used for deploy or admin

`mcp-app serve` and `mcp-app build` read `mcp-app.yaml` from the current
directory — you're the solution developer working in your repo.

All other commands ignore the current directory entirely. Deploy reads from
fleet source refs. Admin commands talk to a remote URL. The operator's cwd
is irrelevant and must never influence behavior. This is a hard rule, not
a default.

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

## SDK-First Architecture

All business logic lives in the core layer, not in CLI or MCP wrappers.

- `admin_client.py` — AdminClient SDK, REST client for deployed instances
- `cli.py` — thin Click wrapper, calls SDK, formats output
- `admin_tools.py` — thin MCP wrapper, calls SDK, handles tool schema

If you're writing logic in a CLI command or MCP tool handler, stop and move
it to the SDK.

## Testing

Tests use httpx's ASGI transport to run the full stack in-memory — no mocks,
no network, no ports. See `tests/unit/test_admin_client.py` for the pattern:

```python
transport = httpx.ASGITransport(app=starlette_app)
http_client = httpx.AsyncClient(transport=transport, base_url="http://test")
client = AdminClient("http://test", signing_key, http_client=http_client)
```

AdminClient → httpx → ASGI → Starlette → admin.py → FileSystemUserDataStore → tmp_path.

## Dependencies

httpx is a direct dependency (used by AdminClient). It is also the #2 Python
HTTP client by downloads (~500M/month), maintained by Encode (author of Django
REST Framework and Starlette), and a hard dependency of every major AI SDK
(OpenAI, Anthropic, Google GenAI). It was already a transitive dependency via
starlette and mcp.
