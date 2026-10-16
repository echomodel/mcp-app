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
from mcp_app.cli import _save_setup, create_admin_cli, main as generic_cli

APP = "connect-test-app"
URL = "https://svc.example.com"


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APP_USERS_PATH", str(tmp_path / "users"))
    return tmp_path / "config" / APP / "setup.json"


def _admin(*args):
    return CliRunner().invoke(create_admin_cli(APP), list(args))


def _setup(path):
    return json.loads(path.read_text())


def test_connect_url_saves_remote(config):
    result = _admin("connect", URL + "/")
    assert result.exit_code == 0, result.output
    assert _setup(config) == {"mode": "remote", "url": URL}
    assert "Discovery" in result.output


def test_connect_local_keeps_saved_remote(config):
    assert _admin("connect", URL).exit_code == 0
    result = _admin("connect", "local")
    assert result.exit_code == 0 and "Saved remote kept" in result.output
    assert _setup(config) == {"mode": "local", "url": URL}


def test_connect_remote_restores_saved_remote(config):
    _admin("connect", URL)
    _admin("connect", "local")
    result = _admin("connect", "remote")
    assert result.exit_code == 0
    assert _setup(config) == {"mode": "remote", "url": URL}


def test_connect_remote_without_saved_remote_errors(config):
    _admin("connect", "local")
    result = _admin("connect", "remote")
    assert result.exit_code != 0 and "No saved remote" in result.output


def test_connect_rejects_the_removed_signing_key_flag(config):
    result = _admin("connect", URL, "--signing-key", "anything")
    assert result.exit_code != 0
    assert "no such option" in result.output.lower()


def test_saved_access_token_survives_same_url_and_not_another(config):
    """A future sign-in stores a token next to the URL; reconnecting to the
    same URL keeps it, a different URL drops it."""
    _save_setup({"mode": "remote", "url": URL, "access_token": "tok"}, app_name=APP)
    _admin("connect", URL)
    assert _setup(config)["access_token"] == "tok"
    _admin("connect", "https://other.example.com")
    assert "access_token" not in _setup(config)


def test_generic_cli_connect_remote(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    runner = CliRunner()
    runner.invoke(generic_cli, ["connect", URL])
    assert runner.invoke(generic_cli, ["connect", "remote"]).exit_code == 0
    assert runner.invoke(generic_cli, ["connect", "local"]).exit_code != 0


def test_admin_store_follows_the_selected_target(config):
    with pytest.raises(click.ClickException, match="Not configured"):
        admin_target(APP)
    _admin("connect", URL)
    assert admin_target(APP) == "remote"
    assert isinstance(admin_store(APP), RemoteAuthAdapter)
    _admin("connect", "local")
    assert admin_target(APP) == "local"
    assert isinstance(admin_store(APP), DataStoreAuthAdapter)
    _admin("connect", "remote")
    store = admin_store(APP)
    assert isinstance(store, RemoteAuthAdapter) and store.base_url == URL


def test_remote_users_without_sign_in_fails_cleanly(config):
    _admin("connect", URL)
    result = _admin("users", "list")
    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "signed in as an administrator" in result.output
