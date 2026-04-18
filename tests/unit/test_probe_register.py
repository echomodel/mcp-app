"""Tests for probe and register commands.

Probe: exercises /health + MCP tools/list round-trip through the full
in-memory ASGI stack.

Register: exercises command generation (pure logic, no network).
"""

import os
import json
import pytest
import httpx
from datetime import datetime, timezone
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mcp_app.admin import create_admin_app
from mcp_app.admin_client import RemoteAuthAdapter
from mcp_app.bridge import DataStoreAuthAdapter
from mcp_app.data_store import FileSystemUserDataStore
from mcp_app.models import UserAuthRecord
from mcp_app.registration import (
    generate_registrations,
    format_registrations,
    TOKEN_PLACEHOLDER,
)


SIGNING_KEY = "test-key-probe-register-32char!"
BASE_URL = "http://test"


# --- Fixtures ---

@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_USERS_PATH", str(tmp_path / "users"))
    monkeypatch.setenv("SIGNING_KEY", SIGNING_KEY)
    return FileSystemUserDataStore(app_name="test")


@pytest.fixture
def _mcp_app_components(store, monkeypatch):
    """Build full ASGI app with MCP tools but don't start session manager."""
    import importlib
    import sys
    fixture_path = os.path.join(os.path.dirname(__file__), "..", "fixture_app")
    sys.path.insert(0, os.path.abspath(fixture_path))
    try:
        tools = importlib.import_module("fixture_app.tools")
    finally:
        sys.path.pop(0)

    from mcp_app import App
    monkeypatch.setenv("SIGNING_KEY", SIGNING_KEY)
    app = App(name="test", tools_module=tools)
    app._asgi = app._build_asgi()
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url=BASE_URL)
    adapter = RemoteAuthAdapter(BASE_URL, SIGNING_KEY, http_client=http_client)
    return adapter, app._mcp


@pytest.fixture
def adapter_health_only(store):
    """Adapter backed by health + admin only — no MCP mount."""
    auth_store = DataStoreAuthAdapter(store)
    admin_app = create_admin_app(auth_store)

    async def health(request):
        return JSONResponse({"status": "ok"})

    app = Starlette(routes=[
        Route("/health", health),
        Mount("/admin", app=admin_app),
    ])
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url=BASE_URL)
    return RemoteAuthAdapter(BASE_URL, SIGNING_KEY, http_client=http_client)


# --- Probe tests ---

@pytest.mark.asyncio
async def test_probe_health_only_no_users(adapter_health_only):
    result = await adapter_health_only.probe()
    assert result["health"]["status"] == "healthy"
    assert result["mcp"]["status"] == "skipped"
    assert "no registered users" in result["mcp"]["reason"]
    assert result["tools"] is None


@pytest.mark.asyncio
async def test_probe_health_only_with_user(adapter_health_only):
    await adapter_health_only.save(
        UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)),
    )
    result = await adapter_health_only.probe()
    assert result["health"]["status"] == "healthy"
    assert result["mcp"]["probed_as"] == "alice@test.com"


@pytest.mark.asyncio
async def test_probe_explicit_user(adapter_health_only):
    await adapter_health_only.save(
        UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)),
    )
    await adapter_health_only.save(
        UserAuthRecord(email="bob@test.com", created=datetime.now(timezone.utc)),
    )
    result = await adapter_health_only.probe(user_email="bob@test.com")
    assert result["mcp"]["probed_as"] == "bob@test.com"


@pytest.mark.asyncio
async def test_probe_full_stack_lists_tools(_mcp_app_components):
    adapter, mcp = _mcp_app_components
    await adapter.save(
        UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)),
    )
    async with mcp.session_manager.run():
        result = await adapter.probe()
    assert result["health"]["status"] == "healthy"
    assert result["mcp"]["status"] == "ok"
    assert isinstance(result["tools"], list)
    assert len(result["tools"]) > 0


# --- Registration tests ---

class TestGenerateRegistrations:

    def test_default_all_clients_all_scopes(self):
        reg = generate_registrations(name="my-app", url="https://my-app.example.com/")
        assert reg["url"] == "https://my-app.example.com/"
        assert reg["name"] == "my-app"
        assert reg["token_provided"] is False
        entries = reg["entries"]
        clients_scopes = [(e["client"], e["scope"]) for e in entries]
        assert ("claude", "user") in clients_scopes
        assert ("claude", "project") in clients_scopes
        assert ("gemini", "user") in clients_scopes
        assert ("gemini", "project") in clients_scopes
        assert ("claude.ai", None) in clients_scopes
        for e in entries:
            if e["client"] != "claude.ai":
                assert TOKEN_PLACEHOLDER in e["command"]

    def test_url_gets_trailing_slash(self):
        reg = generate_registrations(name="x", url="https://my-app.example.com")
        assert reg["url"].endswith("/")
        for e in reg["entries"]:
            assert "https://my-app.example.com/" in e["command"]

    def test_with_token(self):
        reg = generate_registrations(name="x", url="https://a.com/", token="tok123")
        assert reg["token_provided"] is True
        for e in reg["entries"]:
            assert "tok123" in e["command"]

    def test_filter_client(self):
        reg = generate_registrations(name="x", url="https://a.com/", clients=["claude"])
        clients = {e["client"] for e in reg["entries"]}
        assert clients == {"claude"}

    def test_filter_scope(self):
        reg = generate_registrations(name="x", url="https://a.com/", scopes=["user"])
        for e in reg["entries"]:
            if e["client"] != "claude.ai":
                assert e["scope"] == "user"

    def test_claude_ai_has_token_in_url(self):
        reg = generate_registrations(name="x", url="https://a.com/", token="t")
        ai = [e for e in reg["entries"] if e["client"] == "claude.ai"]
        assert len(ai) == 1
        assert "token=t" in ai[0]["command"]


class TestFormatRegistrations:

    def test_output_contains_all_entries(self):
        reg = generate_registrations(name="x", url="https://a.com/")
        text = format_registrations(reg)
        assert "claude" in text
        assert "gemini" in text
        assert "claude.ai" in text

    def test_output_shows_manual_for_claude_ai(self):
        reg = generate_registrations(name="x", url="https://a.com/", clients=["claude.ai"])
        text = format_registrations(reg)
        assert "manual" in text
