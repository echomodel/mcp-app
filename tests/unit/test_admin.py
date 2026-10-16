"""Tests for admin REST endpoints, gated by an administrator's issuer token."""

import jwt as pyjwt
import pytest
from datetime import datetime, timezone, timedelta
from starlette.testclient import TestClient

from mcp_app.admin import create_admin_app
from mcp_app.auth import OAuthAdminAuth, OIDCTokenVerifier
from mcp_app.bridge import DataStoreAuthAdapter
from mcp_app.data_store import FileSystemUserDataStore

from .conftest import OPERATOR

# Starlette's TestClient reaches the app as http://testserver, so that is
# the audience the server derives and tokens must carry.
AUD = "http://testserver/"


@pytest.fixture
def client(auth_env, issuer):
    auth_store = DataStoreAuthAdapter(FileSystemUserDataStore(app_name="test"))
    verifier = OIDCTokenVerifier(issuer.config, auth_store)
    return TestClient(create_admin_app(auth_store, admin_auth=OAuthAdminAuth(verifier)))


@pytest.fixture
def admin(issuer):
    return issuer.headers(OPERATOR, audience=AUD)


def test_register_user(client, admin):
    resp = client.post("/users", headers=admin, json={"email": "alice@test.com"})
    assert resp.status_code == 200
    assert resp.json() == {"email": "alice@test.com", "registered": True}


def test_register_idempotent(client, admin):
    client.post("/users", headers=admin, json={"email": "alice@test.com"})
    resp = client.post("/users", headers=admin, json={"email": "alice@test.com"})
    assert resp.status_code == 200


def test_register_lower_cases_email(client, admin):
    client.post("/users", headers=admin, json={"email": "Alice@Test.com"})
    emails = {u["email"] for u in client.get("/users", headers=admin).json()}
    assert emails == {"alice@test.com"}


def test_list_users(client, admin):
    client.post("/users", headers=admin, json={"email": "alice@test.com"})
    client.post("/users", headers=admin, json={"email": "bob@test.com"})
    resp = client.get("/users", headers=admin)
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert {"alice@test.com", "bob@test.com"} <= emails


def test_revoke_user(client, admin):
    client.post("/users", headers=admin, json={"email": "alice@test.com"})
    resp = client.delete("/users/alice@test.com", headers=admin)
    assert resp.status_code == 200
    assert resp.json()["revoked"] == "alice@test.com"


def test_revoke_nonexistent(client, admin):
    resp = client.delete("/users/nobody@test.com", headers=admin)
    assert resp.status_code == 404


def test_tokens_endpoint_is_gone(client, admin):
    """2.x issues no tokens; the route does not exist."""
    resp = client.post("/tokens", headers=admin, json={"email": "alice@test.com"})
    assert resp.status_code == 404


def test_no_token(client):
    resp = client.post("/users", json={"email": "alice@test.com"})
    assert resp.status_code == 403


def test_non_admin_email_rejected(client, issuer):
    headers = issuer.headers("alice@test.com", audience=AUD)
    resp = client.post("/users", headers=headers, json={"email": "bob@test.com"})
    assert resp.status_code == 403


def test_admin_token_for_another_audience_rejected(client, issuer):
    headers = issuer.headers(OPERATOR, audience="https://other-app.test/")
    resp = client.get("/users", headers=headers)
    assert resp.status_code == 403


def test_legacy_shared_secret_token_rejected(client):
    legacy = pyjwt.encode(
        {"sub": "admin", "scope": "admin",
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        "some-old-signing-key-32-chars-long!!", algorithm="HS256",
    )
    resp = client.get("/users", headers={"Authorization": f"Bearer {legacy}"})
    assert resp.status_code == 403
