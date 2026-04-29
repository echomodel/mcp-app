"""CLI-level regression tests for the per-app `users update-profile` command.

Covers the bug where validating the patch dict alone causes
`ValidationError: field required` for any profile model with two or
more required fields. The fix merges the patch into the existing
stored profile before validating, so partial updates against an
already-complete profile succeed.

These tests drive the per-app admin CLI through Click's CliRunner so
they exercise the same code path operators hit at the terminal.
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from pydantic import BaseModel, ValidationError

from mcp_app.app import App
from mcp_app.cli import create_admin_cli


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Point XDG config and the app store at a tmp directory.

    The per-app admin CLI persists `connect local` config under
    XDG_CONFIG_HOME and reads/writes user records under
    APP_USERS_PATH. Both must be redirected per-test to avoid
    polluting the user's real config.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APP_USERS_PATH", str(tmp_path / "users"))
    return tmp_path


def _make_admin_cli(app_name: str, profile_model):
    """Construct an App (which registers the profile model) and
    return the per-app admin CLI built against that registration."""
    import types
    tools = types.ModuleType("fake_tools")
    App(
        name=app_name,
        tools_module=tools,
        profile_model=profile_model,
        profile_expand=True,
    )
    return create_admin_cli(app_name)


def test_update_profile_partial_patch_succeeds_with_multi_required_fields(isolated_dirs):
    """Regression: PATCHing one field of a profile with multiple required
    fields must succeed when the other required field is already stored."""

    class Profile(BaseModel):
        region: str
        token: str

    cli = _make_admin_cli("multi-field-app", Profile)
    runner = CliRunner()

    # Connect the admin CLI to a local store under the tmp XDG config
    result = runner.invoke(cli, ["connect", "local"])
    assert result.exit_code == 0, result.output

    # Add a user with both required fields populated
    result = runner.invoke(
        cli, ["users", "add", "alice@example.com",
              "--region", "us-west", "--token", "old-token"],
    )
    assert result.exit_code == 0, result.output

    # Rotate just the token — must NOT fail with "region required"
    result = runner.invoke(
        cli, ["users", "update-profile", "alice@example.com",
              "token", "new-token"],
    )
    assert result.exit_code == 0, result.output
    assert "Updated token" in result.output

    # Confirm the merge actually happened by reading the profile back
    result = runner.invoke(
        cli, ["users", "get-profile", "alice@example.com", "--json"],
    )
    assert result.exit_code == 0, result.output
    profile = json.loads(result.output)
    assert profile == {"region": "us-west", "token": "new-token"}


def test_update_profile_still_validates_field_value(isolated_dirs):
    """The merge-before-validate fix must not weaken validation —
    a value that violates a per-field constraint still fails."""
    from pydantic import StringConstraints
    from typing import Annotated

    class Profile(BaseModel):
        region: str
        token: Annotated[str, StringConstraints(min_length=8)]

    cli = _make_admin_cli("min-length-app", Profile)
    runner = CliRunner()

    runner.invoke(cli, ["connect", "local"])
    runner.invoke(
        cli, ["users", "add", "alice@example.com",
              "--region", "us-west", "--token", "long-enough-token"],
    )

    # Try to set token to a value that's too short
    result = runner.invoke(
        cli, ["users", "update-profile", "alice@example.com",
              "token", "short"],
    )
    assert result.exit_code != 0
    # Pydantic surfaces the validation error in some form
    assert "token" in result.output.lower() or isinstance(result.exception, ValidationError)


def test_update_profile_unknown_user_errors(isolated_dirs):
    """Unknown user is rejected before any validation runs."""

    class Profile(BaseModel):
        region: str
        token: str

    cli = _make_admin_cli("unknown-user-app", Profile)
    runner = CliRunner()

    runner.invoke(cli, ["connect", "local"])

    result = runner.invoke(
        cli, ["users", "update-profile", "nobody@example.com",
              "token", "x"],
    )
    assert result.exit_code != 0
    assert "not found" in result.output.lower()
