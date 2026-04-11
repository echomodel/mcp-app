"""Run the framework contract tests against the fixture app."""

import pytest
from tests.tck.fixture_app import tools
from mcp_app.app import App


@pytest.fixture(scope="session")
def app():
    return App(
        name="tck-fixture",
        tools_module=tools,
    )
