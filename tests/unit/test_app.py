"""Tests for App composition root."""

import os
import sys
import pytest
import click
from pathlib import Path
from types import ModuleType

from mcp_app.app import App


@pytest.fixture
def tools_module(tmp_path):
    """Create a minimal tools module."""
    mod_dir = tmp_path / "test_app_tools"
    mod_dir.mkdir()
    (mod_dir / "__init__.py").write_text("")
    (mod_dir / "tools.py").write_text(
        "async def greet(name: str) -> dict:\n"
        "    \"\"\"Say hello.\"\"\"\n"
        "    return {'message': f'hello {name}'}\n\n"
        "async def ping() -> dict:\n"
        "    \"\"\"Health check.\"\"\"\n"
        "    return {'pong': True}\n"
    )
    sys.path.insert(0, str(tmp_path))
    import importlib
    mod = importlib.import_module("test_app_tools.tools")
    yield mod
    sys.path.remove(str(tmp_path))


def test_app_construction(tools_module):
    app = App(name="test-app", tools_module=tools_module)
    assert app.name == "test-app"
    assert app.tools_module is tools_module
    assert app.store_backend == "filesystem"
    assert app.middleware is None
    assert app.profile_model is None


def test_mcp_cli_is_click_group(tools_module):
    app = App(name="test-app", tools_module=tools_module)
    assert isinstance(app.mcp_cli, click.Group)


def test_admin_cli_is_click_group(tools_module):
    app = App(name="test-app", tools_module=tools_module)
    assert isinstance(app.admin_cli, click.Group)


def test_mcp_cli_cached_identity(tools_module):
    """Same object on repeated access."""
    app = App(name="test-app", tools_module=tools_module)
    cli1 = app.mcp_cli
    cli2 = app.mcp_cli
    assert cli1 is cli2


def test_admin_cli_cached_identity(tools_module):
    app = App(name="test-app", tools_module=tools_module)
    cli1 = app.admin_cli
    cli2 = app.admin_cli
    assert cli1 is cli2


def test_mcp_cli_has_serve_and_stdio(tools_module):
    app = App(name="test-app", tools_module=tools_module)
    commands = list(app.mcp_cli.commands.keys())
    assert "serve" in commands
    assert "stdio" in commands


def test_admin_cli_has_connect_users_health(tools_module):
    app = App(name="test-app", tools_module=tools_module)
    commands = list(app.admin_cli.commands.keys())
    assert "connect" in commands
    assert "users" in commands
    assert "health" in commands


def test_profile_model_registers_on_construction(tools_module):
    from pydantic import BaseModel
    import mcp_app.context as ctx

    class TestProfile(BaseModel):
        token: str

    old_model = ctx._profile_model
    try:
        app = App(
            name="test-app",
            tools_module=tools_module,
            profile_model=TestProfile,
        )
        assert ctx.get_profile_model() is TestProfile
    finally:
        ctx._profile_model = old_model


def test_app_without_profile(tools_module):
    app = App(name="test-app", tools_module=tools_module)
    assert app.profile_model is None


def test_app_construction_without_env_vars(tools_module):
    """App constructs at import time; env vars only needed on first ASGI call."""
    for var in ("SIGNING_KEY", "APP_USERS_PATH"):
        os.environ.pop(var, None)
    app = App(name="test-app", tools_module=tools_module)
    assert app.name == "test-app"
    assert app._asgi is None


def test_app_is_asgi_callable_via_httpx(tools_module, tmp_path):
    """App instance is the ASGI callable — works with httpx.ASGITransport,
    uvicorn, or any ASGI host without any wrapping."""
    import asyncio
    import httpx

    os.environ["APP_USERS_PATH"] = str(tmp_path / "users")
    os.environ["SIGNING_KEY"] = "test-key-32chars-minimum-length!!"
    try:
        app = App(name="test-app", tools_module=tools_module)

        async def run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                r1 = await client.get("/health")
                r2 = await client.get("/health")
                return r1, r2

        r1, r2 = asyncio.run(run())
        assert r1.status_code == 200
        assert r2.status_code == 200
        body = r1.json()
        assert body["status"] in {"healthy", "degraded"}
        assert "checks" in body
        assert app._asgi is not None
    finally:
        del os.environ["APP_USERS_PATH"]
        del os.environ["SIGNING_KEY"]


def test_tools_registered_with_identity_enforcement(tools_module, tmp_path):
    """Every discovered tool is wrapped with identity enforcement."""
    os.environ["APP_USERS_PATH"] = str(tmp_path / "users")
    os.environ["SIGNING_KEY"] = "test-key-32chars-minimum-length!!"
    try:
        app = App(name="test-app", tools_module=tools_module)
        app._asgi = app._build_asgi()
        tool_names = [t.name for t in app._mcp._tool_manager.list_tools()]
        assert "greet" in tool_names
        assert "ping" in tool_names
    finally:
        del os.environ["APP_USERS_PATH"]
        del os.environ["SIGNING_KEY"]
