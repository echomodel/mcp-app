"""Static wiring checks — entry points, tool docstrings, return types."""

import inspect
import click

from mcp_app.testing.audit import public_tools


def test_mcp_cli_is_click_group(app):
    assert isinstance(app.mcp_cli, click.Group), (
        f"app.mcp_cli should be a click.Group, got {type(app.mcp_cli)}"
    )


def test_admin_cli_is_click_group(app):
    assert isinstance(app.admin_cli, click.Group), (
        f"app.admin_cli should be a click.Group, got {type(app.admin_cli)}"
    )


def test_mcp_cli_has_serve_and_stdio(app):
    commands = set(app.mcp_cli.commands.keys())
    assert "serve" in commands, "mcp_cli missing 'serve' command"
    assert "stdio" in commands, "mcp_cli missing 'stdio' command"


def test_admin_cli_has_connect_users_health(app):
    commands = set(app.admin_cli.commands.keys())
    assert "connect" in commands, "admin_cli missing 'connect' command"
    assert "users" in commands, "admin_cli missing 'users' command"
    assert "health" in commands, "admin_cli missing 'health' command"


def test_admin_cli_has_safe_tool_command(app):
    """Per #34, every mcp-app admin CLI exposes `safe-tool` (opt-in declaration)."""
    assert "safe-tool" in app.admin_cli.commands, (
        "admin_cli missing 'safe-tool' command"
    )


def test_admin_cli_has_tools_group(app):
    """Per #35, every mcp-app admin CLI exposes the `tools` subcommand group."""
    assert "tools" in app.admin_cli.commands, "admin_cli missing 'tools' group"
    tools_group = app.admin_cli.commands["tools"]
    sub = set(tools_group.commands.keys())
    assert {"list", "show", "call"}.issubset(sub), (
        f"tools group missing required subcommands; got {sub}"
    )


def test_tools_module_has_public_async_functions(app):
    tools = public_tools(app.tools_module)
    assert len(tools) > 0, (
        f"No public async functions found in {app.tools_module.__name__}"
    )


def test_every_tool_has_docstring(app):
    for tool in public_tools(app.tools_module):
        assert tool.__doc__, f"tool {tool.__name__} missing docstring"


def test_every_tool_has_return_type(app):
    for tool in public_tools(app.tools_module):
        sig = inspect.signature(tool)
        assert sig.return_annotation != inspect.Signature.empty, (
            f"tool {tool.__name__} missing return type annotation"
        )


def test_app_name_is_nonempty(app):
    assert app.name and len(app.name) > 0
