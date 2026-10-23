"""The MCP server mcp-app runs: the SDK's ``MCPServer`` plus per-caller
tool visibility.

The SDK registers tools once and lists the same set to every caller.
mcp-app needs one more rule: a tool marked admin-only is neither listed
nor callable unless the current user is an administrator. Both checks
read ``current_user``, which the identity middleware sets before the MCP
layer runs, so the decision is per request and costs a set lookup.

Over stdio there is one local user who launched the process; they are
the operator, so admin-only tools are visible and callable there.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError


class AppServer(MCPServer):
    """``MCPServer`` that hides and blocks admin-only tools for non-admins."""

    def __init__(self, *args, admin_only: set[str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.admin_only: set[str] = set(admin_only or ())

    def caller_is_admin(self) -> bool:
        import mcp_app
        from mcp_app.auth import is_admin
        from mcp_app.context import current_user

        if mcp_app.get_transport() == "stdio":
            return True
        try:
            user = current_user.get()
        except LookupError:
            return False
        return is_admin(user.email)

    async def list_tools(self):
        tools = await super().list_tools()
        if not self.admin_only or self.caller_is_admin():
            return tools
        return [t for t in tools if t.name not in self.admin_only]

    async def call_tool(self, name: str, arguments: dict[str, Any], context=None):
        if name in self.admin_only and not self.caller_is_admin():
            # Same wording the SDK uses for a name that does not exist, so a
            # hidden tool is indistinguishable from an absent one.
            raise ToolError(f"Unknown tool: {name}")
        return await super().call_tool(name, arguments, context)
