"""Import contract tests so pytest discovers them in this directory.

The `app` fixture from conftest.py is available to all imported tests.
"""

from mcp_app.testing.contracts.test_pyproject_wiring import *  # noqa: F401,F403
from mcp_app.testing.contracts.test_http_transport import *  # noqa: F401,F403
from mcp_app.testing.contracts.test_tool_coverage import *  # noqa: F401,F403
