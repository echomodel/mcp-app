"""Test profile_flags helper generates correct CLI flags."""

from pydantic import BaseModel

from mcp_app.app import App
from mcp_app.testing.fixtures import profile_flags


def _make_app(**kwargs):
    """Minimal app for testing — no real tools module needed."""
    import types
    tools = types.ModuleType("fake_tools")
    return App(name="test-app", tools_module=tools, **kwargs)


def test_no_profile_returns_empty():
    app = _make_app()
    assert profile_flags(app) == []


def test_profile_without_expand_returns_empty():
    class Profile(BaseModel):
        token: str

    app = _make_app(profile_model=Profile, profile_expand=False)
    assert profile_flags(app) == []


def test_profile_with_expand_returns_flags():
    class Profile(BaseModel):
        token: str

    app = _make_app(profile_model=Profile, profile_expand=True)
    assert profile_flags(app) == ["--token", "test-placeholder"]


def test_multiple_fields_returns_all_flags():
    class Profile(BaseModel):
        api_key: str
        refresh_token: str

    app = _make_app(profile_model=Profile, profile_expand=True)
    flags = profile_flags(app)
    assert flags == [
        "--api-key", "test-placeholder",
        "--refresh-token", "test-placeholder",
    ]
