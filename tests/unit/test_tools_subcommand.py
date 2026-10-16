"""Tests for #35 — `tools list/show/call` admin subcommands.

Covers the full-stack round-trip via in-memory ASGI transport plus
CLI-level rendering and argument coercion.
"""

import json

import httpx
import pytest
from click.testing import CliRunner

from mcp_app import App
from mcp_app.admin_client import NotSignedInError, RemoteAuthAdapter

from .conftest import OPERATOR

BASE_URL = "http://test"


@pytest.fixture
def full_stack(auth_env, issuer):
    from fixture_app import tools

    app = App(name="test", tools_module=tools, auth=issuer.config)
    app._asgi = app._build_asgi()
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url=BASE_URL)
    adapter = RemoteAuthAdapter(BASE_URL, issuer.token(OPERATOR), http_client=http_client)
    return adapter, app._mcp, http_client


# --- Adapter-level tests (direct round-trip) ---

@pytest.mark.asyncio
async def test_list_tools_returns_full_dicts(full_stack):
    adapter, mcp, _ = full_stack
    async with mcp.session_manager.run():
        tools = await adapter.list_tools()

    names = {t["name"] for t in tools}
    assert {"ping", "greet"}.issubset(names)
    # Each tool dict carries a description and inputSchema (per MCP).
    for t in tools:
        assert "description" in t
        assert "inputSchema" in t


@pytest.mark.asyncio
async def test_call_tool_with_arguments_round_trip(full_stack):
    adapter, mcp, _ = full_stack
    async with mcp.session_manager.run():
        result = await adapter.call_tool("greet", {"name": "world"})

    assert result["result"]["status_code"] == 200
    body = result["result"]["body"]
    content = body["result"]["content"]
    assert any("world" in str(c) for c in content)
    # The operator acted as themselves.
    assert any(OPERATOR in str(c) for c in content)


@pytest.mark.asyncio
async def test_list_tools_without_token_raises_typed_exception(full_stack):
    """Adapter raises NotSignedInError specifically — not bare RuntimeError —
    so CLI helpers can catch it without swallowing other failures."""
    _, _, http_client = full_stack
    anonymous = RemoteAuthAdapter(BASE_URL, http_client=http_client)
    with pytest.raises(NotSignedInError) as exc_info:
        await anonymous.list_tools()
    assert "signed in" in str(exc_info.value)


@pytest.mark.asyncio
async def test_call_tool_without_token_raises_typed_exception(full_stack):
    _, _, http_client = full_stack
    anonymous = RemoteAuthAdapter(BASE_URL, http_client=http_client)
    with pytest.raises(NotSignedInError):
        await anonymous.call_tool("ping", {})


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

    async def list_tools(self):
        return self._tools

    async def call_tool(self, name, arguments):
        return self._call_response or {
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

    async def aclose(self):
        pass


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


# --- CLI-level tests for a connection with no sign-in ---

class _NotSignedInAdapter:
    """Stub mirroring an adapter that holds no administrator token."""

    async def list_tools(self):
        raise NotSignedInError()

    async def call_tool(self, name, arguments):
        raise NotSignedInError()

    async def get_safe_tool(self):
        raise NotSignedInError()

    async def aclose(self):
        pass


def _not_signed_in_stub():
    adapter = _NotSignedInAdapter()
    return lambda app_name: adapter


def _assert_clean_sign_in_error(result):
    out = result.output + (result.stderr or "")
    assert result.exit_code != 0
    assert "Traceback" not in out, f"Stack trace leaked to operator output:\n{out}"
    assert "signed in as an administrator" in out
    assert "connect local" in out


def test_tools_list_not_signed_in_clean_error(monkeypatch):
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_remote_adapter", _not_signed_in_stub())
    result = CliRunner().invoke(cli_mod.create_admin_cli("myapp"), ["tools", "list"])
    _assert_clean_sign_in_error(result)


def test_tools_show_not_signed_in_clean_error(monkeypatch):
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_remote_adapter", _not_signed_in_stub())
    result = CliRunner().invoke(cli_mod.create_admin_cli("myapp"), ["tools", "show", "ping"])
    _assert_clean_sign_in_error(result)


def test_tools_call_not_signed_in_clean_error_with_args(monkeypatch):
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_remote_adapter", _not_signed_in_stub())
    result = CliRunner().invoke(cli_mod.create_admin_cli("myapp"), ["tools", "call", "ping", "--arg", "k=v"])
    _assert_clean_sign_in_error(result)


def test_tools_call_not_signed_in_clean_error_with_body(monkeypatch):
    """The --body path skips the schema lookup and goes straight to call_tool."""
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_remote_adapter", _not_signed_in_stub())
    result = CliRunner().invoke(cli_mod.create_admin_cli("myapp"), ["tools", "call", "ping", "--body", "{}"])
    _assert_clean_sign_in_error(result)


def test_safe_tool_not_signed_in_clean_error(monkeypatch):
    from mcp_app import cli as cli_mod
    monkeypatch.setattr(cli_mod, "_require_remote_adapter", _not_signed_in_stub())
    result = CliRunner().invoke(cli_mod.create_admin_cli("myapp"), ["safe-tool", "--invoke"])
    _assert_clean_sign_in_error(result)
