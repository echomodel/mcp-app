# Testing and validation

Read this when writing or running tests for an mcp-app solution: SDK unit
tests, full-stack HTTP tests, stdio validation, the framework test suite
mcp-app ships, or agent evals. After building or changing a solution, write
tests and validate both transports before presenting the compliance
dashboard (`review-checklist.md`).

Step 2 mints an admin JWT with the signing key. That is part of the
current auth model; `auth.md` describes it.

## Step 0: Verify the local install reflects the working tree

Anything in this section that runs the locally-installed CLI
(`<name>-mcp`, `<name>-admin`) is only valid if that install
actually executes the code in the working tree. Two install
shapes look identical from outside but behave very differently:

- **Editable install** (`pipx install -e .` or `pip install -e .`)
  — the entry point dispatches into the source tree. Edits to
  source files are picked up on the next CLI invocation. This
  is what every step below assumes.
- **Snapshot install** (plain `pipx install .` or
  `pip install .`) — the entry point runs whatever code was
  installed at install time. Subsequent edits to the source tree
  have no effect on the installed CLI until the next reinstall.

Snapshot installs are the silent killer for reviews and
for any returning operator picking up the repo days later: the
stdio recipe below can pass cleanly against a stale snapshot
while the working tree's actual changes remain unverified —
a false "validation green."

`<cli> --version` is **not** a sufficient check. The version
string can match across both install kinds even when the
installed code differs from the working tree, because version
bumps are explicit and source edits do not change the version
string by themselves.

The reliable verification primitive for `pipx`-managed installs:

```bash
pipx list 2>&1 | grep -A5 <package-name>
```

The output for a correct install includes the literal
`(editable)` marker on the package line.

**Before any agent-driven smoke test (`claude mcp add`,
`claude -p`, or the equivalent), run this check on the install
the agent CLI resolves to** — typically `~/.local/bin/<name>-mcp`,
the pipx binary. A `.venv` editable install on the side doesn't
satisfy this: the agent CLI walks `$PATH` and hits the pipx
binary first, so a stale pipx snapshot silently invalidates the
test even if your venv has the right source.

Absence of the `(editable)` marker is a stop-the-world block
for that smoke test. Fix it before proceeding:

```bash
pipx install -e . --force
```

(Or `pip install -e .` if pip-managed in a venv.)

For installers other than `pipx`, find the equivalent
editable-marker check and apply the same precondition.

## Step 1: SDK unit tests

Test business logic directly. Set `current_user` and env vars
in fixtures — the SDK reads these at runtime:

```python
import os
import pytest
from mcp_app.context import current_user
from mcp_app.models import UserRecord

@pytest.fixture(autouse=True)
def isolated_env(tmp_path):
    os.environ["MY_SOLUTION_DATA"] = str(tmp_path / "data")
    os.environ["MY_SOLUTION_CONFIG"] = str(tmp_path / "config")
    token = current_user.set(UserRecord(email="test-user"))
    yield
    current_user.reset(token)
    del os.environ["MY_SOLUTION_DATA"]
    del os.environ["MY_SOLUTION_CONFIG"]

def test_saves_entry():
    sdk = MySDK()
    result = sdk.save_entry({"item": "apple"})
    assert result["success"]

def test_multi_user_isolation(tmp_path):
    """Data for different users doesn't mix."""
    token = current_user.set(UserRecord(email="alice@example.com"))
    try:
        sdk = MySDK()
        sdk.save_entry({"item": "apple"})
    finally:
        current_user.reset(token)

    token = current_user.set(UserRecord(email="bob@example.com"))
    try:
        sdk = MySDK()
        sdk.save_entry({"item": "banana"})
    finally:
        current_user.reset(token)
```

## Step 2: Full-stack HTTP validation

Validate the entire ASGI stack in-memory using httpx's ASGI
transport. No server process, no port, no Docker. httpx is a
dependency of mcp-app — the solution gets it for free.

**If it works here, it works in uvicorn, it works in Docker.**

```python
import httpx
import jwt as pyjwt
from datetime import datetime, timezone, timedelta
from my_app import app

@pytest.fixture
def app_client(tmp_path):
    os.environ["APP_USERS_PATH"] = str(tmp_path / "users")
    os.environ["SIGNING_KEY"] = "test-key"
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")

@pytest.mark.asyncio
async def test_register_and_call_tool(app_client):
    admin_token = pyjwt.encode(
        {"sub": "admin", "scope": "admin",
         "iat": datetime.now(timezone.utc),
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        "test-key", algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    resp = await app_client.post(
        "/admin/users",
        json={"email": "user@example.com",
              "profile": {"api_key": "test-key"}},
        headers=headers,
    )
    assert resp.status_code == 200
    assert "token" in resp.json()  # the mcp-app JWT for this user
```

## Step 3: stdio validation

Unit and framework tests don't exercise the real MCP transport.
Drive at least one tool through stdio end-to-end before declaring
the app ready.

**Precondition: install is editable.** This recipe runs the
locally-installed `<name>-mcp` CLI. If the install is a
snapshot rather than editable, the recipe will round-trip
successfully against stale code and produce a misleading green
result. Confirm before running:

```bash
pipx list 2>&1 | grep -A5 <package-name>
```

Look for the `(editable)` marker on the package line. If it's
absent, run `pipx install -e . --force` (or `pip install -e .`)
from the repo root. See "Step 0: Verify the local install
reflects the working tree" above for the full rationale.

**Use a throwaway project directory** so the test registration
doesn't pollute your user-scope or working-project MCP configs:

```bash
mkdir -p /tmp/my-solution-smoketest && cd /tmp/my-solution-smoketest
claude mcp add my-solution -- my-solution-mcp stdio --user local
claude mcp list | grep my-solution   # expect ✓ Connected
```

Project-scoped registration in `/tmp/<name>-smoketest` is throwaway
by design — `rm -rf` the dir to undo, no `claude mcp remove`
gymnastics, and your real configs stay clean.

**Drive a real tool call non-interactively:**

```bash
claude -p "Use my-solution to <do the simplest read-only thing> and report the result" \
    --allowedTools "mcp__my-solution__<read_only_tool_name>"
```

Pick a read-only tool (list, get, search) — no mutation, no cost
beyond the API roundtrip. The `--allowedTools` flag scopes the
agent so it can't fall back to other MCP tools or shell commands;
if the prompt succeeds, it's because the stdio transport
round-tripped successfully.

**Reading the result:**

- Tool returns real data from the upstream API → smoke test
  passed: registration, transport, and the full SDK code path
  work end-to-end.
- Tool returns an error message (e.g. "no access token
  configured for your profile") → smoke test did NOT pass. The
  transport may be fine, but the smoke test isn't complete until
  real data round-trips. Configure a user/account and re-run.
  If no user is configured, register one (run the app's setup
  flow); the smoke test is not "done" until real data flows.
- `claude -p` errors before any tool call (server failed to
  start, command not found, args rejected) → registration is
  broken. Fix before moving on.

A smoke test is a happy-path proof. Error messages belong in
negative tests where the failure IS the assertion — not in the
smoke test's pass criteria.

This recipe also works for verifying any *deployed* instance —
register HTTP transport instead and run the same `claude -p`
prompt.

## Step 4: Run tests

```bash
pytest tests/unit/ -v
```

All tests must pass before the compliance dashboard.

## Step 5: mcp-app framework test suite

mcp-app ships reusable tests that check auth enforcement,
user admin, JWT handling, CLI wiring, tool protocol compliance,
and SDK test coverage — against YOUR app. These are the
authoritative verification that the app is correctly built on
the framework.

**Check if `tests/framework/` exists.** If it does, run it:

```bash
pytest tests/framework/ -v
```

If it passes, the app is verified. If it fails, investigate —
the failure is either a real compliance issue or an upstream
bug (check mcp-app's issue tracker).

**If `tests/framework/` does not exist, create it now:**

`tests/framework/conftest.py` — the only file that differs
per app (points at your `App` object):

```python
import pytest
from my_solution import app as my_app

@pytest.fixture(scope="session")
def app():
    return my_app
```

`tests/framework/test_framework.py` — identical across all
mcp-app solutions:

```python
from mcp_app.testing.iam import *
from mcp_app.testing.wiring import *
from mcp_app.testing.tools import *
from mcp_app.testing.health import *
```

Then run:

```bash
pytest tests/framework/ -v
```

Zero failures means: auth works, admin works, tools are wired,
identity is enforced, and the SDK has test coverage for every
tool.

**When to run these tests:**
- After adopting the framework test suite for the first time
- After upgrading mcp-app to a newer version
- After any migration or structural change
- As part of any compliance review

## Step 6: Agent evals (when tools can damage data)

Tests prove the tools work; an agent eval proves an agent **uses** them
correctly from their descriptions alone. Run one when adding or reworking
tools that write, delete, or edit by position, after changing a tool's
description, and before releasing a breaking change to the tool surface.
Method, pass criteria, and verified harness recipes are in `agent-evals.md`,
alongside this file.

## When to stub

- **Network I/O** — stub HTTP clients, external API calls
- **Cloud CLIs** — mock at the SDK function boundary
- **Everything else** — real code, real files, real config

