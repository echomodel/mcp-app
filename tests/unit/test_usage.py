"""Usage accounting and the admin-only usage_report tool.

Counters are recorded per tool call, flushed to the data volume, and
summed into a weekly report; the report tool is hidden from and blocked
for non-administrators over HTTP.
"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from mcp_app.app import App
from mcp_app.bridge import DataStoreAuthAdapter
from mcp_app.data_store import FileSystemUserDataStore
from mcp_app.models import UserAuthRecord
from mcp_app.testing.fixtures import mcp_running
from mcp_app.testing.issuer import TestIssuer
from mcp_app.usage import (
    UsageRecorder,
    build_report,
    mask_email,
    read_usage,
    week_window,
)

from .conftest import OPERATOR

BASE = "https://mcp.test"
AUD = "https://mcp.test/"
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _rpc(method, params=None, id=1):
    body = {"jsonrpc": "2.0", "method": method, "id": id}
    if params is not None:
        body["params"] = params
    return body


# -- pure functions ---------------------------------------------------------


@pytest.mark.parametrize("email,masked", [
    ("alice@example.com", "al*****@e***.com"),
    ("bob@example.org", "bo*****@e***.org"),
    ("x@y.co.uk", "x*****@y***.uk"),
    ("nodomain", "no*****"),
])
def test_mask_email_keeps_two_letters_and_the_tld(email, masked):
    assert mask_email(email) == masked


def test_week_window_current_runs_monday_through_today():
    wed = date(2026, 10, 21)  # a Wednesday
    assert week_window("current", wed) == (date(2026, 10, 19), wed)


def test_week_window_prior_is_the_previous_full_week():
    wed = date(2026, 10, 21)
    assert week_window("prior", wed) == (date(2026, 10, 12), date(2026, 10, 18))


def test_week_window_rejects_other_values():
    with pytest.raises(ValueError):
        week_window("last-month")


def test_recorder_flushes_per_instance_files_and_read_usage_sums_them(tmp_path):
    root = tmp_path / "usage"
    a, b = UsageRecorder(root), UsageRecorder(root)
    a.record("Alice@example.com", "greet", True)
    a.record("alice@example.com", "greet", False)
    b.record("alice@example.com", "ping", True)
    b.record("bob@example.com", "greet", True)
    a.flush(); b.flush()
    today = datetime.now(timezone.utc).date()
    files = list((root / today.isoformat()).glob("*.json"))
    assert len(files) == 2, "one file per process, never a shared object"
    usage = read_usage(root, today, today)
    assert usage["alice@example.com"]["greet"] == {"ok": 1, "error": 1}
    assert usage["alice@example.com"]["ping"] == {"ok": 1, "error": 0}
    assert usage["bob@example.com"]["greet"] == {"ok": 1, "error": 0}


def test_recorder_without_root_records_nothing():
    r = UsageRecorder(None)
    r.record("a@example.com", "greet", True)
    r.flush()
    assert not r.enabled


def test_build_report_counts_users_calls_and_masks_emails():
    start, end = date(2026, 10, 19), date(2026, 10, 25)
    usage = {
        "alice@example.com": {"greet": {"ok": 3, "error": 1}, "ping": {"ok": 2, "error": 0}},
        "bob@example.com": {"greet": {"ok": 1, "error": 0}},
    }
    created = {
        "alice@example.com": datetime(2026, 10, 1, tzinfo=timezone.utc),
        "bob@example.com": datetime(2026, 10, 20, 12, tzinfo=timezone.utc),
        "carol@example.com": datetime(2026, 10, 22, tzinfo=timezone.utc),
    }
    report = build_report(usage, week="current", start=start, end=end, total_users=3, created=created)
    assert report["users"] == {"total": 3, "new": 2, "active": 2}
    assert report["tool_calls"]["total"] == 7
    assert report["tool_calls"]["errors"] == 1
    assert report["tool_calls"]["by_tool"] == {"greet": 5, "ping": 2}
    top = report["top_users"]
    assert [u["user"] for u in top] == ["al*****@e***.com", "bo*****@e***.com"]
    assert top[0]["calls"] == 6 and top[0]["tools_used"] == 2
    assert "alice" not in json.dumps(report)


# -- over HTTP --------------------------------------------------------------


@pytest.fixture(scope="module")
def mcp_issuer():
    return TestIssuer(audience=AUD)


@pytest.fixture
def app(auth_env, mcp_issuer):
    from fixture_app import tools

    return App(name="usage-test", tools_module=tools, auth=mcp_issuer.config)


@pytest.fixture
def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)


def _bearer(token):
    return {**MCP_HEADERS, "Authorization": f"Bearer {token}"}


async def _register(email):
    store = FileSystemUserDataStore(app_name="usage-test")
    await DataStoreAuthAdapter(store).save(
        UserAuthRecord(email=email, created=datetime.now(timezone.utc))
    )


@pytest.mark.asyncio
async def test_usage_report_is_listed_only_for_admins(app, client, mcp_issuer):
    await _register("alice@example.com")
    async with mcp_running(app, client):
        for_admin = await client.post("/", json=_rpc("tools/list"), headers=_bearer(mcp_issuer.token(OPERATOR)))
        for_alice = await client.post("/", json=_rpc("tools/list"), headers=_bearer(mcp_issuer.token("alice@example.com")))
    admin_names = {t["name"] for t in for_admin.json()["result"]["tools"]}
    alice_names = {t["name"] for t in for_alice.json()["result"]["tools"]}
    assert "usage_report" in admin_names
    assert "usage_report" not in alice_names
    assert {"ping", "greet"} <= alice_names, "ordinary tools are unaffected"


@pytest.mark.asyncio
async def test_usage_report_is_blocked_for_non_admins_even_when_called(app, client, mcp_issuer):
    await _register("alice@example.com")
    async with mcp_running(app, client):
        resp = await client.post(
            "/", json=_rpc("tools/call", {"name": "usage_report", "arguments": {}}),
            headers=_bearer(mcp_issuer.token("alice@example.com")),
        )
    body = resp.json()
    assert "error" in body or body["result"].get("isError"), body
    assert "Unknown tool" in json.dumps(body), "a hidden tool looks like an absent one"


@pytest.mark.asyncio
async def test_usage_report_counts_calls_made_this_week(app, client, mcp_issuer):
    await _register("alice@example.com")
    alice = _bearer(mcp_issuer.token("alice@example.com"))
    async with mcp_running(app, client):
        for i in range(3):
            r = await client.post("/", json=_rpc("tools/call", {"name": "greet", "arguments": {"name": "x"}}, i + 2), headers=alice)
            assert r.status_code == 200, r.text
        await client.post("/", json=_rpc("tools/call", {"name": "ping", "arguments": {}}, 9), headers=alice)
        resp = await client.post(
            "/", json=_rpc("tools/call", {"name": "usage_report", "arguments": {"week": "current"}}, 10),
            headers=_bearer(mcp_issuer.token(OPERATOR)),
        )
    assert resp.status_code == 200, resp.text
    result = resp.json()["result"]
    assert not result.get("isError"), result
    report = result.get("structuredContent") or json.loads(result["content"][0]["text"])
    assert report["tool_calls"]["total"] == 4
    assert report["tool_calls"]["by_tool"] == {"greet": 3, "ping": 1}
    assert report["users"]["active"] == 1
    assert report["users"]["total"] >= 1
    assert report["top_users"][0]["user"] == "al*****@e***.com"
    assert report["top_users"][0]["tools"] == {"greet": 3, "ping": 1}
    assert "alice@example.com" not in json.dumps(report)
    # The counters reached the volume beside the user directories.
    root = Path(FileSystemUserDataStore(app_name="usage-test").base).parent / "usage"
    assert any(root.rglob("*.json"))
