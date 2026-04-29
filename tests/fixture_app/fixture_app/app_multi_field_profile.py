"""Fixture app variant with two required profile fields.

Used to exercise the partial-update path: rotating one field of a
multi-required-field profile must validate against the merged
post-update state, not the patch dict alone.
"""

from pydantic import BaseModel

from mcp_app.app import App
from fixture_app import tools


class Profile(BaseModel):
    region: str
    token: str


app_multi_field_profile = App(
    name="fixture-app-multi",
    tools_module=tools,
    profile_model=Profile,
    profile_expand=True,
)
