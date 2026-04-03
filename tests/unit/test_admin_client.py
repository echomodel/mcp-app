"""Tests for AdminClient — exercises the full stack in-memory.

AdminClient → httpx (ASGI transport) → Starlette → admin.py → FileSystemUserDataStore → tmp_path.
No mocks, no network.
"""

import pytest
import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mcp_app.admin import create_admin_app
from mcp_app.admin_client import AdminClient
from mcp_app.bridge import DataStoreAuthAdapter
from mcp_app.data_store import FileSystemUserDataStore


SIGNING_KEY = "test-key-for-admin-client-32ch!!"
BASE_URL = "http://test"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_USERS_PATH", str(tmp_path / "users"))
    monkeypatch.setenv("SIGNING_KEY", SIGNING_KEY)
    return FileSystemUserDataStore(app_name="test")


@pytest.fixture
def app(store):
    auth_store = DataStoreAuthAdapter(store)
    admin_app = create_admin_app(auth_store)

    async def health(request):
        return JSONResponse({"status": "ok"})

    return Starlette(routes=[
        Route("/health", health),
        Mount("/admin", app=admin_app),
    ])


@pytest.fixture
def client(app):
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url=BASE_URL)
    return AdminClient(BASE_URL, SIGNING_KEY, http_client=http_client)


@pytest.mark.asyncio
async def test_health_check(client):
    result = await client.health_check()
    assert result["status"] == "healthy"
    assert result["status_code"] == 200


@pytest.mark.asyncio
async def test_register_user_returns_email_and_token(client):
    result = await client.register_user("alice@test.com")
    assert result["email"] == "alice@test.com"
    assert "token" in result


@pytest.mark.asyncio
async def test_list_users_empty(client):
    result = await client.list_users()
    assert result == []


@pytest.mark.asyncio
async def test_list_users_after_register(client):
    await client.register_user("alice@test.com")
    await client.register_user("bob@test.com")
    users = await client.list_users()
    emails = {u["email"] for u in users}
    assert "alice@test.com" in emails
    assert "bob@test.com" in emails


@pytest.mark.asyncio
async def test_register_idempotent(client):
    r1 = await client.register_user("alice@test.com")
    r2 = await client.register_user("alice@test.com")
    assert r1["email"] == r2["email"]
    assert "token" in r1 and "token" in r2


@pytest.mark.asyncio
async def test_create_token_for_existing_user(client):
    await client.register_user("alice@test.com")
    result = await client.create_token("alice@test.com")
    assert result["email"] == "alice@test.com"
    assert "token" in result


@pytest.mark.asyncio
async def test_create_token_for_nonexistent_user_raises(client):
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await client.create_token("nobody@test.com")
    assert exc_info.value.response.status_code == 404


@pytest.mark.asyncio
async def test_revoke_user(client):
    await client.register_user("alice@test.com")
    result = await client.revoke_user("alice@test.com")
    assert result["revoked"] == "alice@test.com"


@pytest.mark.asyncio
async def test_revoke_nonexistent_user_raises(client):
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await client.revoke_user("nobody@test.com")
    assert exc_info.value.response.status_code == 404


@pytest.mark.asyncio
async def test_full_lifecycle(client):
    """Register → list → create token → revoke → list shows revoked."""
    reg = await client.register_user("alice@test.com")
    assert reg["email"] == "alice@test.com"

    users = await client.list_users()
    assert len(users) == 1
    assert users[0]["email"] == "alice@test.com"
    assert users[0].get("revoke_after") is None

    tok = await client.create_token("alice@test.com")
    assert "token" in tok

    await client.revoke_user("alice@test.com")

    users = await client.list_users()
    assert len(users) == 1
    assert users[0]["revoke_after"] is not None
