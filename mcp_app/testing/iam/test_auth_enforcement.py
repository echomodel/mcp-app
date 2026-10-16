"""HTTP transport contract — in-process via httpx ASGI transport.

Tests identity enforcement, admin endpoints, and the OAuth front door
against a stand-in identity provider. No shared secret anywhere: tokens
are signed by ``mcp_app.testing.issuer.TestIssuer`` and verified by the
app exactly as a real issuer's would be.
"""

import httpx
import pytest

from mcp_app.testing.fixtures import OPERATOR, issuer, mcp_running, oauth_env  # noqa: F401


@pytest.fixture
def asgi_client(app, oauth_env):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def admin_headers(oauth_env):
    return oauth_env.headers(OPERATOR)


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
async def test_discovery_document_is_public_and_names_the_issuer(asgi_client, oauth_env):
    """RFC 9728 metadata: how an MCP client finds the authorization server."""
    resp = await asgi_client.get("/.well-known/oauth-protected-resource")
    assert resp.status_code == 200
    body = resp.json()
    assert body["resource"] == "http://test/"
    assert body["authorization_servers"] == [oauth_env.issuer]


@pytest.mark.asyncio
async def test_admin_register_user(asgi_client, admin_headers):
    resp = await asgi_client.post(
        "/admin/users",
        json={"email": "alice@example.com"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "alice@example.com"
    assert data["registered"] is True
    assert "token" not in data, "2.x issues no tokens; the authorization server does"


@pytest.mark.asyncio
async def test_admin_list_users(asgi_client, admin_headers):
    await asgi_client.post(
        "/admin/users",
        json={"email": "bob@example.com"},
        headers=admin_headers,
    )
    resp = await asgi_client.get("/admin/users", headers=admin_headers)
    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()]
    assert "bob@example.com" in emails


@pytest.mark.asyncio
async def test_missing_token_returns_401_with_challenge(asgi_client):
    resp = await asgi_client.post("/", json={})
    assert resp.status_code == 401
    www = resp.headers.get("www-authenticate", "")
    assert www.startswith("Bearer "), f"expected a Bearer challenge, got {www!r}"
    assert 'resource_metadata="http://test/.well-known/oauth-protected-resource"' in www


@pytest.mark.asyncio
async def test_unregistered_user_returns_403(asgi_client, oauth_env):
    headers = oauth_env.headers("nobody@example.com")
    resp = await asgi_client.post("/", json={}, headers=headers)
    assert resp.status_code == 403
    assert "www-authenticate" not in resp.headers, (
        "a registered identity that is not admitted gets no challenge; "
        "re-authenticating cannot help"
    )


@pytest.mark.asyncio
async def test_expired_token_returns_401(asgi_client, oauth_env):
    headers = {"Authorization": f"Bearer {oauth_env.token('alice@example.com', expired=True)}"}
    resp = await asgi_client.post("/", json={}, headers=headers)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_token_for_another_audience_returns_401(asgi_client, oauth_env):
    """A token issued for a different server on the same issuer is refused."""
    headers = {"Authorization": f"Bearer {oauth_env.token(OPERATOR, audience='https://other-app.test/')}"}
    resp = await asgi_client.post("/", json={}, headers=headers)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_email_is_admitted_on_first_sign_in(app, asgi_client, admin_headers):
    """ADMIN_EMAILS bootstraps a deployment: the operator needs no `users add`,
    and the first signed-in request already lists the app's tools."""
    body = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
    headers = {**admin_headers, "Accept": "application/json, text/event-stream"}
    async with mcp_running(app, asgi_client):
        resp = await asgi_client.post("/", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json()["result"]["tools"], list)
    listed = await asgi_client.get("/admin/users", headers=admin_headers)
    assert OPERATOR in [u["email"] for u in listed.json()]


@pytest.mark.asyncio
async def test_non_admin_rejected_on_admin_endpoint(asgi_client, admin_headers, oauth_env):
    await asgi_client.post(
        "/admin/users",
        json={"email": "alice@example.com"},
        headers=admin_headers,
    )
    resp = await asgi_client.get("/admin/users", headers=oauth_env.headers("alice@example.com"))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_register_with_profile(asgi_client, admin_headers):
    resp = await asgi_client.post(
        "/admin/users",
        json={"email": "profiled@example.com",
              "profile": {"token": "test-backend-key"}},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "profiled@example.com"


@pytest.mark.asyncio
async def test_admin_safe_tool_envelope_versioned(asgi_client, admin_headers):
    """Per #34: GET /admin/safe-tool always returns a versioned envelope.

    The schema is additive-only and consumers must tolerate unknown fields,
    but ``schema_version`` and ``supported`` are always present.
    """
    resp = await asgi_client.get("/admin/safe-tool", headers=admin_headers)
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
