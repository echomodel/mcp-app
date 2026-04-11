"""Bootstrap — builds the MCP app from Python objects, no config files."""

import asyncio
import contextlib
import functools
import inspect
import os
from pathlib import Path
from types import ModuleType

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mcp_app.admin import create_admin_app
from mcp_app.bridge import DataStoreAuthAdapter
from mcp_app.data_store import FileSystemUserDataStore
from mcp_app.middleware import JWTMiddleware
from mcp_app.verifier import JWTVerifier


# Built-in store aliases
STORE_ALIASES = {
    "filesystem": FileSystemUserDataStore,
}

# Built-in middleware aliases
MIDDLEWARE_ALIASES = {
    "user-identity": JWTMiddleware,
}


def _resolve_class(value: str, aliases: dict):
    """Resolve an alias or module path to a class."""
    import importlib as _il
    if "." not in value:
        if value not in aliases:
            raise ValueError(f"Unknown alias '{value}'. Valid: {', '.join(sorted(aliases))}")
        return aliases[value]
    module_path, class_name = value.rsplit(".", 1)
    module = _il.import_module(module_path)
    return getattr(module, class_name)


def _discover_tools_from_module(module: ModuleType) -> list:
    """Find all public async functions in a module."""
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
                "stdio: pass --user flag."
            )
        return await func(*args, **kwargs)
    return wrapper


def _build_mcp(name: str, tools_module: ModuleType) -> FastMCP:
    """Create FastMCP instance and register discovered tools."""
    mcp = FastMCP(name, stateless_http=True, json_response=True, streamable_http_path="/")
    mcp.settings.transport_security.enable_dns_rebinding_protection = False

    for func in _discover_tools_from_module(tools_module):
        mcp.tool()(_require_identity(func))

    return mcp


def _build_store(name: str, store: str = "filesystem"):
    """Create the data store."""
    store_cls = _resolve_class(store, STORE_ALIASES)
    return store_cls(app_name=name)


def build_asgi(name: str, tools_module: ModuleType,
               store_backend: str = "filesystem",
               middleware: list[str] | None = None) -> tuple:
    """Build the full ASGI app.

    Args:
        name: App name (server name, store paths).
        tools_module: Python module containing async tool functions.
        store_backend: Store alias or module path. Default: "filesystem".
        middleware: Custom middleware list. None = user-identity (default).
            Empty list = no auth.

    Returns:
        (app, mcp, store) tuple.
    """
    store = _build_store(name, store_backend)
    mcp = _build_mcp(name, tools_module)

    auth_store = DataStoreAuthAdapter(store)
    verifier = JWTVerifier(auth_store)
    admin_app = create_admin_app(auth_store)

    inner = mcp.streamable_http_app()

    if middleware is not None and middleware == []:
        wrapped = inner
    elif middleware is not None:
        wrapped = inner
        for mw_value in reversed(middleware):
            mw_cls = _resolve_class(mw_value, MIDDLEWARE_ALIASES)
            wrapped = mw_cls(wrapped, verifier, store)
    else:
        wrapped = JWTMiddleware(inner, verifier)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    async def health(request):
        return JSONResponse({"status": "ok"})

    app = Starlette(
        routes=[
            Route("/health", health),
            Mount("/admin", app=admin_app),
            Mount("/", app=wrapped),
        ],
        lifespan=lifespan,
    )

    return app, mcp, store


def build_app(name: str = None, tools_module: ModuleType = None,
              store_backend: str = "filesystem",
              middleware: list[str] | None = None,
              config: dict | None = None) -> tuple:
    """One-shot: build everything, return (app, mcp, store, config).

    Either pass name + tools_module directly, or pass a config dict
    with 'name' and 'tools' (module path string) keys.
    """
    if config:
        import importlib
        name = name or config.get("name", "mcp-app")
        if tools_module is None:
            tools_path = config.get("tools")
            if not tools_path:
                raise ValueError("config must include 'tools' module path")
            tools_module = importlib.import_module(tools_path)
        store_backend = config.get("store", store_backend)
        middleware = config.get("middleware", middleware)

    if not name:
        raise ValueError("name is required")
    if tools_module is None:
        raise ValueError("tools_module is required")

    app, mcp, store = build_asgi(name, tools_module, store_backend, middleware)
    return app, mcp, store, {"name": name}


def run_stdio(name: str, tools_module: ModuleType, user: str,
              store_backend: str = "filesystem"):
    """One-shot: build, load user, run stdio.

    Args:
        name: App name.
        tools_module: Python module containing async tool functions.
        user: User identity (required).
        store_backend: Store alias or module path.
    """
    import mcp_app
    from mcp_app.context import current_user, hydrate_profile
    from mcp_app.models import UserRecord

    store = _build_store(name, store_backend)
    mcp = FastMCP(name)

    for func in _discover_tools_from_module(tools_module):
        mcp.tool()(_require_identity(func))

    mcp_app._store = store

    adapter = DataStoreAuthAdapter(store)
    user_record = asyncio.run(adapter.get_full(user))
    if user_record:
        user_record.profile = hydrate_profile(user_record.profile)
    else:
        user_record = UserRecord(email=user)

    current_user.set(user_record)
    mcp.run(transport="stdio")
