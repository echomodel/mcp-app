"""Shared test fixtures for mcp-app contract tests.

Solutions use these in their conftest.py. The fixtures handle
binary pinning (no pipx shadowing), environment isolation, and
app discovery.
"""

import os
import sys
from pathlib import Path

import pytest

from mcp_app.app import App


def _binary_path(name: str) -> Path:
    """Resolve a binary to the current venv's bin/, not PATH."""
    return Path(sys.executable).parent / name


def app_fixture(app: App):
    """Create a pytest fixture from an App instance.

    Returns a fixture function that yields the app with binary
    paths resolved to the current venv.
    """
    @pytest.fixture(scope="session")
    def _app():
        return app
    return _app


@pytest.fixture
def tmp_env(tmp_path):
    """Isolate all writable paths — HOME, XDG, APP_USERS_PATH.

    Prevents tests from polluting real dotfiles or reading stale
    state from earlier runs.
    """
    env = {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "APP_USERS_PATH": str(tmp_path / "users"),
    }
    old = {}
    for k, v in env.items():
        old[k] = os.environ.get(k)
        os.environ[k] = v
        Path(v).mkdir(parents=True, exist_ok=True)

    yield env

    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def require_binary(name: str):
    """Skip test if the named binary isn't installed in the venv."""
    path = _binary_path(name)
    return pytest.mark.skipif(
        not path.exists(),
        reason=f"{name} not installed at {path}",
    )


def mcp_binary(app: App) -> str:
    """Absolute path to the app's MCP CLI binary in the venv."""
    return str(_binary_path(f"{app.name}-mcp"))


def admin_binary(app: App) -> str:
    """Absolute path to the app's admin CLI binary in the venv."""
    return str(_binary_path(f"{app.name}-admin"))


def profile_flags(app: App) -> list[str]:
    """Generate dummy CLI flags for the app's profile model.

    If the app has profile_expand=True, returns flags like
    ['--token', 'test-placeholder'] for each field. If no
    profile or expand=False, returns an empty list.
    """
    if not app.profile_model or not app.profile_expand:
        return []
    flags = []
    for name in app.profile_model.model_fields:
        flags.extend([f"--{name.replace('_', '-')}", "test-placeholder"])
    return flags
