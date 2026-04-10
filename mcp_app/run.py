"""Python API for running mcp-app servers.

Most solutions should use mcp_app.entry (zero-boilerplate entry points
via pyproject.toml). This module provides the underlying API for solutions
that need explicit control over the config path.
"""

from pathlib import Path


def stdio(config_path: str | Path) -> None:
    """Run MCP server over stdio (local, single user).

    Args:
        config_path: Path to mcp-app.yaml.
    """
    from mcp_app.bootstrap import build_stdio
    from mcp_app.context import current_user_id
    import mcp_app

    config_path = Path(config_path)
    mcp, store, config = build_stdio(config_path)
    mcp_app._store = store

    stdio_config = config.get("stdio", {})
    user = stdio_config.get("user")
    if not user:
        raise RuntimeError(
            "stdio.user not configured in mcp-app.yaml. "
            "Add:\n\n  stdio:\n    user: \"local\"\n"
        )
    current_user_id.set(user)
    mcp.run(transport="stdio")


def serve(config_path: str | Path, host: str = "0.0.0.0", port: int = 8080) -> None:
    """Run MCP HTTP server (production, multi-user).

    Args:
        config_path: Path to mcp-app.yaml.
        host: Bind address.
        port: Bind port.
    """
    import uvicorn
    from mcp_app.bootstrap import build_app
    import mcp_app

    config_path = Path(config_path)
    app, _mcp, store, _config = build_app(config_path)
    mcp_app._store = store
    uvicorn.run(app, host=host, port=port)
