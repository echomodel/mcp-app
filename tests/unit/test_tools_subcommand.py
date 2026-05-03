"""Tests for #35 — `tools list/show/call` admin subcommands.

Covers the full-stack round-trip via in-memory ASGI transport plus
CLI-level rendering and argument coercion.
"""

import json
import os
from datetime import datetime, timezone

import httpx
import pytest
from click.testing import CliRunner

from mcp_app import App
from mcp_app.admin_client import RemoteAuthAdapter
from mcp_app.models import UserAuthRecord


SIGNING_KEY = "test-key-tools-subcommand-32chr!"
BASE_URL = "http://test"


@pytest.fixture
def full_stack(tmp_path, monkeypatch):
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

    app = App(name="test", tools_module=tools)
    app._asgi = app._build_asgi()
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url=BASE_URL)
    adapter = RemoteAuthAdapter(BASE_URL, SIGNING_KEY, http_client=http_client)
    return adapter, app._mcp


# --- Adapter-level tests (direct round-trip) ---

@pytest.mark.asyncio
async def test_list_tools_returns_full_dicts(full_stack):
    adapter, mcp = full_stack
    await adapter.save(
        UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)),
    )
    async with mcp.session_manager.run():
        tools, probed_as = await adapter.list_tools()

    assert probed_as == "alice@test.com"
    names = {t["name"] for t in tools}
    assert {"ping", "greet"}.issubset(names)
    # Each tool dict carries a description and inputSchema (per MCP).
    for t in tools:
        assert "description" in t
        assert "inputSchema" in t


@pytest.mark.asyncio
async def test_call_tool_with_arguments_round_trip(full_stack):
    adapter, mcp = full_stack
    await adapter.save(
        UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)),
    )
    async with mcp.session_manager.run():
        result = await adapter.call_tool("greet", {"name": "world"})

    assert result["result"]["status_code"] == 200
    body = result["result"]["body"]
    content = body["result"]["content"]
    assert any("world" in str(c) for c in content)


@pytest.mark.asyncio
async def test_list_tools_no_users_raises_typed_exception(full_stack):
    """Adapter raises NoProbeUserError specifically — not bare RuntimeError —
    so CLI helpers can catch it without swallowing other failures."""
    from mcp_app.admin_client import NoProbeUserError
    adapter, _ = full_stack
    with pytest.raises(NoProbeUserError) as exc_info:
        await adapter.list_tools()
    # The message must point the operator at the corrective action.
    assert "users add" in str(exc_info.value)


@pytest.mark.asyncio
async def test_call_tool_no_users_raises_typed_exception(full_stack):
    from mcp_app.admin_client import NoProbeUserError
    adapter, _ = full_stack
    with pytest.raises(NoProbeUserError) as exc_info:
        await adapter.call_tool("ping", {})
    assert "users add" in str(exc_info.value)


# --- Argument coercion tests ---

def test_coerce_arg_value_boolean():
    from mcp_app.cli import _coerce_arg_value
    assert _coerce_arg_value("true", {"type": "boolean"}) is True
    assert _coerce_arg_value("false", {"type": "boolean"}) is False


def test_coerce_arg_value_integer():
    from mcp_app.cli import _coerce_arg_value
    assert _coerce_arg_value("42", {"type": "integer"}) == 42


def test_coerce_arg_value_string_passthrough():
    from mcp_app.cli import _coerce_arg_value
    assert _coerce_arg_value("hello", {"type": "string"}) == "hello"


def test_coerce_arg_value_object_type_rejects():
    """--arg cannot pass objects — operator must use --body and gets a clear hint."""
    import click
    from mcp_app.cli import _coerce_arg_value
    with pytest.raises(click.ClickException) as excinfo:
        _coerce_arg_value("{}", {"type": "object"})
    assert "--body" in str(excinfo.value.message)


def test_parse_args_pairs_uses_schema():
    from mcp_app.cli import _parse_args_pairs
    schema = {"properties": {"flag": {"type": "boolean"}, "n": {"type": "integer"}}}
    out = _parse_args_pairs(("flag=true", "n=7"), schema)
    assert out == {"flag": True, "n": 7}


# --- CLI-level tests with a stub adapter ---

class _StubAdapter:
    def __init__(self, tools=None, call_response=None):
        self._tools = tools or []
        self._call_response = call_response

    async def list_tools(self, user_email=None):
        return self._tools, user_email or "alice@test.com"

    async def call_tool(self, name, arguments, user_email=None):
        return self._call_response or {
            "probed_as": user_email or "alice@test.com",
            "invocation": {
                "method": "POST",
                "url": "http://test/",
                "headers": {"Authorization": "Bearer xxx"},
                "body": {"jsonrpc": "2.0", "method": "tools/call",
                         "params": {"name": name, "arguments": arguments}, "id": 2},
            },
            "result": {"status_code": 200, "body": {"jsonrpc": "2.0", "id": 2,
                                                     "result": {"content": [{"type": "text", "text": "ok"}]}}},
        }


def _stub(tools=None, call_response=None):
    adapter = _StubAdapter(tools=tools, call_response=call_response)
    return lambda app_name: adapter


def test_tools_list_human_readable(monkeypatch):
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_remote_adapter", _stub(tools=[
        {"name": "ping", "description": "Health check.", "inputSchema": {}},
        {"name": "greet", "description": "Greet someone.", "inputSchema": {
            "type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]
        }},
    ]))
    admin_cli = cli_mod.create_admin_cli("myapp")
    runner = CliRunner()
    result = runner.invoke(admin_cli, ["tools", "list"])
    assert result.exit_code == 0, result.output
    assert "ping" in result.output
    assert "greet" in result.output
    assert "Health check." in result.output
    assert "(2 tools" in result.output


def test_tools_list_json(monkeypatch):
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_remote_adapter", _stub(tools=[
        {"name": "ping", "description": "x", "inputSchema": {}},
    ]))
    admin_cli = cli_mod.create_admin_cli("myapp")
    runner = CliRunner()
    result = runner.invoke(admin_cli, ["tools", "list", "--json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed["tools"][0]["name"] == "ping"
    assert parsed["probed_as"]


def test_tools_show_renders_schema_and_example(monkeypatch):
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_remote_adapter", _stub(tools=[
        {"name": "update_item",
         "description": "Update an item's fields.",
         "inputSchema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "Item ID"},
                "title": {"type": "string", "description": "New title"},
            },
            "required": ["item_id"],
         }},
    ]))
    admin_cli = cli_mod.create_admin_cli("myapp")
    runner = CliRunner()
    result = runner.invoke(admin_cli, ["tools", "show", "update_item"])
    assert result.exit_code == 0, result.output
    assert "update_item" in result.output
    assert "item_id" in result.output
    assert "required" in result.output
    assert "optional" in result.output
    # Example invocation block
    assert "tools call update_item" in result.output


def test_tools_show_unknown_tool_errors(monkeypatch):
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_remote_adapter", _stub(tools=[
        {"name": "ping", "description": "x", "inputSchema": {}},
    ]))
    admin_cli = cli_mod.create_admin_cli("myapp")
    runner = CliRunner()
    result = runner.invoke(admin_cli, ["tools", "show", "no_such_tool"])
    assert result.exit_code != 0
    msg = (result.output + (result.stderr or "")).lower()
    assert "unknown tool" in msg
    assert "tools list" in msg


def test_tools_call_with_args_prints_request_before_response(monkeypatch):
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_remote_adapter", _stub(tools=[
        {"name": "greet", "description": "Greet.",
         "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}},
                         "required": ["name"]}},
    ]))
    admin_cli = cli_mod.create_admin_cli("myapp")
    runner = CliRunner()
    result = runner.invoke(admin_cli, ["tools", "call", "greet", "--arg", "name=world"])
    assert result.exit_code == 0, result.output
    out = result.output
    first_req = out.find("> POST")
    first_resp = out.find("< 200")
    assert first_req != -1
    assert first_resp != -1
    assert first_req < first_resp


def test_tools_call_malformed_arg_errors(monkeypatch):
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_remote_adapter", _stub(tools=[
        {"name": "greet", "description": "x", "inputSchema": {}},
    ]))
    admin_cli = cli_mod.create_admin_cli("myapp")
    runner = CliRunner()
    result = runner.invoke(admin_cli, ["tools", "call", "greet", "--arg", "noequalsign"])
    assert result.exit_code != 0
    msg = (result.output + (result.stderr or "")).lower()
    assert "key=value" in msg


def test_tools_call_with_body_json(monkeypatch):
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_remote_adapter", _stub(tools=[
        {"name": "complex", "description": "x", "inputSchema": {}},
    ]))
    admin_cli = cli_mod.create_admin_cli("myapp")
    runner = CliRunner()
    result = runner.invoke(admin_cli, ["tools", "call", "complex",
                                       "--body", '{"a": 1, "b": [1,2,3]}'])
    assert result.exit_code == 0, result.output
    # The arguments dict round-trips into the printed request body.
    assert '"a": 1' in result.output
    assert '"b"' in result.output


def test_tools_call_unknown_tool_errors_when_using_args(monkeypatch):
    """When using --arg (not --body), we resolve the schema, so unknown tool fails."""
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_remote_adapter", _stub(tools=[
        {"name": "ping", "description": "x", "inputSchema": {}},
    ]))
    admin_cli = cli_mod.create_admin_cli("myapp")
    runner = CliRunner()
    result = runner.invoke(admin_cli, ["tools", "call", "no_such_tool", "--arg", "k=v"])
    assert result.exit_code != 0
    msg = (result.output + (result.stderr or "")).lower()
    assert "unknown tool" in msg


# --- CLI-level tests for the empty-deployment (no users) state ---

class _NoUsersAdapter:
    """Stub that mimics what every adapter method does when the
    deployment has no registered users to mint a probe token for."""

    async def list_tools(self, user_email=None):
        from mcp_app.admin_client import NoProbeUserError
        raise NoProbeUserError(
            "No registered users on this deployment — cannot mint a "
            "probe token. Register one first with `users add <email>`."
        )

    async def call_tool(self, name, arguments, user_email=None):
        from mcp_app.admin_client import NoProbeUserError
        raise NoProbeUserError(
            "No registered users on this deployment — cannot mint a "
            "token to invoke a tool. Register one first with "
            "`users add <email>`."
        )

    async def get_safe_tool(self):
        # safe-tool metadata fetch always succeeds — only the --invoke
        # path needs a probe user. Mirror admin.py's "supported" envelope.
        return {
            "schema_version": "1",
            "supported": True,
            "tool": {"name": "ping", "description": "ok", "arguments": {}},
        }


def _no_users_stub():
    adapter = _NoUsersAdapter()
    return lambda app_name: adapter


def _assert_no_stack_trace(output: str):
    # Click formats ClickException as "Error: <message>". A bubbled
    # RuntimeError would surface as a Python traceback containing
    # 'Traceback (most recent call last):'. We must never see the latter.
    assert "Traceback" not in output, (
        f"Stack trace leaked to operator output:\n{output}"
    )


def test_tools_list_no_users_clean_error(monkeypatch):
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_remote_adapter", _no_users_stub())
    admin_cli = cli_mod.create_admin_cli("myapp")
    runner = CliRunner()
    result = runner.invoke(admin_cli, ["tools", "list"])
    assert result.exit_code != 0
    out = result.output + (result.stderr or "")
    _assert_no_stack_trace(out)
    assert "users add" in out


def test_tools_show_no_users_clean_error(monkeypatch):
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_remote_adapter", _no_users_stub())
    admin_cli = cli_mod.create_admin_cli("myapp")
    runner = CliRunner()
    result = runner.invoke(admin_cli, ["tools", "show", "ping"])
    assert result.exit_code != 0
    out = result.output + (result.stderr or "")
    _assert_no_stack_trace(out)
    assert "users add" in out


def test_tools_call_no_users_clean_error_with_args(monkeypatch):
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_remote_adapter", _no_users_stub())
    admin_cli = cli_mod.create_admin_cli("myapp")
    runner = CliRunner()
    result = runner.invoke(admin_cli, ["tools", "call", "ping", "--arg", "k=v"])
    assert result.exit_code != 0
    out = result.output + (result.stderr or "")
    _assert_no_stack_trace(out)
    assert "users add" in out


def test_tools_call_no_users_clean_error_with_body(monkeypatch):
    """The --body path skips the schema lookup and goes straight to
    call_tool. The no-users error must still surface cleanly."""
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_remote_adapter", _no_users_stub())
    admin_cli = cli_mod.create_admin_cli("myapp")
    runner = CliRunner()
    result = runner.invoke(admin_cli, ["tools", "call", "ping", "--body", "{}"])
    assert result.exit_code != 0
    out = result.output + (result.stderr or "")
    _assert_no_stack_trace(out)
    assert "users add" in out


def test_safe_tool_invoke_no_users_clean_error(monkeypatch):
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_remote_adapter", _no_users_stub())
    admin_cli = cli_mod.create_admin_cli("myapp")
    runner = CliRunner()
    result = runner.invoke(admin_cli, ["safe-tool", "--invoke"])
    assert result.exit_code != 0
    out = result.output + (result.stderr or "")
    _assert_no_stack_trace(out)
    assert "users add" in out
