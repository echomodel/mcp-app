"""App — single composition root for mcp-app solutions.

An ``App`` is the whole mcp-app solution in one object: identity,
tool wiring, middleware, admin endpoints, data store. It is directly
ASGI-callable, so any ASGI host (uvicorn, hypercorn, granian, gunicorn,
Mangum for Lambda, httpx for in-process tests) treats it as the
server callable. The ``App`` also exposes ``stdio()`` and ``serve()``
methods for launching the two MCP transports directly.
"""

import asyncio
import contextlib
import functools
import importlib
import inspect
from dataclasses import dataclass
from functools import cached_property
from types import ModuleType

import click
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mcp_app.admin import create_admin_app
from mcp_app.bridge import DataStoreAuthAdapter
from mcp_app.data_store import FileSystemUserDataStore
from mcp_app.middleware import JWTMiddleware
from mcp_app.verifier import JWTVerifier


STORE_ALIASES = {"filesystem": FileSystemUserDataStore}
MIDDLEWARE_ALIASES = {"user-identity": JWTMiddleware}


@dataclass
class SafeTool:
    """Declaration of a tool the admin CLI can invoke for end-to-end smoke testing.

    The defining property of a safe tool is *low information density* about
    the user. A response that is identical for every user of the same product
    is ideal. A response that varies per user only along impersonal axes
    (counts, configuration enums, public reference data) is acceptable. A
    response containing content the user themselves authored is not.

    Patterns in priority order:
      1. Pure counts — ``{"count": 9}``. Safest by far.
      2. System enums / fixed taxonomies — labels the platform defines.
      3. Identifier-only listings — opaque IDs the user did not type.
      4. Mixed / partial — system-derived subset of an item, never user text.

    Anti-patterns: names, labels, subjects, descriptions the user wrote;
    "last N" framings; free-text fields; shape-leaks user configuration.

    If no existing tool fits, add a small dedicated tool exclusively for
    this purpose (``count_<entity>()``, ``health()``). That is an
    explicitly blessed pattern. Opting out (leaving ``safe_tool`` unset)
    is also fully fine — relying on ``probe`` is a supported configuration.

    Args:
        name: The tool name (must match a registered tool).
        arguments: Arguments dict to pass to ``tools/call``. Usually ``{}``.
        description: Short, app-provided, plain English description shown
            by the admin CLI. Intentionally separate from the MCP-side
            tool description (which is written for agents and may be more
            revealing than is appropriate for an admin smoke-test artifact).
    """

    name: str
    arguments: dict
    description: str


def _resolve_class(value: str, aliases: dict):
    if "." not in value:
        if value not in aliases:
            raise ValueError(
                f"Unknown alias '{value}'. Valid: {', '.join(sorted(aliases))}"
            )
        return aliases[value]
    module_path, class_name = value.rsplit(".", 1)
    return getattr(importlib.import_module(module_path), class_name)


def _discover_tools(module: ModuleType) -> list:
    return [
        obj for name, obj in inspect.getmembers(module, inspect.isfunction)
        if inspect.iscoroutinefunction(obj) and not name.startswith("_")
    ]


def _require_identity(func):
    """Wrap a tool so it refuses to execute without an authenticated user."""
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


@dataclass
class App:
    """An mcp-app solution.

    Args:
        name: App name (server name, store paths, CLI prefixes).
        tools_module: Python module containing async tool functions.
        sdk_package: The SDK package (for test tooling to find SDK
            tests). Optional — not needed for runtime.
        store_backend: Store alias or module path. Default: "filesystem".
        middleware: Custom middleware list. None = user-identity (default).
            Empty list = no auth.
        profile_model: Pydantic BaseModel for typed user profile.
            None = no profile (data-owning apps).
        profile_expand: If True, admin CLI generates individual flags
            from profile model fields. If False, accepts --profile
            as JSON or @file.
    """

    name: str
    tools_module: ModuleType
    sdk_package: ModuleType | None = None
    store_backend: str = "filesystem"
    middleware: list[str] | None = None
    profile_model: type | None = None
    profile_expand: bool = True
    safe_tool: SafeTool | None = None

    def __post_init__(self):
        self._asgi = None
        self._mcp = None
        if self.profile_model is not None:
            from mcp_app.context import register_profile
            register_profile(self.profile_model, expand=self.profile_expand)

    @cached_property
    def mcp_cli(self) -> click.Group:
        """Click group for MCP server commands (serve, stdio)."""
        from mcp_app.cli import create_mcp_cli
        return create_mcp_cli(self)

    @cached_property
    def admin_cli(self) -> click.Group:
        """Click group for admin commands (connect, users, tokens, health)."""
        from mcp_app.cli import create_admin_cli
        return create_admin_cli(self.name)

    def _build_store(self):
        cls = _resolve_class(self.store_backend, STORE_ALIASES)
        return cls(app_name=self.name)

    def _build_asgi(self):
        """Assemble the Starlette ASGI stack: health, admin, MCP + middleware."""
        import mcp_app

        store = self._build_store()
        mcp_app._store = store

        self._mcp = FastMCP(
            self.name,
            stateless_http=True,
            json_response=True,
            streamable_http_path="/",
        )
        self._mcp.settings.transport_security.enable_dns_rebinding_protection = False
        for func in _discover_tools(self.tools_module):
            self._mcp.tool()(_require_identity(func))

        auth_store = DataStoreAuthAdapter(store)
        verifier = JWTVerifier(auth_store)
        admin_app = create_admin_app(auth_store, safe_tool=self.safe_tool)
        inner = self._mcp.streamable_http_app()

        if self.middleware is None:
            wrapped = JWTMiddleware(inner, verifier)
        elif self.middleware == []:
            wrapped = inner
        else:
            wrapped = inner
            for mw_value in reversed(self.middleware):
                mw_cls = _resolve_class(mw_value, MIDDLEWARE_ALIASES)
                wrapped = mw_cls(wrapped, verifier, store)

        @contextlib.asynccontextmanager
        async def lifespan(_):
            async with self._mcp.session_manager.run():
                yield

        async def health(_):
            return JSONResponse({"status": "ok"})

        return Starlette(
            routes=[
                Route("/health", health),
                Mount("/admin", app=admin_app),
                Mount("/", app=wrapped),
            ],
            lifespan=lifespan,
        )

    async def __call__(self, scope, receive, send):
        """ASGI entry point.

        Lazy-builds and caches the ASGI stack on first call so ``App``
        can be constructed at module import time without env vars set.
        The underlying stack is the same whether the caller is uvicorn,
        httpx's ASGITransport, Mangum, or any other ASGI host.
        """
        if self._asgi is None:
            self._asgi = self._build_asgi()
        return await self._asgi(scope, receive, send)

    def stdio(self, user: str) -> None:
        """Run MCP over stdio for a single user."""
        import mcp_app
        from mcp_app.context import current_user, hydrate_profile
        from mcp_app.models import UserRecord

        store = self._build_store()
        mcp_app._store = store

        mcp = FastMCP(self.name)
        for func in _discover_tools(self.tools_module):
            mcp.tool()(_require_identity(func))

        adapter = DataStoreAuthAdapter(store)
        user_record = asyncio.run(adapter.get_full(user))
        if user_record:
            user_record.profile = hydrate_profile(user_record.profile)
        else:
            user_record = UserRecord(email=user)
        current_user.set(user_record)

        mcp.run(transport="stdio")

    def serve(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        """Run MCP over HTTP via uvicorn."""
        import uvicorn
        uvicorn.run(self, host=host, port=port)
