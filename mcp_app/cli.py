"""mcp-app CLI — serve, stdio, setup, and user management."""

import asyncio
import json
import os
from pathlib import Path

import click


# --- Config helpers ---

def _config_dir(app_name: str | None = None) -> Path:
    """XDG config path for an app or mcp-app generic."""
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    name = app_name or "mcp-app"
    return Path(xdg) / name


def _load_setup(app_name: str | None = None) -> dict:
    path = _config_dir(app_name) / "setup.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _save_setup(data: dict, app_name: str | None = None):
    path = _config_dir(app_name) / "setup.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _resolve_url(url: str | None, app_name: str | None = None) -> str:
    result = url or os.environ.get("MCP_APP_URL") or _load_setup(app_name).get("url")
    if not result:
        raise click.ClickException(
            "No base URL. Use --url, set MCP_APP_URL, or run: mcp-app setup <url>"
        )
    return result


def _resolve_signing_key(key: str | None, app_name: str | None = None) -> str:
    result = key or os.environ.get("MCP_APP_SIGNING_KEY") or _load_setup(app_name).get("signing_key")
    if not result:
        raise click.ClickException(
            "No signing key. Use --signing-key, set MCP_APP_SIGNING_KEY, or include in setup."
        )
    return result


def _client(url: str | None, signing_key: str | None, app_name: str | None = None):
    from mcp_app.admin_client import AdminClient
    return AdminClient(
        _resolve_url(url, app_name),
        _resolve_signing_key(signing_key, app_name),
    )


def _run(coro):
    return asyncio.run(coro)


# --- Profile helpers ---

def _parse_profile_value(value: str) -> dict:
    """Parse a profile value: JSON string or @file."""
    if value.startswith("@"):
        path = Path(value[1:])
        if not path.exists():
            raise click.ClickException(f"Profile file not found: {path}")
        return json.loads(path.read_text())
    return json.loads(value)


def _collect_profile_from_flags(ctx: click.Context) -> dict | None:
    """Collect profile data from dynamically generated flags."""
    from mcp_app.context import get_profile_model
    model = get_profile_model()
    if not model:
        return None
    data = {}
    for field_name in model.model_fields:
        value = ctx.params.get(field_name.replace("-", "_"))
        if value is not None:
            data[field_name] = value
    return data if data else None


def _validate_profile(data: dict) -> dict:
    """Validate profile data against the registered model."""
    from mcp_app.context import get_profile_model
    model = get_profile_model()
    if model and data:
        obj = model(**data)  # Pydantic validates
        return obj.model_dump()
    return data


def _profile_help_text() -> str:
    """Generate help text for profile fields from registered model."""
    from mcp_app.context import get_profile_model
    model = get_profile_model()
    if not model:
        return ""
    lines = ["Required fields:"]
    for name, field in model.model_fields.items():
        req = "required" if field.is_required() else "optional"
        desc = field.description or ""
        type_name = field.annotation.__name__ if hasattr(field.annotation, '__name__') else str(field.annotation)
        lines.append(f"  {name} ({type_name}, {req}) {desc}")
    return "\n".join(lines)


# --- Main CLI ---

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


@main.command()
@click.argument("app_path", required=False, default=None)
@click.option("--user", default=None, help="Override stdio.user from yaml.")
def stdio(app_path, user):
    """Run MCP server over stdio (local, single user).

    APP_PATH: Optional path to the directory containing mcp-app.yaml.
    Defaults to the current working directory.

    Reads mcp-app.yaml, discovers tools, wires the store, and runs
    FastMCP over stdin/stdout. No middleware, no admin endpoints.
    """
    from mcp_app.bootstrap import build_stdio
    from mcp_app.context import current_user, hydrate_profile
    from mcp_app.models import UserRecord

    config_path = Path(app_path) / "mcp-app.yaml" if app_path else None
    mcp, store, config = build_stdio(config_path)

    import mcp_app
    mcp_app._store = store

    # Resolve user identity: --user flag overrides yaml
    user_id = user or config.get("stdio", {}).get("user")
    if not user_id:
        raise click.ClickException(
            "No user specified. Use --user flag or configure stdio.user "
            "in mcp-app.yaml:\n\n  stdio:\n    user: \"local\"\n"
        )

    # Load full user record from store (auth + profile in one read)
    from mcp_app.bridge import DataStoreAuthAdapter
    adapter = DataStoreAuthAdapter(store)
    user_record = _run(adapter.get_full(user_id))
    if user_record:
        user_record.profile = hydrate_profile(user_record.profile)
    else:
        user_record = UserRecord(email=user_id)

    current_user.set(user_record)

    mcp.run(transport="stdio")


# --- Setup ---

@main.command()
@click.argument("url")
@click.option("--signing-key", default=None, help="Signing key for admin auth.")
def setup(url, signing_key):
    """Configure connection to a deployed instance.

    Saves the URL and signing key for subsequent user management commands.
    """
    data = _load_setup()
    data["url"] = url
    if signing_key:
        data["signing_key"] = signing_key
    _save_setup(data)
    click.echo(f"Configured: {url}")


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


# --- User management (remote) ---

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
@click.option("--profile", "profile_str", default=None,
              help="Profile data as JSON string or @file.")
@click.option("--url", default=None)
@click.option("--signing-key", default=None)
@click.pass_context
def users_add(ctx, email, profile_str, url, signing_key):
    """Register a user and get their token."""
    # Resolve profile from --profile flag or expanded flags
    profile = None
    if profile_str:
        profile = _parse_profile_value(profile_str)
    else:
        profile = _collect_profile_from_flags(ctx)

    if profile:
        profile = _validate_profile(profile)

    result = _run(_client(url, signing_key).register_user(email, profile))
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


# --- Token management ---

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


# --- App CLI factory ---

def create_app_cli(app_name: str) -> click.Group:
    """Create a CLI for a specific app.

    Returns a Click group with all mcp-app commands, configured for
    the given app name. The app's config is stored at
    ~/.config/{app_name}/setup.json and the store defaults to
    ~/.local/share/{app_name}/users/.

    The users add command dynamically generates flags from the
    registered profile model (if expand=True) or accepts --profile
    for object input.
    """
    from mcp_app.context import get_profile_model, get_profile_expand

    @click.group()
    def cli():
        pass

    # Serve and stdio use the app's bundled config
    @cli.command()
    @click.option("--host", default="0.0.0.0")
    @click.option("--port", default=8080, type=int)
    def serve(host, port):
        """Run MCP server over HTTP."""
        import uvicorn
        from mcp_app.bootstrap import build_app

        # Find config bundled with the installed package
        import importlib
        pkg = importlib.import_module(app_name.replace("-", "_"))
        config_path = Path(pkg.__file__).parent / "mcp-app.yaml"
        if not config_path.exists():
            config_path = None

        app, mcp, store, config = build_app(config_path)
        import mcp_app
        mcp_app._store = store
        uvicorn.run(app, host=host, port=port)

    @cli.command()
    @click.option("--user", default=None, help="User identity for this session.")
    def stdio(user):
        """Run MCP server over stdio."""
        from mcp_app.bootstrap import build_stdio
        from mcp_app.context import current_user, hydrate_profile
        from mcp_app.models import UserRecord

        import importlib
        pkg = importlib.import_module(app_name.replace("-", "_"))
        config_path = Path(pkg.__file__).parent / "mcp-app.yaml"
        if not config_path.exists():
            config_path = None

        mcp, store, config = build_stdio(config_path)
        import mcp_app
        mcp_app._store = store

        user_id = user or config.get("stdio", {}).get("user")
        if not user_id:
            raise click.ClickException(
                f"No user specified. Use --user flag or configure stdio.user "
                f"in mcp-app.yaml."
            )

        from mcp_app.bridge import DataStoreAuthAdapter
        adapter = DataStoreAuthAdapter(store)
        user_record = _run(adapter.get_full(user_id))
        if user_record:
            user_record.profile = hydrate_profile(user_record.profile)
        else:
            user_record = UserRecord(email=user_id)

        current_user.set(user_record)
        mcp.run(transport="stdio")

    # Setup
    @cli.command()
    @click.argument("url", required=False, default=None)
    @click.option("--signing-key", default=None)
    @click.option("--local", is_flag=True, help="Configure for local store access.")
    def setup(url, signing_key, local):
        """Configure connection to a deployed instance or local store."""
        if local:
            _save_setup({"mode": "local"}, app_name=app_name)
            click.echo(f"Configured {app_name} for local access.")
        elif url:
            data = {"mode": "remote", "url": url}
            if signing_key:
                data["signing_key"] = signing_key
            _save_setup(data, app_name=app_name)
            click.echo(f"Configured {app_name}: {url}")
        else:
            raise click.ClickException("Provide a URL or --local.")

    # Health
    @cli.command()
    def health():
        """Check health of the configured instance."""
        from mcp_app.admin_client import AdminClient
        cfg = _load_setup(app_name)
        if cfg.get("mode") == "local":
            click.echo("Local mode — no remote health check.")
            return
        resolved_url = _resolve_url(None, app_name)
        client = AdminClient(resolved_url, "unused")
        result = _run(client.health_check())
        click.echo(f"{result['status']} ({result['status_code']})")

    # Users group
    @cli.group()
    def users():
        """Manage users."""
        pass

    @users.command("list")
    def users_list():
        """List registered users."""
        cfg = _load_setup(app_name)
        if cfg.get("mode") == "local":
            from mcp_app.data_store import FileSystemUserDataStore
            store = FileSystemUserDataStore(app_name=app_name)
            user_list = store.list_users()
            if not user_list:
                click.echo("No users.")
                return
            for u in user_list:
                click.echo(f"  {u}")
        else:
            result = _run(_client(None, None, app_name).list_users())
            if not result:
                click.echo("No users.")
                return
            for user in result:
                status = " (revoked)" if user.get("revoke_after") else ""
                click.echo(f"  {user['email']}{status}")

    # Build the users add command dynamically based on profile model
    model = get_profile_model()
    expand = get_profile_expand()

    add_params = [click.Argument(["email"])]

    if model and expand:
        # Generate flags from Pydantic model fields
        for field_name, field_info in model.model_fields.items():
            required = field_info.is_required()
            flag_name = f"--{field_name.replace('_', '-')}"
            add_params.append(click.Option(
                [flag_name],
                required=required,
                help=field_info.description or "",
            ))
    else:
        # Accept profile as JSON or @file
        help_text = "Profile as JSON string or @file."
        if model:
            help_text += "\n" + _profile_help_text()
        add_params.append(click.Option(
            ["--profile"],
            default=None,
            help=help_text,
        ))

    @users.command("add", params=add_params)
    @click.pass_context
    def users_add(ctx, **kwargs):
        """Register a user."""
        email = kwargs.pop("email")

        # Resolve profile
        profile = None
        if model and expand:
            data = {k: v for k, v in kwargs.items() if v is not None
                    and k not in ("url", "signing_key")}
            if data:
                profile = _validate_profile(data)
        elif "profile" in kwargs and kwargs["profile"]:
            profile = _parse_profile_value(kwargs["profile"])
            if profile:
                profile = _validate_profile(profile)

        cfg = _load_setup(app_name)
        if cfg.get("mode") == "local":
            from datetime import datetime, timezone
            from mcp_app.data_store import FileSystemUserDataStore
            from mcp_app.bridge import DataStoreAuthAdapter
            from mcp_app.models import UserAuthRecord

            store = FileSystemUserDataStore(app_name=app_name)
            adapter = DataStoreAuthAdapter(store)
            _run(adapter.save(
                UserAuthRecord(email=email, created=datetime.now(timezone.utc)),
                profile=profile,
            ))
            click.echo(f"Added locally: {email}")
        else:
            result = _run(_client(None, None, app_name).register_user(email, profile))
            click.echo(f"Registered: {result['email']}")
            click.echo(f"Token: {result['token']}")

    @users.command("revoke")
    @click.argument("email")
    def users_revoke(email):
        """Revoke a user's access."""
        cfg = _load_setup(app_name)
        if cfg.get("mode") == "local":
            from mcp_app.data_store import FileSystemUserDataStore
            from mcp_app.bridge import DataStoreAuthAdapter
            store = FileSystemUserDataStore(app_name=app_name)
            adapter = DataStoreAuthAdapter(store)
            _run(adapter.delete(email))
            click.echo(f"Revoked locally: {email}")
        else:
            result = _run(_client(None, None, app_name).revoke_user(email))
            click.echo(f"Revoked: {result['revoked']}")

    # Tokens
    @cli.group()
    def tokens():
        """Manage tokens."""
        pass

    @tokens.command("create")
    @click.argument("email")
    def tokens_create(email):
        """Create a new token for an existing user."""
        cfg = _load_setup(app_name)
        if cfg.get("mode") == "local":
            click.echo("Tokens are for remote instances only. Local mode uses stdio.user.")
        else:
            result = _run(_client(None, None, app_name).create_token(email))
            click.echo(f"Token for {result['email']}: {result['token']}")

    return cli


if __name__ == "__main__":
    main()
