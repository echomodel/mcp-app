"""MCP tool server for managing deployed mcp-app instances.

Stateless tools — every call takes base_url and signing_key explicitly.
Run via: mcp-app admin-tools
"""

from mcp.server.fastmcp import FastMCP

from mcp_app.admin_client import AdminClient

mcp = FastMCP("mcp-app-admin")


@mcp.tool()
async def health_check(base_url: str) -> dict:
    """Check if a deployed mcp-app instance is reachable and healthy."""
    return await AdminClient(base_url, "unused").health_check()


@mcp.tool()
async def list_users(base_url: str, signing_key: str) -> list[dict]:
    """List all registered users on a deployed mcp-app instance."""
    return await AdminClient(base_url, signing_key).list_users()


@mcp.tool()
async def register_user(base_url: str, signing_key: str, email: str) -> dict:
    """Register a user on a deployed mcp-app instance. Returns their token."""
    return await AdminClient(base_url, signing_key).register_user(email)


@mcp.tool()
async def create_token(base_url: str, signing_key: str, email: str) -> dict:
    """Create a new token for an existing user on a deployed mcp-app instance."""
    return await AdminClient(base_url, signing_key).create_token(email)


@mcp.tool()
async def revoke_user(base_url: str, signing_key: str, email: str) -> dict:
    """Revoke a user's access on a deployed mcp-app instance."""
    return await AdminClient(base_url, signing_key).revoke_user(email)
