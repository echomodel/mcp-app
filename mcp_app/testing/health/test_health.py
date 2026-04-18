"""Health endpoint test — verifies /health returns 200 without auth."""

import os
import pytest
import httpx


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
    resp = await health_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
