"""mcp-app CLI — remote admin and app CLI factories."""

import asyncio
import json
import os
from pathlib import Path

import click


# --- Config helpers ---

def _config_dir(app_name: str | None = None) -> Path:
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


def _client(url: str | None = None, signing_key: str | None = None, app_name: str | None = None):
    from mcp_app.admin_client import RemoteAuthAdapter
    return RemoteAuthAdapter(
        _resolve_url(url, app_name),
        _resolve_signing_key(signing_key, app_name),
    )


def _run(coro):
    return asyncio.run(coro)


def _connect_handler(target: str, signing_key: str | None, app_name: str | None):
    """Shared connect logic for both generic and per-app CLIs.

    When app_name is None (generic CLI), 'local' is not supported
    because the generic CLI doesn't know which app's filesystem store
    to target. Per-app CLIs pass their app_name to enable local mode.
    """
    if target == "local":
        if app_name is None:
            raise click.ClickException(
                "'connect local' requires the per-app admin CLI "
                "(e.g., my-app-admin connect local) because the "
                "generic CLI doesn't know which app's store to use."
            )
        _save_setup({"mode": "local"}, app_name=app_name)
        click.echo(f"Configured {app_name} for local access.")
    else:
        data = {"mode": "remote", "url": target}
        if signing_key:
            data["signing_key"] = signing_key
        _save_setup(data, app_name=app_name)
        label = app_name or "mcp-app"
        click.echo(f"Configured {label}: {target}")


def _print_request(invocation: dict):
    """Print a JSON-RPC invocation in HTTP-trace style with `>` prefixes.

    Emitting the request body before sending serves an operator-replay
    purpose — copy it into a debugger or another terminal without
    re-deriving the wire format.
    """
    headers = invocation.get("headers", {})
    click.echo(f"> {invocation.get('method', 'POST')} {invocation.get('url', '')}")
    for k, v in headers.items():
        click.echo(f"> {k}: {v}")
    body = invocation.get("body")
    if body is not None:
        for line in json.dumps(body, indent=2).splitlines():
            click.echo(f"> {line}")


def _print_response(status: int, body: dict):
    click.echo(f"< {status}")
    for line in json.dumps(body, indent=2).splitlines():
        click.echo(f"< {line}")


def _coerce_arg_value(raw: str, schema: dict | None):
    """Coerce a `--arg k=v` raw string to the type indicated by the tool schema.

    Booleans, numbers, and ``null`` are converted when the schema says so.
    Anything unrecognized is passed through as a string. Complex shapes
    (objects, arrays) should use ``--json``; passing them via ``--arg``
    raises a clear error pointing at ``tools show``.
    """
    if not schema:
        return raw
    type_ = schema.get("type")
    if type_ == "boolean":
        if raw.lower() in {"true", "1", "yes"}:
            return True
        if raw.lower() in {"false", "0", "no"}:
            return False
        raise click.ClickException(
            f"Expected boolean, got {raw!r}. Use 'true' or 'false'."
        )
    if type_ == "integer":
        try:
            return int(raw)
        except ValueError:
            raise click.ClickException(f"Expected integer, got {raw!r}.")
    if type_ == "number":
        try:
            return float(raw)
        except ValueError:
            raise click.ClickException(f"Expected number, got {raw!r}.")
    if type_ == "null":
        return None
    if type_ in {"object", "array"}:
        raise click.ClickException(
            f"Argument expects {type_}; --arg only takes scalars. "
            f"Use --body to pass a full arguments object."
        )
    return raw


def _parse_args_pairs(arg_pairs: tuple[str, ...], input_schema: dict | None) -> dict:
    """Turn ``--arg k=v --arg k2=v2`` into a dict, coerced via the schema."""
    if not arg_pairs:
        return {}
    properties = (input_schema or {}).get("properties", {})
    result = {}
    for pair in arg_pairs:
        if "=" not in pair:
            raise click.ClickException(
                f"--arg must be 'key=value', got: {pair!r}"
            )
        key, _, value = pair.partition("=")
        result[key] = _coerce_arg_value(value, properties.get(key))
    return result


def _parse_json_arg(raw: str) -> dict:
    """Parse a literal JSON object or ``@path`` reference."""
    if raw.startswith("@"):
        path = Path(raw[1:])
        if not path.exists():
            raise click.ClickException(f"JSON file not found: {path}")
        return json.loads(path.read_text())
    return json.loads(raw)


def _print_safe_tool_envelope(envelope: dict):
    """Render the safe-tool envelope as human-readable text."""
    click.echo(f"schema_version: {envelope.get('schema_version', '?')}")
    if not envelope.get("supported"):
        click.echo("Safe tool: not declared")
        hint = envelope.get("hint")
        if hint:
            click.echo(f"  {hint}")
        return
    tool = envelope.get("tool", {})
    click.echo(f"Safe tool: {tool.get('name', '?')}")
    desc = tool.get("description")
    if desc:
        click.echo(f"  {desc}")
    args = tool.get("arguments", {})
    click.echo(f"  arguments: {json.dumps(args)}")
    invocation = envelope.get("invocation")
    if invocation:
        click.echo("")
        click.echo("Invocation:")
        _print_request(invocation)
    result = envelope.get("result")
    if result is not None:
        click.echo("")
        click.echo("Response:")
        _print_response(result.get("status_code", 0), result.get("body", {}))


def _render_tool_show(tool: dict, app_name_hint: str) -> None:
    """Render `tools show <name>` output: description, parameters, example."""
    name = tool["name"]
    description = tool.get("description") or ""
    schema = tool.get("inputSchema") or {}
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    click.echo(name)
    if description:
        for line in description.splitlines():
            click.echo(f"  {line}")
    click.echo("")
    if not properties:
        click.echo("  Arguments: (none)")
    else:
        click.echo("  Arguments:")
        for pname, pinfo in properties.items():
            ptype = pinfo.get("type", "any")
            req = "required" if pname in required else "optional"
            pdesc = pinfo.get("description", "")
            line = f"    {pname}  ({ptype}, {req})"
            if pdesc:
                line += f"  {pdesc}"
            click.echo(line)
    click.echo("")
    click.echo("  Example invocation:")
    parts = [f"{app_name_hint} tools call {name}"]
    for pname in properties:
        prefix = "" if pname in required else "[optional] "
        parts.append(f"{prefix}--arg {pname}=<value>")
    click.echo("    " + " \\\n      ".join(parts))


def _print_probe(result: dict):
    """Render probe result as human-readable text."""
    click.echo(f"URL: {result['url']}")
    health = result.get("health", {})
    click.echo(f"Health: {health.get('status', 'unknown')}")

    mcp = result.get("mcp")
    if mcp is None:
        click.echo("MCP: not probed")
    elif mcp.get("status") == "ok":
        click.echo(f"MCP: ok (probed as {mcp.get('probed_as')})")
    elif mcp.get("status") == "skipped":
        click.echo(f"MCP: skipped — {mcp.get('reason')}")
    else:
        click.echo(f"MCP: {mcp.get('status')} — {mcp.get('error', '')}")

    tools = result.get("tools")
    if tools is not None:
        click.echo(f"Tools ({len(tools)}):")
        for t in tools:
            click.echo(f"  {t}")


# --- Profile helpers ---

def _parse_profile_value(value: str) -> dict:
    if value.startswith("@"):
        path = Path(value[1:])
        if not path.exists():
            raise click.ClickException(f"Profile file not found: {path}")
        return json.loads(path.read_text())
    return json.loads(value)


def _collect_profile_from_flags(ctx: click.Context) -> dict | None:
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
    from mcp_app.context import get_profile_model
    model = get_profile_model()
    if model and data:
        obj = model(**data)
        return obj.model_dump()
    return data


def _profile_help_text() -> str:
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


# --- Main CLI (remote admin only) ---

@click.group()
def main():
    """mcp-app — remote admin for deployed instances."""
    pass


@main.command()
@click.argument("target")
@click.option("--signing-key", default=None, help="Signing key for admin auth.")
def connect(target, signing_key):
    """Configure connection to a deployed instance.

    \b
    Examples:
      mcp-app connect https://my-app.run.app --signing-key xxx
    """
    _connect_handler(target, signing_key, app_name=None)


@main.command()
def health():
    """Check health of a deployed instance."""
    from mcp_app.admin_client import RemoteAuthAdapter
    resolved_url = _resolve_url()
    client = RemoteAuthAdapter(resolved_url, "unused")
    result = _run(client.health_check())
    click.echo(f"{result['status']} ({result['status_code']})")


@main.group()
def users():
    """Manage users on a deployed instance."""
    pass


@users.command("list")
def users_list():
    """List registered users."""
    result = _run(_client().list())
    if not result:
        click.echo("No users.")
        return
    for user in result:
        status = " (revoked)" if user.revoke_after else ""
        click.echo(f"  {user.email}{status}")


@users.command("add")
@click.argument("email")
@click.option("--profile", "profile_str", default=None,
              help="Profile data as JSON string or @file.")
def users_add(email, profile_str):
    """Register a user and get their token."""
    from datetime import datetime, timezone
    from mcp_app.models import UserAuthRecord

    profile = None
    if profile_str:
        profile = _parse_profile_value(profile_str)
        profile = _validate_profile(profile)

    result = _run(_client().save(
        UserAuthRecord(email=email, created=datetime.now(timezone.utc)),
        profile=profile,
    ))
    click.echo(f"Registered: {result['email']}")
    if "token" in result:
        click.echo(f"Token: {result['token']}")


@users.command("update-profile")
@click.argument("email")
@click.argument("key")
@click.argument("value")
def users_update_profile(email, key, value):
    """Update a single profile field for a user."""
    result = _run(_client().update_profile(email, {key: value}))
    click.echo(f"Updated {key} for {email}")


@users.command("get-profile")
@click.argument("email")
@click.option("--json", "as_json", is_flag=True, help="JSON output.")
def users_get_profile(email, as_json):
    """Read a user's profile."""
    record = _run(_client().get_full(email))
    if not record:
        raise click.ClickException(f"User not found: {email}")
    profile = record.profile
    if as_json:
        click.echo(json.dumps(profile, indent=2))
    elif profile is None:
        click.echo("(no profile)")
    else:
        for k, v in profile.items():
            click.echo(f"  {k}: {v}")


@users.command("revoke")
@click.argument("email")
def users_revoke(email):
    """Revoke a user's access."""
    _run(_client().delete(email))
    click.echo(f"Revoked: {email}")


@main.group()
def tokens():
    """Manage tokens on a deployed instance."""
    pass


@tokens.command("create")
@click.argument("email")
def tokens_create(email):
    """Create a new token for an existing user."""
    result = _run(_client().create_token(email))
    click.echo(f"Token for {result['email']}: {result['token']}")


@main.command()
@click.option("--user", default=None, help="User email for MCP probe. Auto-picks first user if omitted.")
@click.option("--json", "as_json", is_flag=True, help="JSON output.")
def probe(user, as_json):
    """Probe a deployed instance: health + MCP tools round-trip."""
    result = _run(_client().probe(user_email=user))
    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        _print_probe(result)


@main.command()
@click.argument("name")
@click.option("--user", default=None, help="Mint a fresh token for this user. Otherwise uses a placeholder.")
@click.option("--client", "clients", multiple=True, type=click.Choice(["claude", "gemini", "claude.ai"]),
              help="Limit to specific client(s).")
@click.option("--scope", "scopes", multiple=True, type=click.Choice(["user", "project"]),
              help="Limit to specific scope(s).")
@click.option("--detect", is_flag=True, help="Check if already registered in each client.")
@click.option("--json", "as_json", is_flag=True, help="JSON output.")
def register(name, user, clients, scopes, detect, as_json):
    """Generate MCP client registration commands for a deployed instance."""
    from mcp_app.registration import generate_registrations, format_registrations

    resolved_url = _resolve_url()
    token = None
    if user:
        result = _run(_client().create_token(user))
        token = result["token"]

    reg = generate_registrations(
        name=name,
        url=resolved_url,
        token=token,
        clients=list(clients) or None,
        scopes=list(scopes) or None,
        detect_registered=detect,
    )
    if as_json:
        click.echo(json.dumps(reg, indent=2))
    else:
        click.echo(format_registrations(reg))


@main.command("admin-tools")
def admin_tools():
    """Run MCP admin tools server over stdio."""
    from mcp_app.admin_tools import mcp as admin_mcp
    admin_mcp.run(transport="stdio")


# --- App CLI factories ---

def _get_auth_store(app_name: str):
    """Get the auth store based on connect config — local or remote."""
    cfg = _load_setup(app_name)
    if not cfg:
        raise click.ClickException(
            f"Not configured. Run:\n"
            f"  {app_name}-admin connect local\n"
            f"  {app_name}-admin connect <url> --signing-key xxx"
        )
    if cfg.get("mode") == "local":
        from mcp_app.data_store import FileSystemUserDataStore
        from mcp_app.bridge import DataStoreAuthAdapter
        return DataStoreAuthAdapter(FileSystemUserDataStore(app_name=app_name))
    else:
        from mcp_app.admin_client import RemoteAuthAdapter
        return RemoteAuthAdapter(
            _resolve_url(None, app_name),
            _resolve_signing_key(None, app_name),
        )


def _require_remote_adapter(app_name: str | None):
    """Return a RemoteAuthAdapter for the configured connection.

    Raises ClickException with actionable hints when the connection is
    local-only or not configured.
    """
    from mcp_app.admin_client import RemoteAuthAdapter
    cfg = _load_setup(app_name)
    if cfg.get("mode") == "local":
        raise click.ClickException(
            "This command requires a remote connection. "
            "Run 'connect <url> --signing-key <key>'."
        )
    return RemoteAuthAdapter(
        _resolve_url(None, app_name),
        _resolve_signing_key(None, app_name),
    )


def _safe_tool_command(invoke, as_json, user, app_name: str | None):
    """Shared body for the `safe-tool` command on both CLIs.

    The endpoint carries metadata only — when ``--invoke`` is passed
    the CLI does the MCP handshake itself (avoids duplicating MCP
    transport logic on the server). The JSON-RPC request body is
    printed before sending so an operator can copy and replay it
    manually in a debugger or another terminal, against a different
    bearer token, etc.
    """
    adapter = _require_remote_adapter(app_name)
    envelope = _run(adapter.get_safe_tool())

    if invoke:
        if not envelope.get("supported"):
            if as_json:
                click.echo(json.dumps(envelope, indent=2))
            else:
                _print_safe_tool_envelope(envelope)
            raise click.ClickException(
                "Cannot invoke — no safe tool declared by this deployment."
            )
        tool = envelope["tool"]
        result = _run(adapter.call_tool(tool["name"], tool.get("arguments") or {}, user_email=user))
        envelope["invocation"] = result["invocation"]
        envelope["result"] = result["result"]
        envelope["probed_as"] = result["probed_as"]

    if as_json:
        click.echo(json.dumps(envelope, indent=2))
    else:
        _print_safe_tool_envelope(envelope)


def _tools_list_command(as_json, user, app_name: str | None):
    """Shared body for `tools list`."""
    adapter = _require_remote_adapter(app_name)
    tools, probed_as = _run(adapter.list_tools(user_email=user))
    if as_json:
        click.echo(json.dumps({"tools": tools, "probed_as": probed_as}, indent=2))
        return
    if not tools:
        click.echo("(no tools)")
        return
    name_w = max(len(t["name"]) for t in tools)
    for t in tools:
        desc = (t.get("description") or "").splitlines()[0] if t.get("description") else ""
        click.echo(f"  {t['name']:<{name_w}}  {desc}")
    cmd_hint = f"{app_name}-admin" if app_name else "mcp-app"
    click.echo("")
    click.echo(f"({len(tools)} tools — run `{cmd_hint} tools show <name>` for schema)")


def _tools_show_command(name, as_json, user, app_name: str | None):
    """Shared body for `tools show <name>`."""
    adapter = _require_remote_adapter(app_name)
    tools, _ = _run(adapter.list_tools(user_email=user))
    matches = [t for t in tools if t["name"] == name]
    if not matches:
        cmd_hint = f"{app_name}-admin" if app_name else "mcp-app"
        raise click.ClickException(
            f"Unknown tool: {name}. Run `{cmd_hint} tools list` to see all tools."
        )
    tool = matches[0]
    if as_json:
        click.echo(json.dumps(tool, indent=2))
        return
    cmd_hint = f"{app_name}-admin" if app_name else "mcp-app"
    _render_tool_show(tool, cmd_hint)


def _tools_call_command(name, arg_pairs, json_body, as_json, user, app_name: str | None):
    """Shared body for `tools call <name>`."""
    adapter = _require_remote_adapter(app_name)

    if json_body:
        arguments = _parse_json_arg(json_body)
        if not isinstance(arguments, dict):
            raise click.ClickException(
                "--json must be a JSON object (not array/scalar)."
            )
    else:
        tools, _ = _run(adapter.list_tools(user_email=user))
        matches = [t for t in tools if t["name"] == name]
        if not matches:
            cmd_hint = f"{app_name}-admin" if app_name else "mcp-app"
            raise click.ClickException(
                f"Unknown tool: {name}. Run `{cmd_hint} tools list` to see all tools."
            )
        arguments = _parse_args_pairs(arg_pairs, matches[0].get("inputSchema"))

    result = _run(adapter.call_tool(name, arguments, user_email=user))
    if as_json:
        click.echo(json.dumps(result, indent=2))
        return
    _print_request(result["invocation"])
    click.echo("")
    _print_response(result["result"]["status_code"], result["result"]["body"])


# Note: the `tools` subcommand group is intentionally scoped to mcp-app
# deployments. Targeting non-mcp-app servers is explicitly out of scope —
# a generic MCP client is a separate product. Reusing the admin CLI here
# saves the operator from re-doing connect/auth/handshake setup that
# `connect` already established.
def _add_safe_tool_command(cli: click.Group, app_name: str | None):
    @cli.command("safe-tool")
    @click.option("--invoke", is_flag=True,
                  help="Invoke the declared safe tool end-to-end.")
    @click.option("--user", default=None,
                  help="Mint a token for this user. Otherwise uses first registered user.")
    @click.option("--json", "as_json", is_flag=True,
                  help="Structured JSON envelope output for agents.")
    def safe_tool(invoke, user, as_json):
        """Show or invoke this deployment's declared safe tool.

        Without --invoke: shows the declaration only (cheap, no
        upstream call). With --invoke: performs the full MCP
        handshake using a freshly minted user token. Either way,
        --json emits the canonical agent-consumption envelope.
        """
        _safe_tool_command(invoke, as_json, user, app_name)


def _add_tools_group(cli: click.Group, app_name: str | None):
    @cli.group()
    def tools():
        """Discover and invoke MCP tools on the deployment."""
        pass

    @tools.command("list")
    @click.option("--user", default=None,
                  help="Mint a token for this user. Otherwise uses first registered user.")
    @click.option("--json", "as_json", is_flag=True, help="JSON output.")
    def tools_list(user, as_json):
        """Enumerate the tools the deployment exposes."""
        _tools_list_command(as_json, user, app_name)

    @tools.command("show")
    @click.argument("name")
    @click.option("--user", default=None,
                  help="Mint a token for this user. Otherwise uses first registered user.")
    @click.option("--json", "as_json", is_flag=True, help="JSON output of the raw tool schema.")
    def tools_show(name, user, as_json):
        """Show schema and example invocation for a named tool."""
        _tools_show_command(name, as_json, user, app_name)

    # `--json` here is the output-format flag (consistent with the rest
    # of the admin CLI); the JSON body literal goes through `--body` to
    # avoid the value-vs-flag ambiguity that one shared `--json` would
    # introduce. `--body` accepts either a JSON object or `@path`.
    @tools.command("call")
    @click.argument("name")
    @click.option("--arg", "arg_pairs", multiple=True,
                  help="Argument as key=value. Repeatable. Scalars only — use --body for objects.")
    @click.option("--body", "json_body", default=None,
                  help="Full arguments JSON object, or @path to a file.")
    @click.option("--user", default=None,
                  help="Mint a token for this user. Otherwise uses first registered user.")
    @click.option("--json", "as_json", is_flag=True, help="JSON envelope output.")
    def tools_call(name, arg_pairs, json_body, user, as_json):
        """Invoke a tool with the given arguments and print the response."""
        _tools_call_command(name, arg_pairs, json_body, as_json, user, app_name)


def create_mcp_cli(app) -> click.Group:
    """Create the MCP server CLI for an app (serve, stdio).

    The subcommands are thin wrappers over ``app.serve()`` and
    ``app.stdio(user)``; the same methods can be called directly
    from Python.
    """

    @click.group()
    def cli():
        """MCP server commands."""
        pass

    @cli.command()
    @click.option("--host", default="0.0.0.0")
    @click.option("--port", default=8080, type=int)
    def serve(host, port):
        """Run MCP server over HTTP."""
        app.serve(host=host, port=port)

    @cli.command()
    @click.option("--user", required=True, help="User identity for this session.")
    def stdio(user):
        """Run MCP server over stdio."""
        app.stdio(user)

    return cli


def create_admin_cli(app_name: str) -> click.Group:
    """Create the admin CLI for an app (connect, users, tokens, health).

    Dynamically generates typed CLI flags from the registered profile
    model (if expand=True) or accepts --profile for object input.
    All user operations go through UserAuthStore — local or remote
    determined by connect config.

    Usage:
        admin_cli = create_admin_cli("my-app")
    """
    from mcp_app.context import get_profile_model, get_profile_expand

    @click.group()
    def cli():
        """Admin commands — user management and health."""
        pass

    @cli.command()
    @click.argument("target")
    @click.option("--signing-key", default=None)
    def connect(target, signing_key):
        """Configure admin target. Use 'local' or a URL.

        \b
        Examples:
          connect local
          connect https://my-app.run.app --signing-key xxx
        """
        _connect_handler(target, signing_key, app_name=app_name)

    @cli.command()
    def health():
        """Check health of the configured instance."""
        cfg = _load_setup(app_name)
        if cfg.get("mode") == "local":
            click.echo("Local mode — no remote health check.")
            return
        from mcp_app.admin_client import RemoteAuthAdapter
        adapter = RemoteAuthAdapter(
            _resolve_url(None, app_name),
            _resolve_signing_key(None, app_name),
        )
        result = _run(adapter.health_check())
        click.echo(f"{result['status']} ({result['status_code']})")

    @cli.group()
    def users():
        """Manage users."""
        pass

    @users.command("list")
    def users_list():
        """List registered users."""
        store = _get_auth_store(app_name)
        result = _run(store.list())
        if not result:
            click.echo("No users.")
            return
        for user in result:
            status = " (revoked)" if user.revoke_after else ""
            click.echo(f"  {user.email}{status}")

    # Build users add dynamically from profile model
    model = get_profile_model()
    expand = get_profile_expand()

    add_params = [click.Argument(["email"])]

    if model and expand:
        for field_name, field_info in model.model_fields.items():
            required = field_info.is_required()
            flag_name = f"--{field_name.replace('_', '-')}"
            add_params.append(click.Option(
                [flag_name],
                required=required,
                help=field_info.description or "",
            ))
    else:
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
        """Register a new user. Fails if the user already exists."""
        from datetime import datetime, timezone
        from mcp_app.models import UserAuthRecord

        email = kwargs.pop("email")

        store = _get_auth_store(app_name)
        existing = _run(store.get(email))
        if existing:
            raise click.ClickException(
                f"User already exists: {email}. "
                f"Use 'users update-profile' to change profile fields."
            )

        profile = None
        if model and expand:
            data = {k: v for k, v in kwargs.items() if v is not None}
            if data:
                profile = _validate_profile(data)
        elif "profile" in kwargs and kwargs["profile"]:
            profile = _parse_profile_value(kwargs["profile"])
            if profile:
                profile = _validate_profile(profile)

        store = _get_auth_store(app_name)
        result = _run(store.save(
            UserAuthRecord(email=email, created=datetime.now(timezone.utc)),
            profile=profile,
        ))
        click.echo(f"Added: {result['email']}")
        if "token" in result:
            click.echo(f"Token: {result['token']}")

    # Build users update-profile dynamically from profile model
    if model and expand:
        field_names = list(model.model_fields.keys())
        field_help = {}
        for fname, finfo in model.model_fields.items():
            desc = finfo.description or ""
            type_name = finfo.annotation.__name__ if hasattr(finfo.annotation, '__name__') else str(finfo.annotation)
            field_help[fname] = f"{type_name}: {desc}" if desc else type_name

        help_lines = ["Update a single profile field for an existing user."]
        help_lines.append("")
        help_lines.append("Valid keys:")
        for fname in field_names:
            help_lines.append(f"  {fname} — {field_help[fname]}")

        @users.command("update-profile")
        @click.argument("email")
        @click.argument("key", type=click.Choice(field_names))
        @click.argument("value")
        def users_update_profile(email, key, value):
            __doc__ = "\n".join(help_lines)
            store = _get_auth_store(app_name)
            existing = _run(store.get_full(email))
            if not existing:
                raise click.ClickException(f"User not found: {email}")
            # Validate against the merged post-update state so models with
            # multiple required fields (or cross-field validators) accept
            # partial patches against an already-complete profile.
            existing_profile = existing.profile or {}
            merged = {**existing_profile, key: value}
            _validate_profile(merged)
            _run(store.update_profile(email, {key: value}))
            click.echo(f"Updated {key} for {email}")

        users_update_profile.help = "\n".join(help_lines)
    else:
        @users.command("update-profile")
        @click.argument("email")
        @click.argument("data")
        def users_update_profile(email, data):
            """Merge profile fields for an existing user.

            DATA is a JSON string or @file with fields to merge.
            """
            store = _get_auth_store(app_name)
            existing = _run(store.get_full(email))
            if not existing:
                raise click.ClickException(f"User not found: {email}")
            updates = _parse_profile_value(data)
            if model:
                existing_profile = existing.profile or {}
                merged = {**existing_profile, **updates}
                _validate_profile(merged)
            _run(store.update_profile(email, updates))
            click.echo(f"Updated profile for {email}")

    @users.command("get-profile")
    @click.argument("email")
    @click.option("--json", "as_json", is_flag=True, help="JSON output.")
    def users_get_profile(email, as_json):
        """Read a user's profile."""
        store = _get_auth_store(app_name)
        record = _run(store.get_full(email))
        if not record:
            raise click.ClickException(f"User not found: {email}")
        profile = record.profile
        if as_json:
            click.echo(json.dumps(profile, indent=2))
            return
        if profile is None:
            click.echo("(no profile)")
            return
        if model:
            for fname in model.model_fields:
                if fname in profile:
                    click.echo(f"  {fname}: {profile[fname]}")
                else:
                    click.echo(f"  {fname}: (missing)")
            extras = [k for k in profile if k not in model.model_fields]
            for k in extras:
                click.echo(f"  {k}: {profile[k]}  (not in profile model)")
        else:
            for k, v in profile.items():
                click.echo(f"  {k}: {v}")

    @users.command("revoke")
    @click.argument("email")
    def users_revoke(email):
        """Revoke a user's access."""
        store = _get_auth_store(app_name)
        _run(store.delete(email))
        click.echo(f"Revoked: {email}")

    @cli.command()
    @click.option("--user", default=None, help="User email for MCP probe. Auto-picks first user if omitted.")
    @click.option("--json", "as_json", is_flag=True, help="JSON output.")
    def probe(user, as_json):
        """Probe the configured instance: health + MCP tools round-trip."""
        cfg = _load_setup(app_name)
        if cfg.get("mode") == "local":
            click.echo("Local mode — probe is for remote instances only.")
            return
        from mcp_app.admin_client import RemoteAuthAdapter
        adapter = RemoteAuthAdapter(
            _resolve_url(None, app_name),
            _resolve_signing_key(None, app_name),
        )
        result = _run(adapter.probe(user_email=user))
        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            _print_probe(result)

    @cli.command()
    @click.option("--user", default=None, help="Mint a fresh token for this user.")
    @click.option("--client", "clients", multiple=True,
                  type=click.Choice(["claude", "gemini", "claude.ai"]),
                  help="Limit to specific client(s).")
    @click.option("--scope", "scopes", multiple=True,
                  type=click.Choice(["user", "project"]),
                  help="Limit to specific scope(s).")
    @click.option("--detect", is_flag=True, help="Check if already registered in each client.")
    @click.option("--json", "as_json", is_flag=True, help="JSON output.")
    def register(user, clients, scopes, detect, as_json):
        """Generate MCP client registration commands for the configured instance."""
        from mcp_app.registration import generate_registrations, format_registrations

        cfg = _load_setup(app_name)
        if cfg.get("mode") == "local":
            click.echo("Local mode — register is for remote instances only.")
            return
        resolved_url = _resolve_url(None, app_name)
        token = None
        if user:
            store = _get_auth_store(app_name)
            result = _run(store.create_token(user))
            token = result["token"]

        reg = generate_registrations(
            name=app_name,
            url=resolved_url,
            token=token,
            clients=list(clients) or None,
            scopes=list(scopes) or None,
            detect_registered=detect,
        )
        if as_json:
            click.echo(json.dumps(reg, indent=2))
        else:
            click.echo(format_registrations(reg))

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
            click.echo("Tokens are for remote instances only.")
            return
        from mcp_app.admin_client import RemoteAuthAdapter
        adapter = RemoteAuthAdapter(
            _resolve_url(None, app_name),
            _resolve_signing_key(None, app_name),
        )
        result = _run(adapter.create_token(email))
        click.echo(f"Token for {result['email']}: {result['token']}")

    _add_safe_tool_command(cli, app_name=app_name)
    _add_tools_group(cli, app_name=app_name)

    return cli


# Mount the same safe-tool / tools commands on the generic `mcp-app` CLI.
# Done after definition of both the group and the helpers so name resolution
# works at module-import time.
_add_safe_tool_command(main, app_name=None)
_add_tools_group(main, app_name=None)


if __name__ == "__main__":
    main()
