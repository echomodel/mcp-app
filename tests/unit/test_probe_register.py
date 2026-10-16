"""Tests for probe and register commands.

Probe: verifies the OAuth front door through the full in-memory ASGI
stack without any sign-in.

Register: exercises command generation (pure logic, no network).
"""

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp_app import App
from mcp_app.admin_client import RemoteAuthAdapter
from mcp_app.registration import format_registrations, generate_registrations

BASE_URL = "http://test"


@pytest.fixture
def full_stack(auth_env, issuer):
    """Full ASGI app with MCP tools; the session manager is started per test."""
    from fixture_app import tools

    app = App(name="test", tools_module=tools, auth=issuer.config)
    app._asgi = app._build_asgi()
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url=BASE_URL)
    return RemoteAuthAdapter(BASE_URL, http_client=http_client), app._mcp


@pytest.fixture
def health_only():
    """A server with health but no OAuth front door at all."""

    async def health(request):
        return JSONResponse({"status": "ok"})

    app = Starlette(routes=[Route("/health", health)])
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url=BASE_URL)
    return RemoteAuthAdapter(BASE_URL, http_client=http_client)


# --- Probe tests ---

@pytest.mark.asyncio
async def test_probe_verifies_oauth_front_door_without_sign_in(full_stack, issuer):
    adapter, mcp = full_stack
    async with mcp.session_manager.run():
        result = await adapter.probe()
    assert result["health"]["status"] == "healthy"
    assert result["oauth"]["status"] == "ok"
    assert result["oauth"]["issuer"] == issuer.issuer
    assert result["oauth"]["resource"] == "http://test/"
    assert "resource_metadata=" in result["oauth"]["challenge"]


@pytest.mark.asyncio
async def test_probe_reports_missing_front_door(health_only):
    result = await health_only.probe()
    assert result["health"]["status"] == "healthy"
    assert result["oauth"]["status"] == "error"
    assert result["oauth"]["error"]


@pytest.mark.asyncio
async def test_probe_unreachable():
    def refuse(request):
        raise httpx.ConnectError("refused")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(refuse), base_url=BASE_URL)
    result = await RemoteAuthAdapter(BASE_URL, http_client=http_client).probe()
    assert result["health"]["status"] == "unreachable"
    assert result["oauth"] is None


# --- Registration tests ---

class TestGenerateRegistrations:

    def test_default_all_clients_all_scopes(self):
        reg = generate_registrations(name="my-app", url="https://my-app.example.com/")
        assert reg["url"] == "https://my-app.example.com/"
        assert reg["name"] == "my-app"
        entries = reg["entries"]
        clients_scopes = [(e["client"], e["scope"]) for e in entries]
        assert ("claude", "user") in clients_scopes
        assert ("claude", "project") in clients_scopes
        assert ("agy", None) in clients_scopes
        assert ("claude.ai", None) in clients_scopes
        for e in entries:
            assert "Bearer" not in e["command"], "no credential belongs in a registration command"
            assert "token" not in e["command"]

    def test_url_gets_trailing_slash(self):
        reg = generate_registrations(name="x", url="https://my-app.example.com")
        assert reg["url"].endswith("/")
        for e in reg["entries"]:
            assert "https://my-app.example.com/" in e["command"]

    def test_filter_client(self):
        reg = generate_registrations(name="x", url="https://a.com/", clients=["claude"])
        clients = {e["client"] for e in reg["entries"]}
        assert clients == {"claude"}

    def test_filter_scope(self):
        reg = generate_registrations(name="x", url="https://a.com/", scopes=["user"])
        for e in reg["entries"]:
            if e["client"] == "claude":
                assert e["scope"] == "user"

    def test_claude_ai_is_just_the_url(self):
        reg = generate_registrations(name="x", url="https://a.com/", clients=["claude.ai"])
        [entry] = reg["entries"]
        assert entry["command"] == "https://a.com/"

    def test_claude_code_command(self):
        reg = generate_registrations(name="my-app", url="https://a.com/", clients=["claude"], scopes=["user"])
        [entry] = reg["entries"]
        assert entry["command"] == "claude mcp add --transport http -s user my-app https://a.com/"


class TestAgyRegistration:

    def test_agy_command_puts_name_then_url(self):
        reg = generate_registrations(name="my-app", url="https://a.com/", clients=["agy"])
        [entry] = reg["entries"]
        assert entry["scope"] is None
        assert entry["command"] == "agy mcp add my-app https://a.com/"

    def test_agy_ignores_scope_filter(self):
        reg = generate_registrations(name="x", url="https://a.com/", clients=["agy"], scopes=["project"])
        assert [e["scope"] for e in reg["entries"]] == [None]

    def test_agy_text_label(self):
        text = format_registrations(generate_registrations(name="x", url="https://a.com/", clients=["agy"]))
        assert "agy (user config, status unknown):" in text


class TestFormatRegistrations:

    def test_output_contains_all_entries(self):
        reg = generate_registrations(name="x", url="https://a.com/")
        text = format_registrations(reg)
        assert "claude" in text
        assert "agy" in text
        assert "claude.ai" in text
        assert "signs the user in" in text

    def test_output_shows_manual_for_claude_ai(self):
        reg = generate_registrations(name="x", url="https://a.com/", clients=["claude.ai"])
        text = format_registrations(reg)
        assert "manual" in text
