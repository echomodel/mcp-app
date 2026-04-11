"""App fixture for tests/framework/.

tests/framework/ runs mcp-app's shipped test suite (mcp_app.testing)
against a specific app to check that auth, user admin, JWT enforcement,
CLI wiring, and tool protocol compliance all work for that app.

The test modules in test_framework.py are identical across every
mcp-app solution — they import from mcp_app.testing.iam, .wiring,
.tools, .health. THIS FILE is the only thing that changes: it tells
the tests which app to run against.

Here in the mcp-app repo, it points at a minimal fixture app. In a
real app like echofit, it points at the real App object:

    import pytest
    from my_app_mcp import app as my_app

    @pytest.fixture(scope="session")
    def app():
        return my_app
"""

import pytest
from fixture_app import app as fixture_app


@pytest.fixture(scope="session")
def app():
    return fixture_app
