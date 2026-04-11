"""Minimal installable app for running mcp_app.testing against."""

from mcp_app.app import App
from fixture_app import tools

app = App(
    name="fixture-app",
    tools_module=tools,
)
