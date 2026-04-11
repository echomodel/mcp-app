# Building an App with mcp-app

How to wire up an app that uses mcp-app for identity, user
management, and MCP server hosting.

## App __init__.py

Everything mcp-app needs from your app goes in `__init__.py`:

**Data-owning app** (no per-user credentials):

```python
# my_app/__init__.py
APP_NAME = "my-app"

from mcp_app.cli import create_admin_cli, create_mcp_cli

mcp_cli = create_mcp_cli(APP_NAME)
admin_cli = create_admin_cli(APP_NAME)
```

**API-proxy app** (per-user backend credentials):

```python
# my_app/__init__.py
APP_NAME = "my-app"

from pydantic import BaseModel
from mcp_app.context import register_profile
from mcp_app.cli import create_admin_cli, create_mcp_cli

class Profile(BaseModel):
    token: str

register_profile(Profile, expand=True)

mcp_cli = create_mcp_cli(APP_NAME)
admin_cli = create_admin_cli(APP_NAME)
```

`expand=True` generates typed CLI flags (`--token`) on the admin
CLI. `expand=False` accepts profile as a JSON string or `@file`.

## pyproject.toml Entry Points

```toml
[project]
name = "my-app"
dependencies = ["mcp-app"]

[project.scripts]
my-app = "my_app.cli:cli"           # app's own CLI (optional)
my-app-mcp = "my_app:mcp_cli"       # serve, stdio
my-app-admin = "my_app:admin_cli"    # connect, users, tokens, health
```

One `pipx install my-app` creates all three commands.

### Multi-package repos

If SDK, MCP, and CLI are separate installable packages, put the
mcp-app integration in the MCP package (where mcp-app is a
dependency):

```python
# mcp/my_app_mcp/__init__.py
from my_app import APP_NAME
from mcp_app.cli import create_admin_cli, create_mcp_cli

mcp_cli = create_mcp_cli(APP_NAME)
admin_cli = create_admin_cli(APP_NAME)
```

```toml
# mcp/pyproject.toml
[project.scripts]
my-app-mcp = "my_app_mcp:mcp_cli"
my-app-admin = "my_app_mcp:admin_cli"
```

## User Management Workflow

### First-time setup

```bash
# Local (filesystem store on this machine)
my-app-admin connect local

# Remote (deployed instance)
my-app-admin connect https://my-app.run.app --signing-key xxx
```

Saves mode to `~/.config/{app-name}/setup.json`. All subsequent
user commands route automatically.

### Managing users

```bash
# API-proxy app with expand=True — typed flags
my-app-admin users add alice@example.com --token xxx

# Data-owning app — no profile needed
my-app-admin users add alice@example.com

# API-proxy app with expand=False — JSON blob
my-app-admin users add alice@example.com --profile '{"client_id":"...","refresh_token":"..."}'
# or from file
my-app-admin users add alice@example.com --profile @creds.json

# List and revoke
my-app-admin users list
my-app-admin users revoke alice@example.com

# Health check (remote only)
my-app-admin health
```

### How routing works

`connect local` makes user commands write directly to the
filesystem store (`~/.local/share/{app-name}/users/`).

`connect <url>` makes user commands call the remote instance's
`/admin` REST API via HTTP.

Both use the `UserAuthStore` protocol — `DataStoreAuthAdapter`
for local, `RemoteAuthAdapter` for remote. The CLI calls the
same interface regardless of mode.

## Running the MCP Server

### Development (from repo directory)

```bash
mcp-app serve                      # HTTP on port 8080
mcp-app stdio --user local         # stdio
```

Reads `mcp-app.yaml` from the current directory.

### Installed app (from anywhere)

```bash
my-app-mcp serve                   # HTTP
my-app-mcp stdio --user local      # stdio
my-app-mcp stdio --user alice      # different user
```

Finds bundled `mcp-app.yaml` from the installed package.

### Registering with MCP clients

```bash
# Claude Code — installed app, stdio
claude mcp add my-app -- my-app-mcp stdio --user local

# Claude Code — remote HTTP
claude mcp add --transport http my-app \
  https://my-app.run.app/ \
  --header "Authorization: Bearer USER_TOKEN"

# Claude.ai — remote URL (works across web, mobile, Claude Code)
https://my-app.run.app/?token=USER_TOKEN
```

## Reading User Identity in the SDK

```python
from mcp_app.context import current_user

user = current_user.get()
user.email       # "alice@example.com" or "local"
user.profile     # typed Pydantic model (API-proxy) or None (data-owning)
```

Set automatically by:
- **HTTP**: identity middleware validates JWT, loads user record
- **stdio**: CLI loads user record using `--user` flag
- **Tests**: set directly in fixtures

### Data-owning app SDK

```python
from mcp_app.context import current_user
from mcp_app import get_store

class MySDK:
    def save_entry(self, data):
        user = current_user.get()
        store = get_store()
        store.save(user.email, "entries/today", data)
```

Or manage storage however the app chooses — `current_user.get().email`
is the identity, the app decides how to use it.

### API-proxy app SDK

```python
from mcp_app.context import current_user
import httpx

class MySDK:
    def list_items(self):
        user = current_user.get()
        token = user.profile.token
        resp = httpx.get("https://api.example.com/items",
                         headers={"Authorization": f"Bearer {token}"})
        return resp.json()
```

## Testing

### Set current_user in test fixtures

```python
from mcp_app.context import current_user
from mcp_app.models import UserRecord

@pytest.fixture(autouse=True)
def test_user():
    token = current_user.set(UserRecord(email="test-user"))
    yield
    current_user.reset(token)
```

### Full-stack HTTP test

```python
from mcp_app.bootstrap import build_app
import httpx

@pytest.fixture
def app_client(tmp_path):
    os.environ["APP_USERS_PATH"] = str(tmp_path / "users")
    os.environ["SIGNING_KEY"] = "test-key-32chars-minimum-length!!"
    app, mcp, store, config = build_app()
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")
```

If it works in httpx ASGI transport, it works in Docker.
