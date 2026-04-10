"""mcp-app CLI — serve and admin commands."""

import asyncio
import json
import os
from pathlib import Path

import click


def _config_path() -> Path:
    """XDG config path for mcp-app."""
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return Path(xdg) / "mcp-app" / "active.json"


def _load_config() -> dict:
    path = _config_path()
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _save_config(data: dict):
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _resolve_url(url: str | None) -> str:
    """Resolve base URL: flag → env → config."""
    result = url or os.environ.get("MCP_APP_URL") or _load_config().get("url")
    if not result:
        raise click.ClickException(
            "No base URL. Use --url, set MCP_APP_URL, or run: mcp-app set-base-url <url>"
        )
    return result


def _resolve_signing_key(key: str | None) -> str:
    """Resolve signing key: flag → env → config."""
    result = key or os.environ.get("MCP_APP_SIGNING_KEY") or _load_config().get("signing_key")
    if not result:
        raise click.ClickException(
            "No signing key. Use --signing-key, set MCP_APP_SIGNING_KEY, or include in set-base-url."
        )
    return result


def _client(url: str | None, signing_key: str | None):
    from mcp_app.admin_client import AdminClient
    return AdminClient(_resolve_url(url), _resolve_signing_key(signing_key))


def _run(coro):
    """Run an async coroutine from sync CLI context."""
    return asyncio.run(coro)


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
    from mcp_app.run import serve as run_serve

    config_path = Path(app_path) / "mcp-app.yaml" if app_path else Path.cwd() / "mcp-app.yaml"
    run_serve(config_path, host=host, port=port)


@main.command()
@click.argument("app_path", required=False, default=None)
def stdio(app_path):
    """Run MCP server over stdio (local, single user).

    APP_PATH: Optional path to the directory containing mcp-app.yaml.
    Defaults to the current working directory.

    Reads mcp-app.yaml, discovers tools, wires the store, and runs
    FastMCP over stdin/stdout. No middleware, no admin endpoints.
    """
    from mcp_app.run import stdio as run_stdio

    config_path = Path(app_path) / "mcp-app.yaml" if app_path else Path.cwd() / "mcp-app.yaml"
    run_stdio(config_path)


@main.command("set-base-url")
@click.argument("url")
@click.option("--signing-key", default=None, help="Signing key for admin auth.")
def set_base_url(url, signing_key):
    """Set the base URL (and optionally signing key) for a deployed instance."""
    config = _load_config()
    config["url"] = url
    if signing_key:
        config["signing_key"] = signing_key
    _save_config(config)
    click.echo(f"Set base URL: {url}")


@main.command()
@click.option("--url", default=None, help="Base URL of the deployed instance.")
@click.option("--signing-key", default=None)
def health(url, signing_key):
    """Check health of a deployed instance."""
    from mcp_app.admin_client import AdminClient
    resolved_url = _resolve_url(url)
    client = AdminClient(resolved_url, "unused")
    result = _run(client.health_check())
    click.echo(f"{result['status']} ({result['status_code']})")


@main.group()
def users():
    """Manage users on a deployed instance."""
    pass


@users.command("list")
@click.option("--url", default=None)
@click.option("--signing-key", default=None)
def users_list(url, signing_key):
    """List registered users."""
    result = _run(_client(url, signing_key).list_users())
    if not result:
        click.echo("No users.")
        return
    for user in result:
        status = " (revoked)" if user.get("revoke_after") else ""
        click.echo(f"  {user['email']}{status}")


@users.command("add")
@click.argument("email")
@click.option("--url", default=None)
@click.option("--signing-key", default=None)
def users_add(email, url, signing_key):
    """Register a user and get their token."""
    result = _run(_client(url, signing_key).register_user(email))
    click.echo(f"Registered: {result['email']}")
    click.echo(f"Token: {result['token']}")


@users.command("revoke")
@click.argument("email")
@click.option("--url", default=None)
@click.option("--signing-key", default=None)
def users_revoke(email, url, signing_key):
    """Revoke a user's access."""
    result = _run(_client(url, signing_key).revoke_user(email))
    click.echo(f"Revoked: {result['revoked']}")


@main.group()
def tokens():
    """Manage tokens on a deployed instance."""
    pass


@tokens.command("create")
@click.argument("email")
@click.option("--url", default=None)
@click.option("--signing-key", default=None)
def tokens_create(email, url, signing_key):
    """Create a new token for an existing user."""
    result = _run(_client(url, signing_key).create_token(email))
    click.echo(f"Token for {result['email']}: {result['token']}")


@main.command("admin-tools")
def admin_tools():
    """Run MCP admin tools server over stdio."""
    from mcp_app.admin_tools import mcp as admin_mcp
    admin_mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
