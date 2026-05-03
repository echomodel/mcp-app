"""Health endpoint conformance tests.

Implementing apps inherit these tests via ``mcp_app.testing.health``.
The test pinning is the public contract — it changes only when the
contract changes (and gets a major version bump).

Public contract:
  - GET /health requires no auth.
  - Body shape: ``{"status": <enum>, "checks": {<key>: <enum>, ...}}``.
  - ``status`` ∈ ``{"healthy", "degraded", "unhealthy"}``.
  - HTTP code: 200 for healthy/degraded, 503 for unhealthy.
  - The body MUST NOT contain identifying detail (paths, fs_type
    strings, REQUIRED_FS_TYPE values, free bytes, mount source).
    Identifying detail lives on /admin/health (auth-gated) and in
    startup logs.
"""

import os
import pytest
import httpx


_FORBIDDEN_PUBLIC_KEYS = {
    "path", "fs_type", "required_fs_type", "free_bytes",
    "mount_source", "writable",
}


@pytest.fixture
def health_client(app, tmp_path):
    os.environ["APP_USERS_PATH"] = str(tmp_path / "users")
    os.environ["SIGNING_KEY"] = "tck-test-key-32chars-minimum-len!!"
    transport = httpx.ASGITransport(app=app)
    yield httpx.AsyncClient(transport=transport, base_url="http://test")
    os.environ.pop("APP_USERS_PATH", None)
    os.environ.pop("SIGNING_KEY", None)


@pytest.mark.asyncio
async def test_health_returns_200_without_auth(health_client):
    """A healthy or degraded response is HTTP 200 and requires no auth."""
    resp = await health_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"healthy", "degraded"}, (
        f"Expected status to be healthy or degraded; got {body['status']!r}"
    )


@pytest.mark.asyncio
async def test_health_response_has_checks_object(health_client):
    """The response always includes a ``checks`` object (possibly empty)."""
    resp = await health_client.get("/health")
    body = resp.json()
    assert "checks" in body, f"Expected 'checks' in response body; got {body!r}"
    assert isinstance(body["checks"], dict), (
        f"Expected 'checks' to be an object; got {type(body['checks'])}"
    )


@pytest.mark.asyncio
async def test_health_response_is_identity_free(health_client):
    """The public response must not leak identifying detail."""
    resp = await health_client.get("/health")
    body = resp.json()
    leaked = _FORBIDDEN_PUBLIC_KEYS & set(body.keys())
    assert not leaked, (
        f"Public /health response leaked identifying keys: {leaked}. "
        f"Identifying detail belongs on /admin/health, never on /health."
    )
    # Also check the checks object doesn't carry detail dicts.
    for key, value in body.get("checks", {}).items():
        assert isinstance(value, str), (
            f"checks.{key} must be a string enum value, got {type(value)}. "
            f"Identifying detail belongs on /admin/health."
        )
