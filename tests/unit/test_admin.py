"""Tests for admin REST endpoints."""

import os
import json
import pytest
import jwt as pyjwt
from datetime import datetime, timezone, timedelta
from starlette.testclient import TestClient

from mcp_app.admin import create_admin_app
from mcp_app.bridge import DataStoreAuthAdapter
from mcp_app.data_store import FileSystemUserDataStore
from mcp_app.models import UserAuthRecord


SIGNING_KEY = "test-key-for-unit-tests-32chars!!"


@pytest.fixture
def store(tmp_path):
    os.environ["APP_USERS_PATH"] = str(tmp_path / "users")
    os.environ["SIGNING_KEY"] = SIGNING_KEY
    s = FileSystemUserDataStore(app_name="test")
    yield s
    del os.environ["APP_USERS_PATH"]
    del os.environ["SIGNING_KEY"]


@pytest.fixture
def auth_store(store):
    return DataStoreAuthAdapter(store)


@pytest.fixture
def client(auth_store):
    app = create_admin_app(auth_store)
    return TestClient(app)


@pytest.fixture
def admin_token():
    return pyjwt.encode(
        {"sub": "admin", "scope": "admin",
         "iat": datetime.now(timezone.utc),
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        SIGNING_KEY, algorithm="HS256",
    )


def test_register_user(client, admin_token):
    resp = client.post("/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "alice@test.com"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "alice@test.com"
    assert "token" in data
    assert "duration_seconds" in data


def test_register_idempotent(client, admin_token):
    client.post("/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "alice@test.com"})
    resp = client.post("/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "alice@test.com"})
    assert resp.status_code == 200


def test_list_users(client, admin_token):
    client.post("/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "alice@test.com"})
    client.post("/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "bob@test.com"})
    resp = client.get("/users",
        headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert "alice@test.com" in emails
    assert "bob@test.com" in emails


def test_revoke_user(client, admin_token):
    client.post("/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "alice@test.com"})
    resp = client.delete("/users/alice@test.com",
        headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    assert resp.json()["revoked"] == "alice@test.com"


def test_revoke_nonexistent(client, admin_token):
    resp = client.delete("/users/nobody@test.com",
        headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 404


def test_create_token(client, admin_token):
    client.post("/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "alice@test.com"})
    resp = client.post("/tokens",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "alice@test.com"})
    assert resp.status_code == 200
    assert "token" in resp.json()


def test_create_token_nonexistent(client, admin_token):
    resp = client.post("/tokens",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "nobody@test.com"})
    assert resp.status_code == 404


def test_no_admin_token(client):
    resp = client.post("/users", json={"email": "alice@test.com"})
    assert resp.status_code == 403


def test_wrong_admin_token(client):
    bad_token = pyjwt.encode(
        {"sub": "user", "iat": datetime.now(timezone.utc)},
        SIGNING_KEY, algorithm="HS256")
    resp = client.post("/users",
        headers={"Authorization": f"Bearer {bad_token}"},
        json={"email": "alice@test.com"})
    assert resp.status_code == 403
