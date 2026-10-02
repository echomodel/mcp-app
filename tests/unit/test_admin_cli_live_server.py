"""Admin CLI commands against a real HTTP server on a local port.

In-process ASGI tests have no pooled TCP connections, so they cannot see
the failure these guard against: a command that makes several requests in
separate ``asyncio.run`` cycles reuses the adapter's httpx connection pool
across event loops and fails with ``RuntimeError: Event loop is closed``.
Here the app runs under uvicorn on 127.0.0.1 and the commands go through
the real ``RemoteAuthAdapter`` via Click's CliRunner.
"""

import json
import socket
import threading
import time

import pytest
import uvicorn
from click.testing import CliRunner
from pydantic import BaseModel

from mcp_app.app import App, SafeTool
from mcp_app.cli import create_admin_cli
from fixture_app import tools

APP_NAME = "live-admin-app"
SIGNING_KEY = "test-signing-key-" + "x" * 24  # 40 bytes, obviously fake
USER = "alice@example.com"


class Profile(BaseModel):
    token: str
    region: str = "us"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGNING_KEY", SIGNING_KEY)
    monkeypatch.setenv("APP_USERS_PATH", str(tmp_path / "users"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("MCP_APP_URL", raising=False)
    monkeypatch.delenv("MCP_APP_SIGNING_KEY", raising=False)
    # App() registers its profile model in mcp_app.context's module globals;
    # restore them afterwards so later tests see the state they expect.
    import mcp_app.context as ctx
    monkeypatch.setattr(ctx, "_profile_model", ctx._profile_model)
    monkeypatch.setattr(ctx, "_profile_expand", ctx._profile_expand)

    app = App(
        name=APP_NAME,
        tools_module=tools,
        profile_model=Profile,
        profile_expand=True,
        safe_tool=SafeTool(name="ping", arguments={}, description="returns pong"),
    )
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("test server did not start")
        time.sleep(0.05)

    url = f"http://127.0.0.1:{port}"
    admin = create_admin_cli(APP_NAME)
    runner = CliRunner()
    assert runner.invoke(admin, ["connect", url, "--signing-key", SIGNING_KEY]).exit_code == 0
    added = runner.invoke(admin, ["users", "add", USER, "--token", "t1"])
    assert added.exit_code == 0, added.output
    yield admin, runner
    server.should_exit = True
    thread.join(timeout=5)


def test_safe_tool_invoke_round_trips(live_server):
    admin, runner = live_server
    result = runner.invoke(admin, ["safe-tool", "--invoke", "--json"])
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["result"]["status_code"] == 200
    assert envelope["probed_as"] == USER


def test_update_profile_reads_then_writes_in_one_cycle(live_server):
    admin, runner = live_server
    result = runner.invoke(admin, ["users", "update-profile", USER, "region", "eu"])
    assert result.exit_code == 0, result.output
    shown = runner.invoke(admin, ["users", "get-profile", USER, "--json"])
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.output)["region"] == "eu"
