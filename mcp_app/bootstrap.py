"""Bootstrap — reads mcp-app.yaml, discovers tools, builds the app."""

import contextlib
import functools
import importlib
import inspect
import os
from pathlib import Path

import yaml
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp_app.admin import create_admin_app
from mcp_app.bridge import DataStoreAuthAdapter
from mcp_app.data_store import FileSystemUserDataStore
from mcp_app.middleware import JWTMiddleware
from mcp_app.verifier import JWTVerifier


# Built-in store aliases
STORE_ALIASES = {
    "filesystem": FileSystemUserDataStore,
}

# Built-in middleware aliases — for custom middleware via module path
MIDDLEWARE_ALIASES = {
    "user-identity": JWTMiddleware,
}


def load_config(config_path: Path | None = None) -> dict:
    """Load mcp-app.yaml from cwd or specified path."""
    if config_path is None:
        config_path = Path.cwd() / "mcp-app.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"No mcp-app.yaml found at {config_path}")
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def _resolve_class(value: str, aliases: dict):
    """Resolve an alias or module path to a class."""
    if "." not in value:
        if value not in aliases:
            raise ValueError(f"Unknown alias '{value}'. Valid: {', '.join(sorted(aliases))}")
        return aliases[value]
    module_path, class_name = value.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _discover_tools(module_path: str) -> list:
    """Import a module and find all async functions (tools)."""
    module = importlib.import_module(module_path)
    tools = []
    for name, obj in inspect.getmembers(module, inspect.isfunction):
        if inspect.iscoroutinefunction(obj) and not name.startswith("_"):
            tools.append(obj)
    return tools


def _require_identity(func):
    """Wrap a tool function to enforce that current_user is set."""
    from mcp_app.context import current_user

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            current_user.get()
        except LookupError:
            raise ValueError(
                "No authenticated user identity established. "
                "HTTP: ensure SIGNING_KEY is set. "
                "stdio: configure stdio.user in mcp-app.yaml."
            )
        return await func(*args, **kwargs)
    return wrapper


def build_mcp(config: dict) -> FastMCP:
    """Create FastMCP instance and register discovered tools."""
    name = config.get("name", "mcp-app")
    mcp = FastMCP(name, stateless_http=True, json_response=True, streamable_http_path="/")
    mcp.settings.transport_security.enable_dns_rebinding_protection = False

    tools_module = config.get("tools")
    if not tools_module:
        raise ValueError("mcp-app.yaml must specify 'tools' module path")

    for func in _discover_tools(tools_module):
        mcp.tool()(_require_identity(func))

    return mcp


def build_store(config: dict):
    """Create the data store from config."""
    store_value = config.get("store", "filesystem")
    store_cls = _resolve_class(store_value, STORE_ALIASES)
    app_name = config.get("name", "mcp-app")
    return store_cls(app_name=app_name)


def build_asgi(config: dict, mcp: FastMCP, store) -> Starlette:
    """Build the full ASGI app with identity middleware and admin.

    Identity middleware (user-identity) always runs. Additional custom
    middleware can be specified in mcp-app.yaml:

        middleware:
          - my_app.auth.CustomMiddleware

    Set middleware to an empty list to disable all middleware (no auth).
    Omit middleware entirely for the default (user-identity only).
    """
    auth_store = DataStoreAuthAdapter(store)
    verifier = JWTVerifier(auth_store)
    admin_app = create_admin_app(auth_store)

    inner = mcp.streamable_http_app()

    # Determine middleware stack
    if "middleware" in config and config["middleware"] == []:
        # Explicitly empty — no middleware (no auth)
        wrapped = inner
    elif "middleware" in config:
        # Custom middleware specified — use as-is (user must include
        # user-identity explicitly if they want it)
        wrapped = inner
        for mw_value in reversed(config["middleware"]):
            mw_cls = _resolve_class(mw_value, MIDDLEWARE_ALIASES)
            wrapped = mw_cls(wrapped, verifier, store)
    else:
        # Default — user-identity runs automatically
        wrapped = JWTMiddleware(inner, verifier)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    return Starlette(
        routes=[
            Mount("/admin", app=admin_app),
            Mount("/", app=wrapped),
        ],
        lifespan=lifespan,
    )


def build_stdio(config_path: Path | None = None):
    """Build for stdio transport: tools + store, no middleware/admin/ASGI."""
    config = load_config(config_path)
    store = build_store(config)

    name = config.get("name", "mcp-app")
    mcp = FastMCP(name)

    tools_module = config.get("tools")
    if not tools_module:
        raise ValueError("mcp-app.yaml must specify 'tools' module path")

    for func in _discover_tools(tools_module):
        mcp.tool()(_require_identity(func))

    return mcp, store, config


def build_app(config_path: Path | None = None):
    """One-shot: load config, build everything, return ASGI app + mcp + store."""
    config = load_config(config_path)
    store = build_store(config)
    mcp = build_mcp(config)
    app = build_asgi(config, mcp, store)
    return app, mcp, store, config


def run_stdio(config_path: Path | None = None, user: str | None = None):
    """One-shot: build, load user, run stdio. Used by mcp-app stdio and app CLIs.

    Args:
        config_path: Path to mcp-app.yaml. None = read from cwd.
        user: User identity. Overrides stdio.user from yaml.
    """
    import asyncio
    import mcp_app
    from mcp_app.context import current_user, hydrate_profile
    from mcp_app.models import UserRecord
    from mcp_app.bridge import DataStoreAuthAdapter

    mcp, store, config = build_stdio(config_path)
    mcp_app._store = store

    user_id = user or config.get("stdio", {}).get("user")
    if not user_id:
        raise RuntimeError(
            "No user specified. Use --user flag or configure stdio.user "
            "in mcp-app.yaml:\n\n  stdio:\n    user: \"local\"\n"
        )

    adapter = DataStoreAuthAdapter(store)
    user_record = asyncio.run(adapter.get_full(user_id))
    if user_record:
        user_record.profile = hydrate_profile(user_record.profile)
    else:
        user_record = UserRecord(email=user_id)

    current_user.set(user_record)
    mcp.run(transport="stdio")
