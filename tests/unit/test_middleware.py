"""Tests for JWT middleware."""

import os
import json
import pytest
import jwt as pyjwt
from datetime import datetime, timezone, timedelta

from mcp_app.middleware import JWTMiddleware
from mcp_app.verifier import JWTVerifier
from mcp_app.bridge import DataStoreAuthAdapter
from mcp_app.data_store import FileSystemUserDataStore
from mcp_app.models import UserAuthRecord
from mcp_app.context import current_user_id


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
def verifier(auth_store):
    return JWTVerifier(auth_store)


def _make_token(email, key=SIGNING_KEY, expired=False, scope=None):
    payload = {
        "sub": email,
        "iat": datetime.now(timezone.utc),
    }
    if expired:
        payload["exp"] = datetime.now(timezone.utc) - timedelta(hours=1)
    else:
        payload["exp"] = datetime.now(timezone.utc) + timedelta(hours=1)
    if scope:
        payload["scope"] = scope
    return pyjwt.encode(payload, key, algorithm="HS256")


async def _call_middleware(middleware, token=None, path="/", method="POST", query_token=None):
    """Simulate an ASGI request through the middleware."""
    headers = [(b"content-type", b"application/json")]
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))

    query_string = f"token={query_token}".encode() if query_token else b""

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers,
        "query_string": query_string,
    }

    response = {}

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        if message["type"] == "http.response.start":
            response["status"] = message["status"]
        elif message["type"] == "http.response.body":
            response["body"] = message.get("body", b"")

    await middleware(scope, receive, send)
    return response


async def _passthrough_app(scope, receive, send):
    """Simple ASGI app that returns 200."""
    body = json.dumps({"user": current_user_id.get()}).encode()
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": body})


@pytest.mark.asyncio
async def test_valid_token(store, auth_store, verifier):
    # Register user
    await auth_store.save(UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)))

    middleware = JWTMiddleware(_passthrough_app, verifier)
    token = _make_token("alice@test.com")
    resp = await _call_middleware(middleware, token=token)
    assert resp["status"] == 200
    body = json.loads(resp["body"])
    assert body["user"] == "alice@test.com"


@pytest.mark.asyncio
async def test_missing_token(verifier):
    middleware = JWTMiddleware(_passthrough_app, verifier)
    resp = await _call_middleware(middleware)
    assert resp["status"] == 401


@pytest.mark.asyncio
async def test_invalid_token(verifier):
    middleware = JWTMiddleware(_passthrough_app, verifier)
    token = _make_token("alice@test.com", key="wrong-key-wrong-key-32chars!!")
    resp = await _call_middleware(middleware, token=token)
    assert resp["status"] == 403


@pytest.mark.asyncio
async def test_expired_token(store, auth_store, verifier):
    await auth_store.save(UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)))

    middleware = JWTMiddleware(_passthrough_app, verifier)
    token = _make_token("alice@test.com", expired=True)
    resp = await _call_middleware(middleware, token=token)
    assert resp["status"] == 403


@pytest.mark.asyncio
async def test_revoked_user(store, auth_store, verifier):
    await auth_store.save(UserAuthRecord(
        email="bob@test.com",
        created=datetime.now(timezone.utc),
        revoke_after=datetime.now(timezone.utc).timestamp() - 10,
    ))

    middleware = JWTMiddleware(_passthrough_app, verifier)
    token = _make_token("bob@test.com")
    # Token iat is now, revoke_after is 10 seconds ago — but iat > revoke_after should pass
    # Actually revoke_after means tokens issued BEFORE this time are revoked
    # Token issued now (after revoke_after) should be valid
    resp = await _call_middleware(middleware, token=token)
    assert resp["status"] == 200


@pytest.mark.asyncio
async def test_unregistered_user(verifier):
    middleware = JWTMiddleware(_passthrough_app, verifier)
    token = _make_token("nobody@test.com")
    resp = await _call_middleware(middleware, token=token)
    assert resp["status"] == 403


async def _simple_ok_app(scope, receive, send):
    """ASGI app that returns 200 without reading user identity."""
    body = b'{"status": "ok"}'
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": body})


@pytest.mark.asyncio
async def test_health_passthrough(verifier):
    middleware = JWTMiddleware(_simple_ok_app, verifier)
    resp = await _call_middleware(middleware, path="/health", method="GET")
    assert resp["status"] == 200


@pytest.mark.asyncio
async def test_query_param_token(store, auth_store, verifier):
    await auth_store.save(UserAuthRecord(email="alice@test.com", created=datetime.now(timezone.utc)))

    middleware = JWTMiddleware(_passthrough_app, verifier)
    token = _make_token("alice@test.com")
    resp = await _call_middleware(middleware, query_token=token)
    assert resp["status"] == 200
