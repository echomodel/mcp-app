"""`connect` keeps the saved remote when switching targets (#43).

Drives the per-app and generic admin CLIs through Click's CliRunner with
XDG_CONFIG_HOME and APP_USERS_PATH redirected to a tmp directory, and
asserts on the persisted setup.json plus the store `admin_store` resolves.
"""

import json

import click
import pytest
from click.testing import CliRunner

from mcp_app import admin_store, admin_target
from mcp_app.admin_client import RemoteAuthAdapter
from mcp_app.bridge import DataStoreAuthAdapter
from mcp_app.cli import create_admin_cli, main as generic_cli

APP = "connect-test-app"
URL = "https://svc.example.com"
KEY = "test-signing-key"


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APP_USERS_PATH", str(tmp_path / "users"))
    monkeypatch.delenv("MCP_APP_URL", raising=False)
    monkeypatch.delenv("MCP_APP_SIGNING_KEY", raising=False)
    return tmp_path / "config" / APP / "setup.json"


def _admin(*args):
    result = CliRunner().invoke(create_admin_cli(APP), list(args))
    return result


def _setup(path):
    return json.loads(path.read_text())


def test_connect_local_keeps_saved_remote(config):
    assert _admin("connect", URL, "--signing-key", KEY).exit_code == 0
    result = _admin("connect", "local")
    assert result.exit_code == 0 and "Saved remote kept" in result.output
    assert _setup(config) == {"mode": "local", "url": URL, "signing_key": KEY}


def test_connect_remote_restores_saved_remote_without_key(config):
    _admin("connect", URL, "--signing-key", KEY)
    _admin("connect", "local")
    result = _admin("connect", "remote")
    assert result.exit_code == 0
    assert _setup(config) == {"mode": "remote", "url": URL, "signing_key": KEY}


def test_connect_remote_without_saved_remote_errors(config):
    _admin("connect", "local")
    result = _admin("connect", "remote")
    assert result.exit_code != 0 and "No saved remote" in result.output


def test_connect_same_url_reuses_saved_key(config):
    _admin("connect", URL + "/", "--signing-key", KEY)
    _admin("connect", "local")
    result = _admin("connect", URL)
    assert result.exit_code == 0 and "Reusing the saved signing key" in result.output
    assert _setup(config) == {"mode": "remote", "url": URL, "signing_key": KEY}


def test_connect_different_url_does_not_reuse_key(config):
    _admin("connect", URL, "--signing-key", KEY)
    _admin("connect", "https://other.example.com")
    assert _setup(config) == {"mode": "remote", "url": "https://other.example.com"}


def test_explicit_key_replaces_saved_key(config):
    _admin("connect", URL, "--signing-key", KEY)
    _admin("connect", URL, "--signing-key", "new-key")
    assert _setup(config)["signing_key"] == "new-key"


def test_generic_cli_connect_remote(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    runner = CliRunner()
    runner.invoke(generic_cli, ["connect", URL, "--signing-key", KEY])
    assert runner.invoke(generic_cli, ["connect", "remote"]).exit_code == 0
    assert runner.invoke(generic_cli, ["connect", "local"]).exit_code != 0


def test_admin_store_follows_the_selected_target(config):
    with pytest.raises(click.ClickException, match="Not configured"):
        admin_target(APP)
    _admin("connect", URL, "--signing-key", KEY)
    assert admin_target(APP) == "remote"
    assert isinstance(admin_store(APP), RemoteAuthAdapter)
    _admin("connect", "local")
    assert admin_target(APP) == "local"
    assert isinstance(admin_store(APP), DataStoreAuthAdapter)
    _admin("connect", "remote")
    store = admin_store(APP)
    assert isinstance(store, RemoteAuthAdapter) and store.base_url == URL
