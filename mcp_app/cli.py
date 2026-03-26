"""mcp-app CLI — stdio and serve commands."""

import click


@click.group()
def main():
    """MCP application framework."""
    pass


@main.command()
def stdio():
    """Run MCP server over stdio (local, single user)."""
    from mcp_app.bootstrap import load_config, build_mcp, build_store

    config = load_config()
    store = build_store(config)

    # Make store available to tools via module-level import
    import mcp_app
    mcp_app._store = store

    mcp = build_mcp(config)
    mcp.run()


@main.command()
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8080, type=int)
def serve(host, port):
    """Run MCP server over HTTP (production, multi-user)."""
    import uvicorn
    from mcp_app.bootstrap import build_app

    app, mcp, store, config = build_app()

    # Make store available to tools via module-level import
    import mcp_app
    mcp_app._store = store

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
