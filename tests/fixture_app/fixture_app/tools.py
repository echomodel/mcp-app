"""Minimal tools module — just enough to validate the contract tests."""

from mcp_app.context import current_user


async def ping() -> dict:
    """Health check."""
    return {"pong": True}


async def greet(name: str) -> dict:
    """Greet someone."""
    user = current_user.get()
    return {"message": f"hello {name}", "from": user.email}
