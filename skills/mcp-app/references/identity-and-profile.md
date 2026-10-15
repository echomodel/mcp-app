# User identity and profile

Read this when a tool or SDK method needs to know who the caller is, when
an app needs per-user data or backend credentials, or when declaring or
changing the app's profile model. Admin commands that read and write
profiles are in `operate.md`.

## How it works

In HTTP mode, identity middleware validates the JWT, loads the full
user record from the store (auth + profile in one read), and sets
`current_user` ContextVar. In stdio mode, the CLI loads the user
record from the store using the `--user` flag.

The SDK reads it:

```python
from mcp_app.context import current_user

user = current_user.get()
user.email       # "alice@example.com" (HTTP) or "local" (stdio)
user.profile     # typed Pydantic model or raw dict
```

## Two app patterns — same framework, different SDK reads

**Data-owning** (owns user data — food logs, notes):

```python
from mcp_app.context import current_user
from mcp_app import get_store

class MySDK:
    def save_entry(self, data):
        user = current_user.get()
        store = get_store()
        store.save(user.email, "entries/today", data)
```

The SDK reads `current_user.get().email` for user identity. How
it stores data is the app's choice — `get_store()` provides
mcp-app's per-user key-value store, but the SDK can also manage
its own storage (XDG paths, custom databases, etc.) using the
email as the scoping key.

**API-proxy** (wraps external API — financial data, task management):

```python
from mcp_app.context import current_user
import httpx

class MySDK:
    def list_items(self):
        user = current_user.get()
        api_key = user.profile.api_key  # typed via Pydantic
        resp = httpx.get("https://api.example.com/items",
                         headers={"Authorization": f"Bearer {api_key}"})
        return resp.json()
```

Both use `current_user.get()`. The middleware is the same (identity
only). The SDK decides what to read from the user context.

## Profile registration

The app declares its per-user profile shape:

```python
# my_solution/__init__.py
from pydantic import BaseModel, Field
from mcp_app import App
from my_solution.mcp import tools

class Profile(BaseModel):
    api_key: str = Field(description="API key from https://example.com/settings")

app = App(
    name="my-solution",
    tools_module=tools,
    profile_model=Profile,
    profile_expand=True,
)
```

A data-owning app might declare a different shape entirely —
`display_name`, `default_region`, or whatever per-user config it
needs. mcp-app does not interpret the profile; the app owns
both the model and the meaning.

`profile_expand=True` generates typed CLI flags from the model
(e.g., `--api-key` from the example in this section).
`profile_expand=False` accepts the profile as a JSON blob or `@file`.
Profile registration happens automatically when the `App` is
constructed — no separate `register_profile()` call needed.

**Field descriptions are the self-documentation mechanism for
API-proxy apps.** The Pydantic model is the single place where
the app author declares what per-user credentials the app needs.
The field name is the app author's choice (`token`, `api_key`,
`github_pat`, `plaid_access_token` — mcp-app doesn't enforce
or assume any naming). The `Field(description=...)` should say
what the credential is, what system it connects to, and where
the operator can obtain it.

This matters because the admin CLI surfaces field names and
descriptions in `--help` output for `users add` and
`users update-profile`. An operator (or agent) managing a
deployed instance discovers what credentials the app needs
by running `my-solution-admin users add --help` — no source
code or documentation needed. This is the re-discovery path:
months later, when a token needs rotating, the CLI tells you
what each field is for.

**Always include `Field(description=...)` on every profile field.**
A bare `api_key: str` works mechanically but gives operators
nothing to work with when they encounter the field in a CLI or
admin tool. For credentials, a good description answers: what is
this, what system does it authenticate to, and where do I get one.
For non-credential fields, describe what the value controls and
what valid values look like.

**Propagate this into the implementing app.** When creating or
reviewing an API-proxy app:

1. **Code comment on the Profile class** — explain that field
   descriptions drive CLI help text and are the primary way
   operators discover what credentials the app needs.
2. **CONTRIBUTING.md** — document that profile fields must
   include `Field(description=...)` and what a good description
   looks like. This ensures future contributors maintain the
   self-documentation when adding or changing profile fields.

These are not optional polish — they are the re-discovery
mechanism. Without descriptions, an operator returning to the
app months later sees `--api-key` (or whatever the field is)
in `--help` with no explanation of what the value is for, what
system it connects to, or where to get a new one.

