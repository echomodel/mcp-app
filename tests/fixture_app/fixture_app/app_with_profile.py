"""Fixture app variant with profile_expand=True for testing profile-aware tests."""

from pydantic import BaseModel

from mcp_app.app import App
from fixture_app import tools


class Profile(BaseModel):
    token: str


app_with_profile = App(
    name="fixture-app",
    tools_module=tools,
    profile_model=Profile,
    profile_expand=True,
)
