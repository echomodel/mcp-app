"""The admin tools and the admission states they act on.

users_list / user_register / user_block are admin-only MCP tools; the
status on a user record (approved, pending, blocked) is what the identity
layer enforces, under either admission policy. Machine clients listed in
ADMIN_CLIENT_IDS are administrators without a record.
"""

import json
from datetime import datetime, timezone

import httpx
import pytest

from mcp_app.app import App
from mcp_app.auth import ADMISSION_OPEN, Admission, OAuthResourceServer
from mcp_app.bridge import DataStoreAuthAdapter
from mcp_app.data_store import FileSystemUserDataStore
from mcp_app.models import UserAuthRecord
from mcp_app.testing.fixtures import mcp_running
from mcp_app.testing.issuer import TestIssuer

from .conftest import OPERATOR

BASE = "https://mcp.test"
AUD = "https://mcp.test/"
MCP = {"Accept": "application/json, text/event-stream"}
TOOLS_LIST = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}


def _call(name, arguments=None, id=2):
    return {"jsonrpc": "2.0", "method": "tools/call", "id": id,
            "params": {"name": name, "arguments": arguments or {}}}


def _result(resp):
    body = resp.json()
    assert "error" not in body, body
    r = body["result"]
    assert not r.get("isError"), r
    return r.get("structuredContent") or json.loads(r["content"][0]["text"])


@pytest.fixture(scope="module")
def mcp_issuer():
    return TestIssuer(audience=AUD)


def _app(mcp_issuer, admission=None):
    from fixture_app import tools

    config = OAuthResourceServer(issuer=mcp_issuer.issuer, jwks=mcp_issuer.jwks,
                                 admission=admission or Admission())
    return App(name="mgmt-test", tools_module=tools, auth=config)


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)


def _bearer(token):
    return {**MCP, "Authorization": f"Bearer {token}"}


async def _store():
    return DataStoreAuthAdapter(FileSystemUserDataStore(app_name="mgmt-test"))


@pytest.mark.asyncio
async def test_admin_tools_are_hidden_from_and_blocked_for_non_admins(auth_env, mcp_issuer):
    app = _app(mcp_issuer, Admission(policy=ADMISSION_OPEN))
    client = _client(app)
    alice = _bearer(mcp_issuer.token("alice@example.com"))
    async with mcp_running(app, client):
        names = {t["name"] for t in (await client.post("/", json=TOOLS_LIST, headers=alice)).json()["result"]["tools"]}
        blocked = (await client.post("/", json=_call("users_list"), headers=alice)).json()
    assert not ({"users_list", "user_register", "user_block", "usage_report"} & names)
    assert "Unknown tool" in json.dumps(blocked)


@pytest.mark.asyncio
async def test_register_approves_in_advance_and_block_refuses_under_open_admission(auth_env, mcp_issuer):
    app = _app(mcp_issuer, Admission(policy=ADMISSION_OPEN))
    client = _client(app)
    admin = _bearer(mcp_issuer.token(OPERATOR))
    async with mcp_running(app, client):
        reg = _result(await client.post("/", json=_call("user_register", {"email": "Alice@Example.com"}), headers=admin))
        assert reg == {"email": "alice@example.com", "status": "approved", "created": True}
        again = _result(await client.post("/", json=_call("user_register", {"email": "alice@example.com"}), headers=admin))
        assert again["created"] is False, "idempotent"

        ok = await client.post("/", json=TOOLS_LIST, headers=_bearer(mcp_issuer.token("alice@example.com")))
        assert ok.status_code == 200

        blk = _result(await client.post("/", json=_call("user_block", {"email": "alice@example.com"}), headers=admin))
        assert blk["status"] == "blocked"
        refused = await client.post("/", json=TOOLS_LIST, headers=_bearer(mcp_issuer.token("alice@example.com")))
        assert refused.status_code == 403
        assert "blocked" in refused.json()["error_description"]
        assert "www-authenticate" not in refused.headers

        # Open admission must not quietly re-admit a blocked user: the record stays.
        store = await _store()
        assert (await store.get("alice@example.com")).status == "blocked"

        lifted = _result(await client.post("/", json=_call("user_register", {"email": "alice@example.com"}), headers=admin))
        assert lifted["status"] == "approved"
        back = await client.post("/", json=TOOLS_LIST, headers=_bearer(mcp_issuer.token("alice@example.com")))
        assert back.status_code == 200


@pytest.mark.asyncio
async def test_pending_user_appears_in_list_and_register_approves_them(auth_env, mcp_issuer):
    app = _app(mcp_issuer)  # allowlist
    client = _client(app)
    admin = _bearer(mcp_issuer.token(OPERATOR))
    async with mcp_running(app, client):
        first = await client.post("/", json=TOOLS_LIST, headers=_bearer(mcp_issuer.token("bob@example.com")))
        assert first.status_code == 403 and "awaiting approval" in first.json()["error_description"]

        listing = _result(await client.post("/", json=_call("users_list"), headers=admin))
        bob = next(u for u in listing["users"] if u["email"] == "bob@example.com")
        assert bob["status"] == "pending"
        assert listing["users"][0]["status"] == "pending", "pending sorts first"
        assert listing["counts"]["pending"] == 1

        _result(await client.post("/", json=_call("user_register", {"email": "bob@example.com"}), headers=admin))
        second = await client.post("/", json=TOOLS_LIST, headers=_bearer(mcp_issuer.token("bob@example.com")))
        assert second.status_code == 200


@pytest.mark.asyncio
async def test_pre_emptive_block_holds_for_an_email_never_seen(auth_env, mcp_issuer):
    app = _app(mcp_issuer, Admission(policy=ADMISSION_OPEN))
    client = _client(app)
    admin = _bearer(mcp_issuer.token(OPERATOR))
    async with mcp_running(app, client):
        blk = _result(await client.post("/", json=_call("user_block", {"email": "mallory@example.com"}), headers=admin))
        assert blk == {"email": "mallory@example.com", "status": "blocked", "created": True}
        resp = await client.post("/", json=TOOLS_LIST, headers=_bearer(mcp_issuer.token("mallory@example.com")))
        assert resp.status_code == 403 and "blocked" in resp.json()["error_description"]


@pytest.mark.asyncio
async def test_records_without_a_status_field_are_approved(auth_env, mcp_issuer):
    """A 1.x record (no status) keeps working after the upgrade."""
    store = await _store()
    store.store.save("legacy@example.com", "user", {"email": "legacy@example.com", "created": "2026-01-01T00:00:00+00:00"})
    app = _app(mcp_issuer)
    client = _client(app)
    async with mcp_running(app, client):
        resp = await client.post("/", json=TOOLS_LIST, headers=_bearer(mcp_issuer.token("legacy@example.com")))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_max_users_bounds_pending_records_too(auth_env, mcp_issuer):
    app = _app(mcp_issuer, Admission(max_users=1))  # allowlist with a cap
    client = _client(app)
    async with mcp_running(app, client):
        one = await client.post("/", json=TOOLS_LIST, headers=_bearer(mcp_issuer.token("one@example.com")))
        two = await client.post("/", json=TOOLS_LIST, headers=_bearer(mcp_issuer.token("two@example.com")))
    assert "awaiting approval" in one.json()["error_description"]
    assert "not accepting new users" in two.json()["error_description"]
    assert (await (await _store()).get("two@example.com")) is None


@pytest.mark.asyncio
async def test_machine_client_in_admin_client_ids_is_an_administrator(auth_env, mcp_issuer, monkeypatch):
    """A client-credentials token (no email, azp = client id) listed in
    ADMIN_CLIENT_IDS is admitted as an administrator with no record; an
    unlisted one is refused as a token without an email claim."""
    monkeypatch.setenv("ADMIN_CLIENT_IDS", "ci-sync-bot")
    app = _app(mcp_issuer, Admission(policy=ADMISSION_OPEN))
    client = _client(app)
    machine = _bearer(mcp_issuer.token(None, azp="ci-sync-bot"))
    stranger = _bearer(mcp_issuer.token(None, azp="someone-else"))
    async with mcp_running(app, client):
        names = {t["name"] for t in (await client.post("/", json=TOOLS_LIST, headers=machine)).json()["result"]["tools"]}
        assert "users_list" in names
        reg = _result(await client.post("/", json=_call("user_register", {"email": "carol@example.com"}), headers=machine))
        assert reg["status"] == "approved"
        refused = await client.post("/", json=TOOLS_LIST, headers=stranger)
        assert refused.status_code == 401
    # The machine principal left no user record behind.
    emails = {r.email for r in await (await _store()).list()}
    assert "carol@example.com" in emails and not any(e.startswith("client:") for e in emails)


@pytest.mark.asyncio
async def test_machine_client_may_call_the_admin_rest_surface_too(auth_env, mcp_issuer, monkeypatch):
    monkeypatch.setenv("ADMIN_CLIENT_IDS", "ci-sync-bot")
    app = _app(mcp_issuer)
    client = _client(app)
    resp = await client.get("/admin/users", headers={"Authorization": f"Bearer {mcp_issuer.token(None, azp='ci-sync-bot')}"})
    assert resp.status_code == 200
