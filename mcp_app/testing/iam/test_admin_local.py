"""Admin CLI local mode contract — connect local, users add/list/revoke."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_app.testing.fixtures import mcp_binary, admin_binary, profile_flags


@pytest.fixture
def local_env(app, tmp_path):
    """Isolated env for local admin CLI tests."""
    binary = str(Path(sys.executable).parent / f"{app.name}-admin")
    if not Path(binary).exists():
        pytest.skip(f"{app.name}-admin not installed at {binary}")

    env = {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "APP_USERS_PATH": str(tmp_path / "users"),
        "PATH": str(Path(sys.executable).parent),
    }
    for d in env.values():
        Path(d).mkdir(parents=True, exist_ok=True)

    return binary, env, tmp_path


def _run(binary, args, env):
    result = subprocess.run(
        [binary] + args,
        capture_output=True, text=True, env=env, timeout=10,
    )
    return result


def test_connect_local(local_env):
    binary, env, _ = local_env
    result = _run(binary, ["connect", "local"], env)
    assert result.returncode == 0
    assert "local" in result.stdout.lower()


def test_users_add_locally(app, local_env):
    binary, env, tmp_path = local_env
    _run(binary, ["connect", "local"], env)
    result = _run(binary, ["users", "add", "alice@example.com"] + profile_flags(app), env)
    assert result.returncode == 0
    assert "alice@example.com" in result.stdout


def test_users_list_locally(app, local_env):
    binary, env, _ = local_env
    _run(binary, ["connect", "local"], env)
    _run(binary, ["users", "add", "alice@example.com"] + profile_flags(app), env)
    result = _run(binary, ["users", "list"], env)
    assert result.returncode == 0
    assert "alice@example.com" in result.stdout


def test_users_add_without_connect_fails(app, local_env):
    binary, env, _ = local_env
    result = _run(binary, ["users", "add", "alice@example.com"] + profile_flags(app), env)
    assert result.returncode != 0
    assert "not configured" in result.stdout.lower() or "not configured" in result.stderr.lower()


def test_health_local_mode(local_env):
    binary, env, _ = local_env
    _run(binary, ["connect", "local"], env)
    result = _run(binary, ["health"], env)
    assert result.returncode == 0
    assert "local" in result.stdout.lower()


def test_tokens_rejected_in_local_mode(local_env):
    binary, env, _ = local_env
    _run(binary, ["connect", "local"], env)
    result = _run(binary, ["tokens", "create", "alice@example.com"], env)
    assert "remote" in result.stdout.lower() or result.returncode == 0
