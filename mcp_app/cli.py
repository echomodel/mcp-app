"""mcp-app CLI — serve command."""

from pathlib import Path

import click


@click.group()
def main():
    """MCP application framework."""
    pass


@main.command()
@click.argument("app_path", required=False, default=None)
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8080, type=int)
def serve(app_path, host, port):
    """Run MCP server over HTTP (production, multi-user).

    APP_PATH: Optional path to the directory containing mcp-app.yaml.
    Defaults to the current working directory.
    """
    import uvicorn
    from mcp_app.bootstrap import build_app

    config_path = Path(app_path) / "mcp-app.yaml" if app_path else None
    app, mcp, store, config = build_app(config_path)

    import mcp_app
    mcp_app._store = store

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
