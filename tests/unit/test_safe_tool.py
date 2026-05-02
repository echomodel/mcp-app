"""Tests for #34 — safe-tool admin endpoint, RemoteAuthAdapter helper,
CLI command, and the structured envelope schema.
"""

import json
import os
from datetime import datetime, timezone

import httpx
import pytest
from click.testing import CliRunner
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mcp_app import App, SafeTool
from mcp_app.admin import create_admin_app, SAFE_TOOL_SCHEMA_VERSION
from mcp_app.admin_client import RemoteAuthAdapter
from mcp_app.bridge import DataStoreAuthAdapter
from mcp_app.data_store import FileSystemUserDataStore
from mcp_app.models import UserAuthRecord


SIGNING_KEY = "test-key-safe-tool-32chars-min!!"
BASE_URL = "http://test"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_USERS_PATH", str(tmp_path / "users"))
    monkeypatch.setenv("SIGNING_KEY", SIGNING_KEY)
    return FileSystemUserDataStore(app_name="test")


def _admin_only_app(store, safe_tool=None):
    auth_store = DataStoreAuthAdapter(store)
    admin_app = create_admin_app(auth_store, safe_tool=safe_tool)

    async def health(request):
        return JSONResponse({"status": "ok"})

    return Starlette(routes=[
        Route("/health", health),
        Mount("/admin", app=admin_app),
    ])


@pytest.fixture
def adapter_no_safe_tool(store):
    app = _admin_only_app(store)
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url=BASE_URL)
    return RemoteAuthAdapter(BASE_URL, SIGNING_KEY, http_client=http_client)


@pytest.fixture
def adapter_with_safe_tool(store):
    safe_tool = SafeTool(
        name="ping",
        arguments={},
        description="returns a static health response",
    )
    app = _admin_only_app(store, safe_tool=safe_tool)
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url=BASE_URL)
    return RemoteAuthAdapter(BASE_URL, SIGNING_KEY, http_client=http_client)


# --- Endpoint tests ---

@pytest.mark.asyncio
async def test_safe_tool_endpoint_unsupported_envelope(adapter_no_safe_tool):
    envelope = await adapter_no_safe_tool.get_safe_tool()
    assert envelope["schema_version"] == SAFE_TOOL_SCHEMA_VERSION
    assert envelope["supported"] is False
    assert "hint" in envelope
    assert "probe" in envelope["hint"].lower()


@pytest.mark.asyncio
async def test_safe_tool_endpoint_supported_envelope(adapter_with_safe_tool):
    envelope = await adapter_with_safe_tool.get_safe_tool()
    assert envelope["schema_version"] == SAFE_TOOL_SCHEMA_VERSION
    assert envelope["supported"] is True
    tool = envelope["tool"]
    assert tool["name"] == "ping"
    assert tool["description"] == "returns a static health response"
    assert tool["arguments"] == {}


@pytest.mark.asyncio
async def test_safe_tool_endpoint_requires_admin_auth(store):
    """Without a valid admin token the endpoint must return 403."""
    app = _admin_only_app(store, safe_tool=SafeTool("ping", {}, "x"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as http_client:
        resp = await http_client.get("/admin/safe-tool")
        assert resp.status_code == 403


# --- Full-stack tests (with MCP) ---

@pytest.fixture
def full_stack(tmp_path, monkeypatch):
    """Full ASGI app with MCP wired and a declared safe tool."""
    import importlib
    import sys
    fixture_path = os.path.join(os.path.dirname(__file__), "..", "fixture_app")
    sys.path.insert(0, os.path.abspath(fixture_path))
    try:
        tools = importlib.import_module("fixture_app.tools")
    finally:
        sys.path.pop(0)

    monkeypatch.setenv("SIGNING_KEY", SIGNING_KEY)
    monkeypatch.setenv("APP_USERS_PATH", str(tmp_path / "users"))

    app = App(
        name="test",
        tools_module=tools,
        safe_tool=SafeTool(name="ping", arguments={}, description="health"),
    )
    app._asgi = app._build_asgi()
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url=BASE_URL)
    adapter = RemoteAuthAdapter(BASE_URL, SIGNING_KEY, http_client=http_client)
    return adapter, app._mcp


@pytest.mark.asyncio
async def test_call_tool_round_trip_against_safe_tool(full_stack):
    adapter, mcp = full_stack
    await adapter.save(
        UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)),
    )
    async with mcp.session_manager.run():
        result = await adapter.call_tool("ping", {})

    assert result["probed_as"] == "alice@test.com"
    assert result["result"]["status_code"] == 200
    response_body = result["result"]["body"]
    assert "result" in response_body
    # Invocation envelope is replayable: complete URL, headers, body.
    inv = result["invocation"]
    assert inv["method"] == "POST"
    assert inv["url"].endswith("/")
    assert "Authorization" in inv["headers"]
    assert inv["body"]["method"] == "tools/call"
    assert inv["body"]["params"]["name"] == "ping"


# --- CLI tests ---

def _mock_envelope_adapter(envelope, call_result=None):
    """Test helper: a stand-in adapter that returns a known envelope."""

    class _Stub:
        async def get_safe_tool(self_):
            return envelope

        async def call_tool(self_, name, arguments, user_email=None):
            return call_result or {
                "probed_as": user_email or "alice@test.com",
                "invocation": {
                    "method": "POST",
                    "url": "http://test/",
                    "headers": {"Authorization": "Bearer xxx"},
                    "body": {"jsonrpc": "2.0", "method": "tools/call",
                             "params": {"name": name, "arguments": arguments}, "id": 2},
                },
                "result": {"status_code": 200, "body": {"jsonrpc": "2.0", "id": 2,
                                                         "result": {"content": []}}},
            }

    return _Stub()


def test_safe_tool_cli_unsupported_human(monkeypatch, tmp_path):
    """`safe-tool` against an instance with no declaration shows a clear hint."""
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(
        cli_mod, "_require_remote_adapter",
        lambda app_name: _mock_envelope_adapter({
            "schema_version": "1",
            "supported": False,
            "hint": "no safe tool — run probe",
        }),
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    admin_cli = cli_mod.create_admin_cli("myapp")
    runner = CliRunner()
    result = runner.invoke(admin_cli, ["safe-tool"])
    assert result.exit_code == 0, result.output
    assert "not declared" in result.output.lower()
    assert "run probe" in result.output


def test_safe_tool_cli_supported_json_envelope(monkeypatch, tmp_path):
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(
        cli_mod, "_require_remote_adapter",
        lambda app_name: _mock_envelope_adapter({
            "schema_version": "1",
            "supported": True,
            "tool": {"name": "count_items", "description": "x", "arguments": {}},
        }),
    )
    admin_cli = cli_mod.create_admin_cli("myapp")
    runner = CliRunner()
    result = runner.invoke(admin_cli, ["safe-tool", "--json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed["schema_version"] == "1"
    assert parsed["supported"] is True
    assert parsed["tool"]["name"] == "count_items"


def test_safe_tool_invoke_prints_request_before_response(monkeypatch, tmp_path):
    """Per #34: the JSON-RPC request body is printed before the response so
    operators can copy and replay it."""
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(
        cli_mod, "_require_remote_adapter",
        lambda app_name: _mock_envelope_adapter({
            "schema_version": "1",
            "supported": True,
            "tool": {"name": "count_items", "description": "x", "arguments": {}},
        }),
    )
    admin_cli = cli_mod.create_admin_cli("myapp")
    runner = CliRunner()
    result = runner.invoke(admin_cli, ["safe-tool", "--invoke"])
    assert result.exit_code == 0, result.output
    # Request lines (>) appear before response lines (<).
    out = result.output
    first_req = out.find("> POST")
    first_resp = out.find("< 200")
    assert first_req != -1, f"Missing request lines: {out}"
    assert first_resp != -1, f"Missing response lines: {out}"
    assert first_req < first_resp, "Request must be printed before response"


def test_safe_tool_invoke_unsupported_errors(monkeypatch, tmp_path):
    """`--invoke` on an undeclared deployment surfaces a clear error."""
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(
        cli_mod, "_require_remote_adapter",
        lambda app_name: _mock_envelope_adapter({
            "schema_version": "1",
            "supported": False,
            "hint": "not declared",
        }),
    )
    admin_cli = cli_mod.create_admin_cli("myapp")
    runner = CliRunner()
    result = runner.invoke(admin_cli, ["safe-tool", "--invoke"])
    assert result.exit_code != 0
    assert "no safe tool" in (result.output + (result.stderr or "")).lower()
