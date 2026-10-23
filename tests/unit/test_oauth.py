"""The HTTP identity layer: issuer-signed tokens, discovery, 401/403 semantics.

Runs the full ASGI stack in-process against the stand-in issuer from
``mcp_app.testing.issuer``. No network, no real identity provider.
"""

import json
from datetime import datetime, timedelta, timezone

import httpx
import jwt as pyjwt
import pytest

from mcp_app.app import App
from mcp_app.auth import (
    ADMISSION_OPEN,
    Admission,
    OAuthResourceServer,
    OIDCTokenVerifier,
    admin_emails,
    request_base_url,
)
from mcp_app.bridge import DataStoreAuthAdapter
from mcp_app.data_store import FileSystemUserDataStore
from mcp_app.models import UserAuthRecord
from mcp_app.testing.issuer import TestIssuer

from .conftest import OPERATOR

BASE = "https://mcp.test"          # what the test client types
AUD = "https://mcp.test/"          # what the server derives, and tokens must carry
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture(scope="module")
def mcp_issuer():
    return TestIssuer(audience=AUD)


@pytest.fixture
def app(auth_env, mcp_issuer):
    from fixture_app import tools

    return App(name="oauth-test", tools_module=tools, auth=mcp_issuer.config)


@pytest.fixture
def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)


def _bearer(token):
    return {**MCP_HEADERS, "Authorization": f"Bearer {token}"}


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
async def test_protected_resource_metadata_reflects_the_url_the_caller_used(client, mcp_issuer):
    resp = await client.get("/.well-known/oauth-protected-resource")
    assert resp.status_code == 200
    body = resp.json()
    assert body["resource"] == AUD
    assert body["authorization_servers"] == [mcp_issuer.issuer]
    assert "header" in body["bearer_methods_supported"]


@pytest.mark.asyncio
async def test_metadata_follows_host_header(app):
    """Two hostnames for one service each see themselves as the resource."""
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://alias.test")
    resp = await client.get("/.well-known/oauth-protected-resource")
    assert resp.json()["resource"] == "https://alias.test/"


@pytest.mark.asyncio
async def test_health_needs_no_token(client):
    assert (await client.get("/health")).status_code == 200


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
async def test_query_token_is_not_accepted(client, mcp_issuer):
    await _register()
    token = mcp_issuer.token("alice@example.com")
    resp = await client.post(f"/?token={token}", json=_rpc("tools/list"), headers=MCP_HEADERS)
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"audience": "https://other.test/"},
        {"iss": "https://other-issuer.test/"},
        {"expired": True},
    ],
    ids=["wrong-audience", "wrong-issuer", "expired"],
)
async def test_bad_claims_are_401(client, mcp_issuer, kwargs):
    await _register()
    resp = await client.post(
        "/", json=_rpc("tools/list"), headers=_bearer(mcp_issuer.token("alice@example.com", **kwargs))
    )
    assert resp.status_code == 401
    assert "resource_metadata=" in resp.headers["www-authenticate"]


@pytest.mark.asyncio
async def test_token_signed_by_unknown_key_is_401(client):
    rogue = TestIssuer(audience=AUD, kid="rogue")
    resp = await client.post(
        "/", json=_rpc("tools/list"), headers=_bearer(rogue.token("alice@example.com"))
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_garbage_token_is_401(client):
    resp = await client.post("/", json=_rpc("tools/list"), headers=_bearer("not.a.jwt"))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_token_without_email_claim_is_401_and_says_so(client, mcp_issuer):
    resp = await client.post("/", json=_rpc("tools/list"), headers=_bearer(mcp_issuer.token(None)))
    assert resp.status_code == 401
    assert "'email' claim" in resp.json()["error_description"]


@pytest.mark.asyncio
async def test_legacy_shared_secret_token_is_401(client):
    legacy = pyjwt.encode(
        {"sub": "alice@example.com", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "some-old-signing-key-32-chars-long!!",
        algorithm="HS256",
    )
    resp = await client.post("/", json=_rpc("tools/list"), headers=_bearer(legacy))
    assert resp.status_code == 401


# -- 403: identity established, not admitted ---------------------------------


@pytest.mark.asyncio
async def test_unregistered_email_is_403_without_challenge(client, mcp_issuer):
    resp = await client.post(
        "/", json=_rpc("tools/list"), headers=_bearer(mcp_issuer.token("nobody@example.com"))
    )
    assert resp.status_code == 403
    assert "www-authenticate" not in resp.headers
    assert "nobody@example.com" in resp.json()["error_description"]


# -- 200: the happy path ------------------------------------------------------


@pytest.mark.asyncio
async def test_registered_user_lists_and_calls_tools_as_themselves(app, client, mcp_issuer):
    await _register("alice@example.com")
    headers = _bearer(mcp_issuer.token("alice@example.com"))

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
async def test_email_claim_is_matched_case_insensitively(app, client, mcp_issuer):
    await _register("alice@example.com")
    async with _mcp_running(app, client):
        resp = await client.post(
            "/", json=_rpc("tools/list"), headers=_bearer(mcp_issuer.token("Alice@Example.com"))
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_admin_email_is_admitted_as_a_user_on_first_sign_in(app, client, mcp_issuer):
    """ADMIN_EMAILS bootstraps a fresh deployment: no `users add` for the operator."""
    async with _mcp_running(app, client):
        resp = await client.post("/", json=_rpc("tools/list"), headers=_bearer(mcp_issuer.token(OPERATOR)))
    assert resp.status_code == 200
    store = DataStoreAuthAdapter(FileSystemUserDataStore(app_name="oauth-test"))
    assert (await store.get(OPERATOR)) is not None


@pytest.mark.asyncio
async def test_custom_email_claim_name(auth_env):
    from fixture_app import tools

    namespaced = TestIssuer(audience=AUD, email_claim="https://example.com/email")
    app = App(name="oauth-test", tools_module=tools, auth=namespaced.config)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)
    await _register("alice@example.com")
    async with _mcp_running(app, client):
        resp = await client.post(
            "/", json=_rpc("tools/list"), headers=_bearer(namespaced.token("alice@example.com"))
        )
    assert resp.status_code == 200


# -- the admin surface -------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_token_reaches_admin_endpoints(client, mcp_issuer):
    headers = _bearer(mcp_issuer.token(OPERATOR))
    created = await client.post("/admin/users", json={"email": "alice@example.com"}, headers=headers)
    assert created.status_code == 200
    assert created.json() == {"email": "alice@example.com", "registered": True}
    listed = await client.get("/admin/users", headers=headers)
    assert [u["email"] for u in listed.json()] == ["alice@example.com"]


@pytest.mark.asyncio
async def test_non_admin_is_forbidden_on_admin_endpoints(client, mcp_issuer):
    await _register("alice@example.com")
    assert (await client.get("/admin/users", headers=_bearer(mcp_issuer.token("alice@example.com")))).status_code == 403
    assert (await client.get("/admin/users")).status_code == 403


@pytest.mark.asyncio
async def test_tokens_endpoint_does_not_exist(client, mcp_issuer):
    resp = await client.post("/admin/tokens", json={"email": "x"}, headers=_bearer(mcp_issuer.token(OPERATOR)))
    assert resp.status_code == 404


# -- configuration -----------------------------------------------------------


def test_from_env_requires_the_issuer(auth_env):
    with pytest.raises(RuntimeError, match="AUTH_ISSUER"):
        OAuthResourceServer.from_env()


def test_from_env_reads_optional_fields(auth_env, monkeypatch):
    monkeypatch.setenv("AUTH_ISSUER", "https://issuer.test/")
    monkeypatch.setenv("AUTH_AUDIENCE", "https://pinned.test/")
    monkeypatch.setenv("AUTH_EMAIL_CLAIM", "https://example.com/email")
    monkeypatch.setenv("AUTH_JWKS_URI", "https://issuer.test/keys")
    assert OAuthResourceServer.from_env() == OAuthResourceServer(
        issuer="https://issuer.test/",
        email_claim="https://example.com/email",
        audience="https://pinned.test/",
        jwks_uri="https://issuer.test/keys",
    )


def test_from_env_minimal(auth_env, monkeypatch):
    monkeypatch.setenv("AUTH_ISSUER", "https://issuer.test/")
    cfg = OAuthResourceServer.from_env()
    assert cfg.issuer == "https://issuer.test/"
    assert cfg.audience is None and cfg.email_claim == "email" and cfg.jwks_uri is None
    assert cfg.audience_for("https://mcp.test/") == "https://mcp.test/"


def test_admin_emails_parsing(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", " A@x.io ,,b@y.io,")
    assert admin_emails() == frozenset({"a@x.io", "b@y.io"})
    monkeypatch.delenv("ADMIN_EMAILS")
    assert admin_emails() == frozenset()


def test_request_base_url_uses_host_and_scheme_and_ignores_forwarded_host():
    scope = {
        "scheme": "https",
        "headers": [(b"x-forwarded-host", b"evil.test"), (b"host", b"mcp.example.com")],
    }
    assert request_base_url(scope) == "https://mcp.example.com/"
    assert request_base_url({"scheme": "http", "headers": [(b"host", b"localhost:8080")]}) == "http://localhost:8080/"
    assert request_base_url({"scheme": "http", "headers": [], "server": ("127.0.0.1", 9000)}) == "http://127.0.0.1:9000/"


@pytest.mark.asyncio
async def test_audience_override_pins_what_tokens_must_carry(auth_env):
    """With AUTH_AUDIENCE set, the Host no longer decides; the pinned value does."""
    from fixture_app import tools

    pinned = TestIssuer(audience="https://pinned.test/")
    config = OAuthResourceServer(issuer=pinned.issuer, audience="https://pinned.test/", jwks=pinned.jwks)
    app = App(name="oauth-test", tools_module=tools, auth=config)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)
    async with _mcp_running(app, client):
        ok = await client.post("/", json=_rpc("tools/list"), headers=_bearer(pinned.token(OPERATOR)))
        bad = await client.post(
            "/", json=_rpc("tools/list"), headers=_bearer(pinned.token(OPERATOR, audience=AUD))
        )
    assert ok.status_code == 200
    assert bad.status_code == 401


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


def _fetching_verifier(http, **config):
    return OIDCTokenVerifier(
        OAuthResourceServer(issuer="https://issuer.test/", **config),
        DataStoreAuthAdapter(FileSystemUserDataStore(app_name="oauth-test")),
        http_client=http,
    )


@pytest.mark.asyncio
async def test_jwks_uri_comes_from_openid_discovery(auth_env, mcp_issuer):
    http, calls = _mock_issuer([mcp_issuer.jwks])
    verifier = _fetching_verifier(http)
    assert await verifier.verify_claims(mcp_issuer.token("a@example.com"), AUD) is not None
    assert calls == {"discovery": 1, "jwks": 1}
    # Cached: a second token does not refetch.
    assert await verifier.verify_claims(mcp_issuer.token("a@example.com"), AUD) is not None
    assert calls == {"discovery": 1, "jwks": 1}


@pytest.mark.asyncio
async def test_discovery_failure_falls_back_to_well_known_jwks(auth_env, mcp_issuer):
    http, calls = _mock_issuer([mcp_issuer.jwks], discovery=False)
    verifier = _fetching_verifier(http)
    assert await verifier.verify_claims(mcp_issuer.token("a@example.com"), AUD) is not None
    assert calls["jwks"] == 1


@pytest.mark.asyncio
async def test_unknown_kid_triggers_one_refetch(auth_env, mcp_issuer):
    """Issuer key rotation: a token signed with a new key is accepted after one refetch."""
    rotated = TestIssuer(audience=AUD, kid="key-2")
    http, calls = _mock_issuer([mcp_issuer.jwks, rotated.jwks])
    verifier = _fetching_verifier(http, jwks_uri="https://issuer.test/keys")
    assert await verifier.verify_claims(mcp_issuer.token("a@example.com"), AUD) is not None
    assert calls["jwks"] == 1
    assert await verifier.verify_claims(rotated.token("a@example.com"), AUD) is not None
    assert calls["jwks"] == 2
    # A kid the issuer never published costs one more fetch and is then rejected.
    rogue = TestIssuer(audience=AUD, kid="rogue")
    assert await verifier.verify_claims(rogue.token("a@example.com"), AUD) is None
    assert calls["jwks"] == 3


@pytest.mark.asyncio
async def test_verify_token_satisfies_sdk_protocol_with_a_pinned_audience(auth_env):
    """The verifier can also be handed to the MCP SDK as a TokenVerifier."""
    from mcp.server.auth.provider import AccessToken

    pinned = TestIssuer(audience="https://pinned.test/")
    await _register("alice@example.com")
    verifier = OIDCTokenVerifier(
        OAuthResourceServer(issuer=pinned.issuer, audience="https://pinned.test/", jwks=pinned.jwks),
        DataStoreAuthAdapter(FileSystemUserDataStore(app_name="oauth-test")),
    )
    access = await verifier.verify_token(pinned.token("alice@example.com"))
    assert isinstance(access, AccessToken)
    assert access.client_id == "alice@example.com"
    assert await verifier.verify_token(pinned.token("nobody@example.com")) is None


@pytest.mark.asyncio
async def test_verify_token_refuses_without_a_pinned_audience(auth_env, mcp_issuer):
    verifier = OIDCTokenVerifier(
        mcp_issuer.config, DataStoreAuthAdapter(FileSystemUserDataStore(app_name="oauth-test"))
    )
    with pytest.raises(RuntimeError, match="AUTH_AUDIENCE"):
        await verifier.verify_token(mcp_issuer.token("alice@example.com"))


# -- admission policy -----------------------------------------------------

from mcp_app.testing.fixtures import mcp_running  # noqa: E402

TOOLS_LIST = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}


def _open_app(mcp_issuer, max_users=None):
    from fixture_app import tools

    config = OAuthResourceServer(
        issuer=mcp_issuer.issuer, jwks=mcp_issuer.jwks,
        admission=Admission(policy=ADMISSION_OPEN, max_users=max_users),
    )
    return App(name="oauth-test", tools_module=tools, auth=config)


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)


def test_allowlist_is_the_default_policy(auth_env):
    assert Admission().policy == "allowlist"
    assert Admission.from_env() == Admission()


def test_admission_from_env_parses_policy_and_cap(auth_env, monkeypatch):
    monkeypatch.setenv("AUTH_ADMISSION", "Open")
    monkeypatch.setenv("MAX_USERS", "25")
    assert Admission.from_env() == Admission(policy="open", max_users=25)


@pytest.mark.parametrize("var,value", [("AUTH_ADMISSION", "anyone"), ("MAX_USERS", "many"), ("MAX_USERS", "0")])
def test_admission_from_env_rejects_bad_values(auth_env, monkeypatch, var, value):
    monkeypatch.setenv(var, value)
    with pytest.raises(ValueError):
        Admission.from_env()


@pytest.mark.asyncio
async def test_open_admission_registers_a_new_email_on_first_request(auth_env, mcp_issuer):
    """Open mode: any email the issuer vouches for gets a record and runs,
    and is still not an administrator."""
    app = _open_app(mcp_issuer)
    client = _client(app)
    newcomer = _bearer(mcp_issuer.token("newcomer@example.com"))
    async with mcp_running(app, client):
        resp = await client.post("/", json=TOOLS_LIST, headers=newcomer)
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json()["result"]["tools"], list)
    store = DataStoreAuthAdapter(FileSystemUserDataStore(app_name="oauth-test"))
    assert await store.get("newcomer@example.com") is not None
    assert (await client.get("/admin/users", headers=newcomer)).status_code == 403


@pytest.mark.asyncio
async def test_open_admission_stops_at_max_users(auth_env, mcp_issuer):
    """The cap counts every record; past it a new email gets 403 and no record."""
    await _register("first@example.com")
    app = _open_app(mcp_issuer, max_users=1)
    client = _client(app)
    resp = await client.post("/", json=TOOLS_LIST, headers=_bearer(mcp_issuer.token("second@example.com")))
    assert resp.status_code == 403
    assert "not accepting new users" in resp.json()["error_description"]
    assert "www-authenticate" not in resp.headers
    store = DataStoreAuthAdapter(FileSystemUserDataStore(app_name="oauth-test"))
    assert await store.get("second@example.com") is None
    async with mcp_running(app, client):
        existing = await client.post("/", json=TOOLS_LIST, headers=_bearer(mcp_issuer.token("first@example.com")))
    assert existing.status_code == 200, "an existing user is unaffected by the cap"


@pytest.mark.asyncio
async def test_admins_are_admitted_past_the_cap(auth_env, mcp_issuer):
    """ADMIN_EMAILS is a declaration: the cap never locks the operator out."""
    await _register("first@example.com")
    app = _open_app(mcp_issuer, max_users=1)
    client = _client(app)
    async with mcp_running(app, client):
        resp = await client.post("/", json=TOOLS_LIST, headers=_bearer(mcp_issuer.token(OPERATOR)))
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_allowlist_mode_still_refuses_unknown_emails(auth_env, mcp_issuer):
    from fixture_app import tools

    app = App(name="oauth-test", tools_module=tools, auth=mcp_issuer.config)
    resp = await _client(app).post("/", json=TOOLS_LIST, headers=_bearer(mcp_issuer.token("stranger@example.com")))
    assert resp.status_code == 403
    assert "not registered" in resp.json()["error_description"]
