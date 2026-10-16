"""Client registration command generation for deployed mcp-app instances.

Produces the exact commands an operator (or agent) pastes into each MCP
client (Claude Code, Antigravity CLI `agy`) and the URL to add in Claude.ai,
for a given deployed service URL. No credential appears in any of them:
the client discovers the authorization server from the URL and runs the
sign-in itself.
"""

from __future__ import annotations

import shutil
import subprocess

CLIENTS = ("claude", "agy", "claude.ai")
SCOPES = ("user", "project")


def _claude_cmd(name: str, url: str, scope: str) -> str:
    return f"claude mcp add --transport http -s {scope} {name} {url}"


def _agy_cmd(name: str, url: str) -> str:
    # agy requires flags before <name>; http URLs set the server type.
    return f"agy mcp add {name} {url}"


def _is_registered(client: str, name: str, scope: str) -> bool | None:
    """Check whether the service is already registered at the given scope.

    Returns True/False on a successful check, or None if detection was not
    possible (CLI missing, errored, or the output could not be parsed).
    """
    try:
        if client == "claude":
            if not shutil.which("claude"):
                return None
            proc = subprocess.run(
                ["claude", "mcp", "list", "-s", scope],
                capture_output=True, text=True, timeout=5,
            )
        elif client == "agy":
            if not shutil.which("agy"):
                return None
            proc = subprocess.run(
                ["agy", "mcp", "list"],
                capture_output=True, text=True, timeout=5,
            )
        else:
            return None
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        return None
    return any(name in line.split() for line in proc.stdout.splitlines())


def generate_registrations(
    name: str,
    url: str,
    clients: list[str] | None = None,
    scopes: list[str] | None = None,
    detect_registered: bool = False,
) -> dict:
    """Produce ready-to-paste client registration commands.

    Args:
        name: MCP server name the client will know the service by.
        url: Deployed service base URL. Must end with '/'.
        clients: Subset of {"claude", "agy", "claude.ai"}. Default: all.
        scopes: Subset of {"user", "project"}. Default: all. Applies to
            claude only; agy has one user-level config and claude.ai is a
            URL form.
        detect_registered: If True, shell out to each CLI's list command to
            note whether the name is already registered at that scope.

    Returns:
        Dict with 'url', 'name', and an 'entries' list of
        {client, scope, command, registered} records.
    """
    if not url.endswith("/"):
        url = url + "/"
    clients = list(clients) if clients else list(CLIENTS)
    scopes = list(scopes) if scopes else list(SCOPES)
    entries = []

    for client in clients:
        if client == "claude.ai":
            entries.append({
                "client": "claude.ai",
                "scope": None,
                "command": url,
                "registered": None,
            })
            continue
        if client == "agy":
            entries.append({
                "client": "agy",
                "scope": None,
                "command": _agy_cmd(name, url),
                "registered": _is_registered("agy", name, "user") if detect_registered else None,
            })
            continue
        for scope in scopes:
            if client == "claude":
                cmd = _claude_cmd(name, url, scope)
            else:
                continue
            registered = (
                _is_registered(client, name, scope) if detect_registered else None
            )
            entries.append({
                "client": client,
                "scope": scope,
                "command": cmd,
                "registered": registered,
            })

    return {
        "url": url,
        "name": name,
        "entries": entries,
    }


def format_registrations(result: dict) -> str:
    """Render the output of generate_registrations() as human text."""
    lines = []
    for e in result["entries"]:
        client = e["client"]
        scope = e["scope"]
        reg = e["registered"]
        status = (
            "registered" if reg is True
            else "not registered" if reg is False
            else "status unknown"
        )
        if client == "claude.ai":
            label = f"{client} (manual: Settings > Connectors > Add custom connector)"
        elif scope is None:
            label = f"{client} (user config, {status})"
        else:
            label = f"{client} ({scope} scope, {status})"
        lines.append(f"{label}:")
        lines.append(f"  {e['command']}")
        lines.append("")
    lines.append("Each client signs the user in with the identity provider on first use.")
    return "\n".join(lines).rstrip() + "\n"
