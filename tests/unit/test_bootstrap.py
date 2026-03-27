"""Tests for mcp-app bootstrap — config loading, tool discovery, app building."""

import os
import pytest
from pathlib import Path

from mcp_app.bootstrap import (
    load_config,
    _resolve_class,
    _discover_tools,
    build_mcp,
    build_store,
    STORE_ALIASES,
    MIDDLEWARE_ALIASES,
)


# --- Config loading ---

def test_load_config(tmp_path):
    (tmp_path / "mcp-app.yaml").write_text(
        "name: test-app\nstore: filesystem\ntools: my.module\n"
    )
    config = load_config(tmp_path / "mcp-app.yaml")
    assert config["name"] == "test-app"
    assert config["store"] == "filesystem"
    assert config["tools"] == "my.module"


def test_load_config_missing():
    with pytest.raises(FileNotFoundError):
        load_config(Path("/nonexistent/mcp-app.yaml"))


# --- Class resolution ---

def test_resolve_alias():
    cls = _resolve_class("filesystem", STORE_ALIASES)
    from mcp_app.data_store import FileSystemUserDataStore
    assert cls is FileSystemUserDataStore


def test_resolve_module_path():
    cls = _resolve_class("mcp_app.data_store.FileSystemUserDataStore", STORE_ALIASES)
    from mcp_app.data_store import FileSystemUserDataStore
    assert cls is FileSystemUserDataStore


def test_resolve_unknown_alias():
    with pytest.raises(ValueError, match="Unknown alias"):
        _resolve_class("nonexistent", STORE_ALIASES)


def test_resolve_middleware_alias():
    cls = _resolve_class("user-identity", MIDDLEWARE_ALIASES)
    from mcp_app.middleware import JWTMiddleware
    assert cls is JWTMiddleware


# --- Tool discovery ---

def test_discover_tools_finds_async_functions(tmp_path):
    """Create a temp module with async functions and discover them."""
    import sys
    mod_dir = tmp_path / "test_tools_pkg"
    mod_dir.mkdir()
    (mod_dir / "__init__.py").write_text("")
    (mod_dir / "tools.py").write_text(
        "async def public_tool() -> dict:\n"
        "    return {'ok': True}\n\n"
        "async def another_tool(x: int) -> dict:\n"
        "    return {'x': x}\n\n"
        "async def _private() -> dict:\n"
        "    return {}\n\n"
        "def sync_func() -> dict:\n"
        "    return {}\n"
    )
    sys.path.insert(0, str(tmp_path))
    try:
        tools = _discover_tools("test_tools_pkg.tools")
        names = [f.__name__ for f in tools]
        assert "public_tool" in names
        assert "another_tool" in names
        assert "_private" not in names
        assert "sync_func" not in names
    finally:
        sys.path.remove(str(tmp_path))


# --- Store building ---

def test_build_store_filesystem(tmp_path):
    os.environ["APP_USERS_PATH"] = str(tmp_path / "users")
    try:
        config = {"name": "test-app", "store": "filesystem"}
        store = build_store(config)
        assert store.base == tmp_path / "users"
    finally:
        del os.environ["APP_USERS_PATH"]


def test_build_store_default_name():
    config = {"store": "filesystem"}
    store = build_store(config)
    assert "mcp-app" in str(store.base)


# --- MCP building ---

def test_build_mcp_registers_tools(tmp_path):
    """Build MCP from config with a real tools module."""
    import sys
    mod_dir = tmp_path / "mcp_test_pkg"
    mod_dir.mkdir()
    (mod_dir / "__init__.py").write_text("")
    (mod_dir / "tools.py").write_text(
        "async def greet(name: str) -> dict:\n"
        "    \"\"\"Say hello.\"\"\"\n"
        "    return {'message': f'hello {name}'}\n"
    )
    sys.path.insert(0, str(tmp_path))
    try:
        config = {"name": "test", "tools": "mcp_test_pkg.tools"}
        mcp = build_mcp(config)
        tool_names = [t.name for t in mcp._tool_manager.list_tools()]
        assert "greet" in tool_names
    finally:
        sys.path.remove(str(tmp_path))


def test_build_mcp_requires_tools():
    with pytest.raises(ValueError, match="must specify 'tools'"):
        build_mcp({"name": "test"})
