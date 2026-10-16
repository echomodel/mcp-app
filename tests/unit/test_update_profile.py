"""Tests for update-profile and add-rejects-existing behavior.

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
from mcp_app.auth import OAuthAdminAuth, OIDCTokenVerifier
from mcp_app.bridge import DataStoreAuthAdapter
from mcp_app.data_store import FileSystemUserDataStore
from mcp_app.models import UserAuthRecord

from .conftest import OPERATOR

BASE_URL = "http://test"


@pytest.fixture
def store(auth_env):
    return FileSystemUserDataStore(app_name="test")


@pytest.fixture
def app(store, issuer):
    auth_store = DataStoreAuthAdapter(store)
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


# --- update_profile via REST ---

@pytest.mark.asyncio
async def test_update_profile_merges_field(adapter):
    await adapter.save(
        UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)),
        profile={"token": "old-key", "region": "us-east"},
    )
    result = await adapter.update_profile("alice@test.com", {"token": "new-key"})
    assert result["profile"]["token"] == "new-key"
    assert result["profile"]["region"] == "us-east"  # preserved


@pytest.mark.asyncio
async def test_update_profile_adds_field(adapter):
    await adapter.save(
        UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)),
        profile={"token": "key"},
    )
    result = await adapter.update_profile("alice@test.com", {"region": "eu-west"})
    assert result["profile"]["token"] == "key"  # preserved
    assert result["profile"]["region"] == "eu-west"


@pytest.mark.asyncio
async def test_update_profile_nonexistent_user(adapter):
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await adapter.update_profile("nobody@test.com", {"token": "x"})
    assert exc_info.value.response.status_code == 404


@pytest.mark.asyncio
async def test_update_profile_no_prior_profile(adapter):
    await adapter.save(
        UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)),
    )
    result = await adapter.update_profile("alice@test.com", {"token": "new-key"})
    assert result["profile"]["token"] == "new-key"


# --- update_profile via local bridge ---

@pytest.mark.asyncio
async def test_bridge_update_profile_merges(store):
    bridge = DataStoreAuthAdapter(store)
    await bridge.save(
        UserAuthRecord(email="bob@test.com", created=datetime.now(timezone.utc)),
        profile={"token": "old", "extra": "keep"},
    )
    result = await bridge.update_profile("bob@test.com", {"token": "new"})
    assert result["token"] == "new"
    assert result["extra"] == "keep"


@pytest.mark.asyncio
async def test_bridge_update_profile_nonexistent(store):
    bridge = DataStoreAuthAdapter(store)
    with pytest.raises(KeyError):
        await bridge.update_profile("nobody@test.com", {"token": "x"})


# --- add rejects existing (REST layer) ---

@pytest.mark.asyncio
async def test_add_existing_user_does_not_overwrite_profile(adapter):
    """REST register_user checks for an existing user and skips the save."""
    await adapter.save(
        UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)),
        profile={"token": "original"},
    )
    result = await adapter.save(
        UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)),
        profile={"token": "overwritten"},
    )
    assert result["registered"] is True
    full = await adapter.get_full("alice@test.com")
    assert full.profile == {"token": "original"}
