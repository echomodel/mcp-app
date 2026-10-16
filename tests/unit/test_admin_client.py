"""Tests for RemoteAuthAdapter — exercises the full stack in-memory.

RemoteAuthAdapter → httpx (ASGI transport) → Starlette → admin.py →
FileSystemUserDataStore → tmp_path. No mocks, no network. The adapter
carries the operator's issuer token, as the admin CLI would after a
sign-in.
"""

import pytest
import httpx
from datetime import datetime, timezone
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mcp_app.admin import create_admin_app
from mcp_app.admin_client import NotSignedInError, RemoteAuthAdapter
from mcp_app.auth import OAuthAdminAuth, OIDCTokenVerifier
from mcp_app.bridge import DataStoreAuthAdapter
from mcp_app.data_store import FileSystemUserDataStore
from mcp_app.models import UserAuthRecord

from .conftest import OPERATOR

BASE_URL = "http://test"


@pytest.fixture
def app(auth_env, issuer):
    auth_store = DataStoreAuthAdapter(FileSystemUserDataStore(app_name="test"))
    verifier = OIDCTokenVerifier(issuer.config, auth_store)
    admin_app = create_admin_app(auth_store, admin_auth=OAuthAdminAuth(verifier))

    async def health(request):
        return JSONResponse({"status": "ok"})

    return Starlette(routes=[
        Route("/health", health),
        Mount("/admin", app=admin_app),
    ])


@pytest.fixture
def adapter(app, issuer):
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url=BASE_URL)
    return RemoteAuthAdapter(BASE_URL, issuer.token(OPERATOR), http_client=http_client)


@pytest.mark.asyncio
async def test_health_check(adapter):
    result = await adapter.health_check()
    assert result["status"] == "healthy"
    assert result["status_code"] == 200


@pytest.mark.asyncio
async def test_save_returns_registered(adapter):
    result = await adapter.save(
        UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc))
    )
    assert result == {"email": "alice@test.com", "registered": True}


@pytest.mark.asyncio
async def test_list_empty(adapter):
    assert await adapter.list() == []


@pytest.mark.asyncio
async def test_list_after_save(adapter):
    await adapter.save(UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)))
    await adapter.save(UserAuthRecord(email="bob@test.com", created=datetime.now(timezone.utc)))
    emails = {u.email for u in await adapter.list()}
    assert {"alice@test.com", "bob@test.com"} <= emails


@pytest.mark.asyncio
async def test_save_idempotent(adapter):
    r1 = await adapter.save(UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)))
    r2 = await adapter.save(UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)))
    assert r1 == r2


@pytest.mark.asyncio
async def test_delete_marks_revoked(adapter):
    await adapter.save(UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)))
    await adapter.delete("alice@test.com")
    users = await adapter.list()
    assert len(users) == 1
    assert users[0].revoke_after is not None


@pytest.mark.asyncio
async def test_delete_nonexistent_raises(adapter):
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await adapter.delete("nobody@test.com")
    assert exc_info.value.response.status_code == 404


@pytest.mark.asyncio
async def test_save_with_profile(adapter):
    result = await adapter.save(
        UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)),
        profile={"token": "test-api-key"},
    )
    assert result["email"] == "alice@test.com"
    full = await adapter.get_full("alice@test.com")
    assert full.profile == {"token": "test-api-key"}


@pytest.mark.asyncio
async def test_without_token_public_calls_work_and_admin_calls_say_why(app):
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url=BASE_URL)
    anonymous = RemoteAuthAdapter(BASE_URL, http_client=http_client)
    assert (await anonymous.health_check())["status_code"] == 200
    with pytest.raises(NotSignedInError, match="signed in as an administrator"):
        await anonymous.list()


@pytest.mark.asyncio
async def test_non_admin_token_is_forbidden(app, issuer):
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url=BASE_URL)
    user = RemoteAuthAdapter(BASE_URL, issuer.token("alice@test.com"), http_client=http_client)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await user.list()
    assert exc_info.value.response.status_code == 403
