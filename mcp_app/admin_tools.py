"""MCP tool server for managing deployed mcp-app instances from an agent.

Stateless tools — every call takes ``base_url`` and, where the deployment's
admin API is involved, the caller's own ``access_token`` from the identity
provider (an email in that deployment's ``ADMIN_EMAILS``). Run via:
``mcp-app admin-tools``.
"""

from datetime import datetime, timezone

from mcp.server.mcpserver import MCPServer

from mcp_app.admin_client import RemoteAuthAdapter
from mcp_app.models import UserAuthRecord

mcp = MCPServer("mcp-app-admin")


@mcp.tool()
async def health_check(base_url: str) -> dict:
    """Check if a deployed mcp-app instance is reachable and healthy."""
    return await RemoteAuthAdapter(base_url).health_check()


@mcp.tool()
async def probe(base_url: str) -> dict:
    """Verify a deployment's OAuth front door without signing in.

    Health, the protected-resource metadata (which issuer it names), and
    the 401 challenge an MCP client receives first.
    """
    return await RemoteAuthAdapter(base_url).probe()


@mcp.tool()
async def list_users(base_url: str, access_token: str) -> list[dict]:
    """List all registered users on a deployed mcp-app instance."""
    users = await RemoteAuthAdapter(base_url, access_token).list()
    return [u.model_dump(mode="json") for u in users]


@mcp.tool()
async def register_user(base_url: str, access_token: str, email: str,
                        profile: dict | None = None) -> dict:
    """Register a user on a deployed mcp-app instance.

    The user signs in with the identity provider from their own MCP client;
    nothing is handed to them.
    """
    adapter = RemoteAuthAdapter(base_url, access_token)
    return await adapter.save(
        UserAuthRecord(email=email, created=datetime.now(timezone.utc)),
        profile=profile,
    )


@mcp.tool()
async def update_user_profile(base_url: str, access_token: str, email: str,
                               updates: dict) -> dict:
    """Update profile fields for a user on a deployed mcp-app instance.

    Merges the updates dict into the existing profile. Does not replace
    fields that aren't in updates.
    """
    return await RemoteAuthAdapter(base_url, access_token).update_profile(email, updates)


@mcp.tool()
async def revoke_user(base_url: str, access_token: str, email: str) -> dict:
    """Revoke a user's access on a deployed mcp-app instance."""
    await RemoteAuthAdapter(base_url, access_token).delete(email)
    return {"revoked": email}


@mcp.tool()
async def register_commands(
    base_url: str,
    name: str,
    clients: list[str] | None = None,
    scopes: list[str] | None = None,
) -> dict:
    """Generate MCP client registration commands for a deployed instance.

    Returns the exact commands to paste into Claude Code or Antigravity
    CLI (agy), and the URL to add in Claude.ai. The client runs the
    sign-in; no credential is part of the command.
    """
    from mcp_app.registration import generate_registrations

    return generate_registrations(
        name=name,
        url=base_url,
        clients=clients,
        scopes=scopes,
    )
