"""Admin CLI error paths — misuse produces clear errors, not crashes."""

import subprocess
import sys
from pathlib import Path

import pytest

from mcp_app.testing.fixtures import profile_flags


@pytest.fixture
def admin_env(app, tmp_path):
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

    return binary, env


def _run(binary, args, env):
    return subprocess.run(
        [binary] + args,
        capture_output=True, text=True, env=env, timeout=10,
    )


def test_users_add_without_connect_fails(app, admin_env):
    binary, env = admin_env
    result = _run(binary, ["users", "add", "alice@example.com"] + profile_flags(app), env)
    assert result.returncode != 0


def test_connect_url_without_signing_key_succeeds_but_users_fails(app, admin_env):
    """connect <url> without --signing-key saves config but users add fails."""
    binary, env = admin_env
    connect = _run(binary, ["connect", "https://fake.example.com"], env)
    assert connect.returncode == 0

    add = _run(binary, ["users", "add", "alice@example.com"] + profile_flags(app), env)
    assert add.returncode != 0


def test_health_without_connect_fails(admin_env):
    binary, env = admin_env
    result = _run(binary, ["health"], env)
    assert result.returncode != 0
