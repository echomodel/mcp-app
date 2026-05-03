"""HTTP transport contract — in-process via httpx ASGI transport.

Tests identity enforcement, admin endpoints, multi-user segregation.
"""

import os
import pytest
import httpx
import jwt as pyjwt
from datetime import datetime, timezone, timedelta

from mcp_app.context import current_user


@pytest.fixture
def http_env(tmp_path):
    old = {}
    env = {
        "APP_USERS_PATH": str(tmp_path / "users"),
        "SIGNING_KEY": "tck-test-key-32chars-minimum-len!!",
    }
    for k, v in env.items():
        old[k] = os.environ.get(k)
        os.environ[k] = v
    yield env
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def asgi_client(app, http_env):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _admin_token(key="tck-test-key-32chars-minimum-len!!"):
    return pyjwt.encode(
        {"sub": "admin", "scope": "admin",
         "iat": datetime.now(timezone.utc),
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        key, algorithm="HS256",
    )


def _user_token(email, key="tck-test-key-32chars-minimum-len!!"):
    return pyjwt.encode(
        {"sub": email,
         "iat": datetime.now(timezone.utc),
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        key, algorithm="HS256",
    )


@pytest.mark.asyncio
async def test_health_returns_200(asgi_client):
    """Public /health is auth-free and returns the structured status enum.

    The conformance contract pins ``status`` ∈ {healthy, degraded} for a
    serving instance — ``unhealthy`` would be HTTP 503 and is covered by
    the dedicated unit tests.
    """
    resp = await asgi_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] in {"healthy", "degraded"}


@pytest.mark.asyncio
async def test_admin_register_user(asgi_client):
    headers = {"Authorization": f"Bearer {_admin_token()}"}
    resp = await asgi_client.post(
        "/admin/users",
        json={"email": "alice@example.com"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "alice@example.com"
    assert "token" in data


@pytest.mark.asyncio
async def test_admin_list_users(asgi_client):
    headers = {"Authorization": f"Bearer {_admin_token()}"}
    await asgi_client.post(
        "/admin/users",
        json={"email": "bob@example.com"},
        headers=headers,
    )
    resp = await asgi_client.get("/admin/users", headers=headers)
    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()]
    assert "bob@example.com" in emails


@pytest.mark.asyncio
async def test_missing_token_returns_401(asgi_client):
    resp = await asgi_client.post("/", json={})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_unregistered_user_returns_403(asgi_client):
    headers = {"Authorization": f"Bearer {_user_token('nobody@example.com')}"}
    resp = await asgi_client.post("/", json={}, headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_expired_token_returns_403(asgi_client):
    token = pyjwt.encode(
        {"sub": "alice@example.com",
         "iat": datetime.now(timezone.utc) - timedelta(hours=2),
         "exp": datetime.now(timezone.utc) - timedelta(hours=1)},
        "tck-test-key-32chars-minimum-len!!", algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {token}"}
    resp = await asgi_client.post("/", json={}, headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_non_admin_scope_rejected_on_admin_endpoint(asgi_client):
    headers = {"Authorization": f"Bearer {_admin_token()}"}
    await asgi_client.post(
        "/admin/users",
        json={"email": "alice@example.com"},
        headers=headers,
    )
    user_headers = {"Authorization": f"Bearer {_user_token('alice@example.com')}"}
    resp = await asgi_client.get("/admin/users", headers=user_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_register_with_profile(asgi_client):
    headers = {"Authorization": f"Bearer {_admin_token()}"}
    resp = await asgi_client.post(
        "/admin/users",
        json={"email": "profiled@example.com",
              "profile": {"token": "test-backend-key"}},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "profiled@example.com"


@pytest.mark.asyncio
async def test_admin_safe_tool_envelope_versioned(asgi_client, app):
    """Per #34: GET /admin/safe-tool always returns a versioned envelope.

    The schema is additive-only and consumers must tolerate unknown fields,
    but ``schema_version`` and ``supported`` are always present.
    """
    headers = {"Authorization": f"Bearer {_admin_token()}"}
    resp = await asgi_client.get("/admin/safe-tool", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "schema_version" in body
    assert "supported" in body
    if body["supported"]:
        assert "tool" in body
        assert body["tool"]["name"]
    else:
        assert "hint" in body


@pytest.mark.asyncio
async def test_admin_safe_tool_requires_admin(asgi_client):
    resp = await asgi_client.get("/admin/safe-tool")
    assert resp.status_code == 403
