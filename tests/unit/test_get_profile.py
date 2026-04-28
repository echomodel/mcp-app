"""Tests for the get-profile flow.

Exercises the full stack in-memory: RemoteAuthAdapter → httpx ASGI
transport → Starlette admin endpoints → DataStoreAuthAdapter →
FileSystemUserDataStore → tmp_path.
"""

import pytest
import httpx
from datetime import datetime, timezone
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mcp_app.admin import create_admin_app
from mcp_app.admin_client import RemoteAuthAdapter
from mcp_app.bridge import DataStoreAuthAdapter
from mcp_app.data_store import FileSystemUserDataStore
from mcp_app.models import UserAuthRecord


SIGNING_KEY = "test-key-get-profile-32chars-pad!"
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
def adapter(app):
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url=BASE_URL)
    return RemoteAuthAdapter(BASE_URL, SIGNING_KEY, http_client=http_client)


# --- get_full via REST ---

@pytest.mark.asyncio
async def test_get_full_returns_profile(adapter):
    await adapter.save(
        UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)),
        profile={"token": "abc123", "region": "us-east"},
    )
    record = await adapter.get_full("alice@test.com")
    assert record is not None
    assert record.email == "alice@test.com"
    assert record.profile == {"token": "abc123", "region": "us-east"}


@pytest.mark.asyncio
async def test_get_full_user_without_profile(adapter):
    await adapter.save(
        UserAuthRecord(email="bob@test.com", created=datetime.now(timezone.utc)),
    )
    record = await adapter.get_full("bob@test.com")
    assert record is not None
    assert record.email == "bob@test.com"
    assert record.profile is None


@pytest.mark.asyncio
async def test_get_full_unknown_user(adapter):
    record = await adapter.get_full("nobody@test.com")
    assert record is None


# --- REST endpoint directly ---

@pytest.mark.asyncio
async def test_get_profile_endpoint_requires_admin(adapter):
    await adapter.save(
        UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)),
        profile={"token": "abc"},
    )
    resp = await adapter._http.get(
        f"{BASE_URL}/admin/users/alice@test.com/profile",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_profile_endpoint_404_for_unknown_user(adapter):
    resp = await adapter._http.get(
        f"{BASE_URL}/admin/users/nobody@test.com/profile",
        headers=adapter._headers(),
    )
    assert resp.status_code == 404


# --- get via local bridge ---

@pytest.mark.asyncio
async def test_bridge_get_full_returns_profile(store):
    bridge = DataStoreAuthAdapter(store)
    await bridge.save(
        UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)),
        profile={"token": "xyz"},
    )
    record = await bridge.get_full("alice@test.com")
    assert record is not None
    assert record.profile == {"token": "xyz"}
