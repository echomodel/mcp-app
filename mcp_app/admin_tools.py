"""MCP tool server for managing deployed mcp-app instances.

Stateless tools — every call takes base_url and signing_key explicitly.
Run via: mcp-app admin-tools
"""

from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from mcp_app.admin_client import RemoteAuthAdapter
from mcp_app.models import UserAuthRecord

mcp = FastMCP("mcp-app-admin")


@mcp.tool()
async def health_check(base_url: str) -> dict:
    """Check if a deployed mcp-app instance is reachable and healthy."""
    return await RemoteAuthAdapter(base_url, "unused").health_check()


@mcp.tool()
async def list_users(base_url: str, signing_key: str) -> list[dict]:
    """List all registered users on a deployed mcp-app instance."""
    users = await RemoteAuthAdapter(base_url, signing_key).list()
    return [u.model_dump(mode="json") for u in users]


@mcp.tool()
async def register_user(base_url: str, signing_key: str, email: str,
                        profile: dict | None = None) -> dict:
    """Register a user on a deployed mcp-app instance. Returns their token."""
    adapter = RemoteAuthAdapter(base_url, signing_key)
    return await adapter.save(
        UserAuthRecord(email=email, created=datetime.now(timezone.utc)),
        profile=profile,
    )


@mcp.tool()
async def create_token(base_url: str, signing_key: str, email: str) -> dict:
    """Create a new token for an existing user on a deployed mcp-app instance."""
    return await RemoteAuthAdapter(base_url, signing_key).create_token(email)


@mcp.tool()
async def update_user_profile(base_url: str, signing_key: str, email: str,
                               updates: dict) -> dict:
    """Update profile fields for a user on a deployed mcp-app instance.

    Merges the updates dict into the existing profile. Does not replace
    fields that aren't in updates.
    """
    return await RemoteAuthAdapter(base_url, signing_key).update_profile(email, updates)


@mcp.tool()
async def revoke_user(base_url: str, signing_key: str, email: str) -> dict:
    """Revoke a user's access on a deployed mcp-app instance."""
    await RemoteAuthAdapter(base_url, signing_key).delete(email)
    return {"revoked": email}


@mcp.tool()
async def probe(base_url: str, signing_key: str,
                user_email: str | None = None) -> dict:
    """Probe a deployed mcp-app instance: health + MCP tools round-trip.

    Hits /health for liveness, then attempts tools/list. If user_email
    is omitted, the first registered user is used for the MCP probe.
    """
    return await RemoteAuthAdapter(base_url, signing_key).probe(
        user_email=user_email,
    )


@mcp.tool()
async def register_commands(
    base_url: str,
    signing_key: str,
    name: str,
    user_email: str | None = None,
    clients: list[str] | None = None,
    scopes: list[str] | None = None,
) -> dict:
    """Generate MCP client registration commands for a deployed instance.

    Returns the exact commands to paste into Claude Code, Gemini CLI,
    or the URL form for Claude.ai. If user_email is provided, a fresh
    token is minted for them. Otherwise a placeholder is emitted.
    """
    from mcp_app.registration import generate_registrations

    token = None
    if user_email:
        adapter = RemoteAuthAdapter(base_url, signing_key)
        result = await adapter.create_token(user_email)
        token = result["token"]

    return generate_registrations(
        name=name,
        url=base_url,
        token=token,
        clients=clients,
        scopes=scopes,
    )
