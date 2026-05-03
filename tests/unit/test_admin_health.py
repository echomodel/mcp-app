"""Tests for the admin /admin/health endpoint added in #39.

The endpoint mirrors the public /health verdict but adds the full
diagnostic detail (paths, fs_type, free bytes, mount source) that
the public response intentionally omits. Authenticated callers only.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import httpx
import jwt as pyjwt
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp_app.admin import create_admin_app
from mcp_app.bridge import DataStoreAuthAdapter
from mcp_app.data_store import FileSystemUserDataStore
from mcp_app.storage_check import StorageCheckResult, reset_last_check


SIGNING_KEY = "test-key-admin-health-32chars-min!!"


@pytest.fixture(autouse=True)
def _reset_storage_cache():
    reset_last_check()
    yield
    reset_last_check()


@pytest.fixture
def admin_app(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_USERS_PATH", str(tmp_path / "users"))
    monkeypatch.setenv("SIGNING_KEY", SIGNING_KEY)
    store = FileSystemUserDataStore(app_name="test-admin-health")
    auth_store = DataStoreAuthAdapter(store)
    inner = create_admin_app(auth_store)
    return Starlette(routes=[Mount("/admin", app=inner)])


@pytest.fixture
def admin_token():
    now = datetime.now(timezone.utc)
    return pyjwt.encode(
        {"sub": "admin", "scope": "admin", "iat": now,
         "exp": now + timedelta(minutes=5)},
        SIGNING_KEY, algorithm="HS256",
    )


def _stub(fs_type_check: str, **overrides) -> StorageCheckResult:
    defaults = dict(
        path="/persistent/users",
        exists=True,
        writable=True,
        fs_type="fuse.gcsfuse",
        free_bytes=999_999,
        required_fs_type="fuse",
        fs_type_check=fs_type_check,
        mount_source="my-bucket",
    )
    defaults.update(overrides)
    return StorageCheckResult(**defaults)


@pytest.mark.asyncio
async def test_admin_health_requires_auth(admin_app):
    transport = httpx.ASGITransport(app=admin_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/admin/health")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_health_returns_full_detail(admin_app, admin_token):
    transport = httpx.ASGITransport(app=admin_app)
    headers = {"Authorization": f"Bearer {admin_token}"}
    with patch("mcp_app.health_check.get_last_check", return_value=_stub("ok")):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/admin/health", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["http_status"] == 200
    storage = body["details"]["persistent_storage"]
    # All identifying fields the public surface omits must appear here.
    assert storage["path"] == "/persistent/users"
    assert storage["fs_type"] == "fuse.gcsfuse"
    assert storage["required_fs_type"] == "fuse"
    assert storage["free_bytes"] == 999_999
    assert storage["mount_source"] == "my-bucket"
    assert storage["fs_type_check"] == "ok"


@pytest.mark.asyncio
async def test_admin_health_reports_unhealthy_with_503_status_field(admin_app, admin_token):
    """The admin endpoint reports the public status verdict including the would-be HTTP code."""
    transport = httpx.ASGITransport(app=admin_app)
    headers = {"Authorization": f"Bearer {admin_token}"}
    with patch("mcp_app.health_check.get_last_check", return_value=_stub("mismatch")):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/admin/health", headers=headers)

    # The admin endpoint itself is 200 (the diagnostic call succeeded);
    # the body reports that public /health would return 503.
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unhealthy"
    assert body["http_status"] == 503
    assert body["details"]["persistent_storage"]["fs_type_check"] == "mismatch"
