"""Transport-scoped tools: `@mcp_transport` keeps a tool off a transport.

A tool that reads a caller-named host path is safe over stdio (runs as the
local user) but an arbitrary-server-file read over HTTP. `@mcp_transport`
lets the author declare which transports a tool is registered on, so the
dangerous tool is simply never advertised on the HTTP surface.

Tests run the real discovery/registration code against a synthetic tools
module — no mocks.
"""

import types

import pytest

import mcp_app
from mcp_app import mcp_transport
from mcp_app.app import App, VALID_TRANSPORTS, _discover_tools, _tool_transports


def _tools_module() -> types.ModuleType:
    """A synthetic tools module with one tool per transport posture."""
    mod = types.ModuleType("synthetic_tools")

    async def tool_all() -> dict:
        return {"ok": True}

    @mcp_transport("stdio")
    async def tool_stdio_only(path: str) -> dict:
        return {"path": path}

    @mcp_transport("http")
    async def tool_http_only() -> dict:
        return {"ok": True}

    for fn in (tool_all, tool_stdio_only, tool_http_only):
        setattr(mod, fn.__name__, fn)
    return mod


# --- the annotation ---

def test_unannotated_tool_allows_all_transports():
    mod = _tools_module()
    assert _tool_transports(mod.tool_all) == VALID_TRANSPORTS


def test_mcp_transport_records_the_restriction():
    mod = _tools_module()
    assert _tool_transports(mod.tool_stdio_only) == frozenset({"stdio"})
    assert _tool_transports(mod.tool_http_only) == frozenset({"http"})


def test_mcp_transport_rejects_unknown_transport():
    with pytest.raises(ValueError, match="expects one or more"):
        mcp_transport("ftp")


def test_mcp_transport_rejects_empty():
    with pytest.raises(ValueError, match="expects one or more"):
        mcp_transport()


# --- discovery filtering (what the registration loops use) ---

def test_no_filter_returns_every_tool():
    names = {f.__name__ for f in _discover_tools([_tools_module()])}
    assert names == {"tool_all", "tool_stdio_only", "tool_http_only"}


def test_http_discovery_skips_stdio_only_tool():
    names = {f.__name__ for f in _discover_tools([_tools_module()], "http")}
    assert "tool_stdio_only" not in names
    assert names == {"tool_all", "tool_http_only"}


def test_stdio_discovery_skips_http_only_tool():
    names = {f.__name__ for f in _discover_tools([_tools_module()], "stdio")}
    assert "tool_http_only" not in names
    assert names == {"tool_all", "tool_stdio_only"}


# --- end-to-end: the HTTP server never advertises a stdio-only tool ---

@pytest.mark.asyncio
async def test_http_app_does_not_register_stdio_only_tool(monkeypatch, tmp_path):
    monkeypatch.setenv("SIGNING_KEY", "test-signing-key")
    monkeypatch.setenv("APP_USERS_PATH", str(tmp_path / "users"))
    app = App(name="test", tools_module=_tools_module())
    app._asgi = app._build_asgi()

    names = {t.name for t in await app._mcp.list_tools()}
    assert "tool_stdio_only" not in names, "stdio-only tool must not be on the HTTP surface"
    assert {"tool_all", "tool_http_only"} <= names
    # building the HTTP stack records the transport fact
    assert mcp_app._transport == "http"


# --- the transport fact (report-the-fact half), fail-closed ---

def test_is_stdio_is_fail_closed(monkeypatch):
    monkeypatch.setattr(mcp_app, "_transport", None)
    assert mcp_app.is_stdio() is False
    assert mcp_app.get_transport() is None

    monkeypatch.setattr(mcp_app, "_transport", "http")
    assert mcp_app.is_stdio() is False
    assert mcp_app.get_transport() == "http"

    monkeypatch.setattr(mcp_app, "_transport", "stdio")
    assert mcp_app.is_stdio() is True
    assert mcp_app.get_transport() == "stdio"
