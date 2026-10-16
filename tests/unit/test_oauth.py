"""OAuth resource-server mode: issuer-signed tokens, metadata, 401/403 semantics.

Runs the full ASGI stack in-process with a generated RSA key standing in
for the authorization server's signing key. No network, no real issuer.
"""

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from mcp_app.app import App
from mcp_app.auth import OAuthResourceServer, OIDCTokenVerifier
from mcp_app.bridge import DataStoreAuthAdapter
from mcp_app.data_store import FileSystemUserDataStore
from mcp_app.models import UserAuthRecord

ISSUER = "https://issuer.test/"
AUDIENCE = "https://mcp.test/"
RESOURCE = "https://mcp.test/"
KID = "key-1"


def _keypair(kid=KID):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    jwk = json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return pem, jwk


@pytest.fixture(scope="module")
def keys():
    pem, jwk = _keypair()
    return {"pem": pem, "jwks": {"keys": [jwk]}}


def _token(pem, kid=KID, **overrides):
    now = datetime.now(timezone.utc)
    claims = {
        "iss": ISSUER,
        "aud": [AUDIENCE, f"{ISSUER}userinfo"],
        "sub": "google-oauth2|12345",
        "iat": now,
        "exp": now + timedelta(minutes=10),
        "email": "alice@example.com",
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return pyjwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_USERS_PATH", str(tmp_path / "users"))
    # Admin endpoints still use the shared secret in this phase.
    monkeypatch.setenv("SIGNING_KEY", "unit-test-admin-key-32-chars-long!!")
    for var in ("AUTH_ISSUER", "AUTH_AUDIENCE", "MCP_RESOURCE_URL"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


@pytest.fixture
def app(env, keys):
    from fixture_app import tools

    return App(
        name="oauth-test",
        tools_module=tools,
        auth=OAuthResourceServer(
            issuer=ISSUER, audience=AUDIENCE, resource_url=RESOURCE, jwks=keys["jwks"]
        ),
    )


@pytest.fixture
def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://mcp.test")


async def _register(email="alice@example.com"):
    store = FileSystemUserDataStore(app_name="oauth-test")
    await DataStoreAuthAdapter(store).save(
        UserAuthRecord(email=email, created=datetime.now(timezone.utc))
    )


def _rpc(method, params=None, request_id=1):
    body = {"jsonrpc": "2.0", "method": method, "id": request_id}
    if params is not None:
        body["params"] = params
    return body


MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


class _mcp_running:
    """httpx's ASGITransport runs no lifespan; start the SDK session manager by hand."""

    def __init__(self, app, client):
        self.app, self.client = app, client

    async def __aenter__(self):
        await self.client.get("/health")  # builds the ASGI stack lazily
        self._cm = self.app._mcp.session_manager.run()
        await self._cm.__aenter__()

    async def __aexit__(self, *exc):
        await self._cm.__aexit__(*exc)


# -- discovery --------------------------------------------------------------


@pytest.mark.asyncio
async def test_protected_resource_metadata_is_public(client):
    resp = await client.get("/.well-known/oauth-protected-resource")
    assert resp.status_code == 200
    body = resp.json()
    assert body["resource"] == RESOURCE
    assert body["authorization_servers"] == [ISSUER]
    assert "header" in body["bearer_methods_supported"]


@pytest.mark.asyncio
async def test_health_needs_no_token(client):
    resp = await client.get("/health")
    assert resp.status_code == 200


# -- 401: no identity established -------------------------------------------


@pytest.mark.asyncio
async def test_missing_token_gets_challenge_pointing_at_metadata(client):
    resp = await client.post("/", json=_rpc("tools/list"), headers=MCP_HEADERS)
    assert resp.status_code == 401
    www = resp.headers["www-authenticate"]
    assert www.startswith("Bearer ")
    assert 'error="invalid_token"' in www
    assert 'resource_metadata="https://mcp.test/.well-known/oauth-protected-resource"' in www
    assert resp.json()["error"] == "invalid_token"


@pytest.mark.asyncio
async def test_query_token_is_not_accepted(client, keys):
    await _register()
    resp = await client.post(f"/?token={_token(keys['pem'])}", json=_rpc("tools/list"), headers=MCP_HEADERS)
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "https://other.test/"},
        {"iss": "https://other-issuer.test/"},
        {"exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
    ],
    ids=["wrong-audience", "wrong-issuer", "expired"],
)
async def test_bad_claims_are_401(client, keys, overrides):
    await _register()
    resp = await client.post(
        "/",
        json=_rpc("tools/list"),
        headers={**MCP_HEADERS, "Authorization": f"Bearer {_token(keys['pem'], **overrides)}"},
    )
    assert resp.status_code == 401
    assert "resource_metadata=" in resp.headers["www-authenticate"]


@pytest.mark.asyncio
async def test_token_signed_by_unknown_key_is_401(client):
    other_pem, _ = _keypair(kid="rogue")
    resp = await client.post(
        "/",
        json=_rpc("tools/list"),
        headers={**MCP_HEADERS, "Authorization": f"Bearer {_token(other_pem, kid='rogue')}"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_garbage_token_is_401(client):
    resp = await client.post(
        "/", json=_rpc("tools/list"), headers={**MCP_HEADERS, "Authorization": "Bearer not.a.jwt"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_token_without_email_claim_is_401_and_says_so(client, keys):
    resp = await client.post(
        "/",
        json=_rpc("tools/list"),
        headers={**MCP_HEADERS, "Authorization": f"Bearer {_token(keys['pem'], email=None)}"},
    )
    assert resp.status_code == 401
    assert "'email' claim" in resp.json()["error_description"]


# -- 403: identity established, not admitted ---------------------------------


@pytest.mark.asyncio
async def test_unregistered_email_is_403_without_challenge(client, keys):
    resp = await client.post(
        "/",
        json=_rpc("tools/list"),
        headers={**MCP_HEADERS, "Authorization": f"Bearer {_token(keys['pem'], email='nobody@example.com')}"},
    )
    assert resp.status_code == 403
    assert "www-authenticate" not in resp.headers
    assert "nobody@example.com" in resp.json()["error_description"]


# -- 200: the happy path ------------------------------------------------------


@pytest.mark.asyncio
async def test_registered_user_lists_and_calls_tools_as_themselves(app, client, keys):
    await _register("alice@example.com")
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {_token(keys['pem'])}"}

    async with _mcp_running(app, client):
        listed = await client.post("/", json=_rpc("tools/list"), headers=headers)
        assert listed.status_code == 200
        names = {t["name"] for t in listed.json()["result"]["tools"]}
        assert {"ping", "greet"} <= names

        called = await client.post(
            "/",
            json=_rpc("tools/call", {"name": "greet", "arguments": {"name": "Bob"}}, 2),
            headers=headers,
        )
        assert called.status_code == 200
        assert "alice@example.com" in json.dumps(called.json()["result"])


@pytest.mark.asyncio
async def test_email_claim_is_matched_case_insensitively(app, client, keys):
    await _register("alice@example.com")
    async with _mcp_running(app, client):
        resp = await client.post(
            "/",
            json=_rpc("tools/list"),
            headers={**MCP_HEADERS, "Authorization": f"Bearer {_token(keys['pem'], email='Alice@Example.com')}"},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_custom_email_claim_name(env, keys):
    from fixture_app import tools

    app = App(
        name="oauth-test",
        tools_module=tools,
        auth=OAuthResourceServer(
            issuer=ISSUER,
            audience=AUDIENCE,
            resource_url=RESOURCE,
            email_claim="https://example.com/email",
            jwks=keys["jwks"],
        ),
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://mcp.test")
    await _register("alice@example.com")
    token = _token(keys["pem"], email=None, **{"https://example.com/email": "alice@example.com"})
    async with _mcp_running(app, client):
        resp = await client.post(
            "/", json=_rpc("tools/list"), headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"}
        )
    assert resp.status_code == 200


# -- configuration from the environment ---------------------------------------


def test_from_env_is_none_when_unset(env):
    assert OAuthResourceServer.from_env() is None


def test_from_env_reads_all_fields(env, monkeypatch):
    monkeypatch.setenv("AUTH_ISSUER", ISSUER)
    monkeypatch.setenv("AUTH_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("MCP_RESOURCE_URL", RESOURCE)
    monkeypatch.setenv("AUTH_EMAIL_CLAIM", "https://example.com/email")
    monkeypatch.setenv("AUTH_JWKS_URI", "https://issuer.test/keys")
    cfg = OAuthResourceServer.from_env()
    assert cfg == OAuthResourceServer(
        issuer=ISSUER,
        audience=AUDIENCE,
        resource_url=RESOURCE,
        email_claim="https://example.com/email",
        jwks_uri="https://issuer.test/keys",
    )


def test_from_env_partial_config_is_an_error(env, monkeypatch):
    monkeypatch.setenv("AUTH_ISSUER", ISSUER)
    with pytest.raises(RuntimeError, match="AUTH_AUDIENCE, MCP_RESOURCE_URL"):
        OAuthResourceServer.from_env()


def test_app_selects_oauth_mode_from_env(env, monkeypatch, keys):
    """AUTH_ISSUER in the environment switches the default mode without code."""
    from fixture_app import tools
    from mcp_app.auth import SharedSecretJWT

    app = App(name="oauth-test", tools_module=tools)
    assert isinstance(app._resolve_auth(), SharedSecretJWT)

    monkeypatch.setenv("AUTH_ISSUER", ISSUER)
    monkeypatch.setenv("AUTH_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("MCP_RESOURCE_URL", RESOURCE)
    assert isinstance(app._resolve_auth(), OAuthResourceServer)


# -- key fetching: discovery and rotation --------------------------------------


def _mock_issuer(jwks_by_call: list[dict], discovery: bool = True):
    """An httpx MockTransport standing in for the issuer's web endpoints."""
    calls = {"discovery": 0, "jwks": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            calls["discovery"] += 1
            if not discovery:
                return httpx.Response(404)
            return httpx.Response(200, json={"jwks_uri": "https://issuer.test/keys"})
        if request.url.path in ("/keys", "/.well-known/jwks.json"):
            idx = min(calls["jwks"], len(jwks_by_call) - 1)
            calls["jwks"] += 1
            return httpx.Response(200, json=jwks_by_call[idx])
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls


@pytest.mark.asyncio
async def test_jwks_uri_comes_from_openid_discovery(env, keys):
    http, calls = _mock_issuer([keys["jwks"]])
    verifier = OIDCTokenVerifier(
        OAuthResourceServer(issuer=ISSUER, audience=AUDIENCE, resource_url=RESOURCE),
        DataStoreAuthAdapter(FileSystemUserDataStore(app_name="oauth-test")),
        http_client=http,
    )
    assert await verifier.verify_claims(_token(keys["pem"])) is not None
    assert calls == {"discovery": 1, "jwks": 1}
    # Cached: a second token does not refetch.
    assert await verifier.verify_claims(_token(keys["pem"])) is not None
    assert calls == {"discovery": 1, "jwks": 1}


@pytest.mark.asyncio
async def test_discovery_failure_falls_back_to_well_known_jwks(env, keys):
    http, calls = _mock_issuer([keys["jwks"]], discovery=False)
    verifier = OIDCTokenVerifier(
        OAuthResourceServer(issuer=ISSUER, audience=AUDIENCE, resource_url=RESOURCE),
        DataStoreAuthAdapter(FileSystemUserDataStore(app_name="oauth-test")),
        http_client=http,
    )
    assert await verifier.verify_claims(_token(keys["pem"])) is not None
    assert calls["jwks"] == 1


@pytest.mark.asyncio
async def test_unknown_kid_triggers_one_refetch(env, keys):
    """Issuer key rotation: a token signed with a new key is accepted after one refetch."""
    new_pem, new_jwk = _keypair(kid="key-2")
    rotated = {"keys": [new_jwk]}
    http, calls = _mock_issuer([keys["jwks"], rotated])
    verifier = OIDCTokenVerifier(
        OAuthResourceServer(
            issuer=ISSUER, audience=AUDIENCE, resource_url=RESOURCE, jwks_uri="https://issuer.test/keys"
        ),
        DataStoreAuthAdapter(FileSystemUserDataStore(app_name="oauth-test")),
        http_client=http,
    )
    assert await verifier.verify_claims(_token(keys["pem"])) is not None
    assert calls["jwks"] == 1
    assert await verifier.verify_claims(_token(new_pem, kid="key-2")) is not None
    assert calls["jwks"] == 2
    # A kid the issuer never published costs one more fetch and is then rejected.
    rogue_pem, _ = _keypair(kid="rogue")
    assert await verifier.verify_claims(_token(rogue_pem, kid="rogue")) is None
    assert calls["jwks"] == 3


@pytest.mark.asyncio
async def test_verify_token_satisfies_sdk_protocol(env, keys):
    """The verifier can also be handed to the MCP SDK as a TokenVerifier."""
    from mcp.server.auth.provider import AccessToken

    await _register("alice@example.com")
    verifier = OIDCTokenVerifier(
        OAuthResourceServer(issuer=ISSUER, audience=AUDIENCE, resource_url=RESOURCE, jwks=keys["jwks"]),
        DataStoreAuthAdapter(FileSystemUserDataStore(app_name="oauth-test")),
    )
    access = await verifier.verify_token(_token(keys["pem"]))
    assert isinstance(access, AccessToken)
    assert access.client_id == "alice@example.com"
    assert access.subject == "google-oauth2|12345"
    assert await verifier.verify_token(_token(keys["pem"], email="nobody@example.com")) is None
