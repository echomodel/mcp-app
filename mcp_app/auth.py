"""Authentication modes for ``App.auth``.

Two modes exist while the shared-secret model is phased out:

* :class:`SharedSecretJWT` — the 1.x model. mcp-app issues user tokens
  itself, signed with ``SIGNING_KEY``. Still the default when nothing
  else is configured, so every existing deployment keeps working.
* :class:`OAuthResourceServer` — standard MCP authorization. An external
  OAuth 2.1 authorization server (an identity provider) issues the
  tokens; mcp-app is a resource server that validates them against the
  issuer's JWKS, maps the token's email claim to a user record, and
  publishes RFC 9728 protected-resource metadata so MCP clients can
  discover the issuer from the server URL alone.

Selection: ``App(auth=...)`` wins. Otherwise, ``AUTH_ISSUER`` in the
environment selects :class:`OAuthResourceServer` (built from env), and
its absence selects :class:`SharedSecretJWT`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt as pyjwt
from jwt import PyJWKSet
from pydantic import AnyHttpUrl

from mcp_app.context import current_user, hydrate_profile

logger = logging.getLogger("mcp_app.auth")

# Signature algorithms accepted from the issuer. Asymmetric only: a resource
# server never holds the issuer's signing secret, so HMAC is excluded by
# construction.
ALLOWED_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512")


ENV_ADMIN_EMAILS = "ADMIN_EMAILS"


def admin_emails() -> frozenset[str]:
    """Operator-declared administrators: ``ADMIN_EMAILS``, comma-separated.

    Membership is the whole admin model in OAuth mode: nothing is stored,
    there is no promotion path, and changing the set is a redeploy.
    Compared lower-cased.
    """
    raw = os.environ.get(ENV_ADMIN_EMAILS, "")
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


@dataclass(frozen=True)
class SharedSecretJWT:
    """The 1.x auth model: self-issued HS256 user tokens under ``SIGNING_KEY``.

    Carries no configuration of its own; ``SIGNING_KEY`` and ``JWT_AUD``
    are read from the environment as before.
    """


@dataclass
class OAuthResourceServer:
    """Validate bearer tokens issued by an external OAuth 2.1 authorization server.

    Args:
        issuer: The authorization server's issuer identifier, exactly as it
            appears in the token's ``iss`` claim (trailing slash included if
            the issuer uses one).
        audience: Value the token's ``aud`` claim must contain. Usually the
            API identifier registered at the issuer for this server.
        resource_url: The public URL MCP clients use for this server. It is
            the ``resource`` in the protected-resource metadata document and
            determines where that document is served.
        email_claim: Name of the claim carrying the user's email. ``email``
            by default; issuers that namespace custom claims need the full
            claim name (for example ``https://example.com/email``).
        jwks_uri: Where to fetch the issuer's signing keys. Default: the
            ``jwks_uri`` from the issuer's OpenID discovery document, falling
            back to ``<issuer>/.well-known/jwks.json``.
        jwks: A static JWK Set (``{"keys": [...]}``). When given, no key is
            ever fetched. Intended for tests and air-gapped deployments.
    """

    issuer: str
    audience: str
    resource_url: str
    email_claim: str = "email"
    jwks_uri: str | None = None
    jwks: dict | None = field(default=None, repr=False)

    ENV_ISSUER = "AUTH_ISSUER"
    ENV_AUDIENCE = "AUTH_AUDIENCE"
    ENV_RESOURCE_URL = "MCP_RESOURCE_URL"
    ENV_EMAIL_CLAIM = "AUTH_EMAIL_CLAIM"
    ENV_JWKS_URI = "AUTH_JWKS_URI"

    @classmethod
    def from_env(cls) -> "OAuthResourceServer | None":
        """Build from environment variables, or return ``None`` if unset.

        ``AUTH_ISSUER``, ``AUTH_AUDIENCE`` and ``MCP_RESOURCE_URL`` must be
        set together. A partial set is a misconfiguration and raises, rather
        than silently falling back to the shared-secret model.
        """
        required = {
            cls.ENV_ISSUER: os.environ.get(cls.ENV_ISSUER, "").strip(),
            cls.ENV_AUDIENCE: os.environ.get(cls.ENV_AUDIENCE, "").strip(),
            cls.ENV_RESOURCE_URL: os.environ.get(cls.ENV_RESOURCE_URL, "").strip(),
        }
        if not any(required.values()):
            return None
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise RuntimeError(
                "OAuth resource-server mode needs AUTH_ISSUER, AUTH_AUDIENCE and "
                f"MCP_RESOURCE_URL together; missing: {', '.join(missing)}."
            )
        return cls(
            issuer=required[cls.ENV_ISSUER],
            audience=required[cls.ENV_AUDIENCE],
            resource_url=required[cls.ENV_RESOURCE_URL],
            email_claim=os.environ.get(cls.ENV_EMAIL_CLAIM, "").strip() or "email",
            jwks_uri=os.environ.get(cls.ENV_JWKS_URI, "").strip() or None,
        )

    def protected_resource_routes(self):
        """RFC 9728 metadata route(s), built by the MCP SDK.

        Served at ``/.well-known/oauth-protected-resource`` (plus the
        resource path, if ``resource_url`` has one). Public: clients read
        it before they have a token.
        """
        from mcp.server.auth.routes import create_protected_resource_routes

        return create_protected_resource_routes(
            resource_url=AnyHttpUrl(self.resource_url),
            authorization_servers=[AnyHttpUrl(self.issuer)],
        )

    def resource_metadata_url(self) -> str:
        from mcp.server.auth.routes import build_resource_metadata_url

        return str(build_resource_metadata_url(AnyHttpUrl(self.resource_url)))


class OIDCTokenVerifier:
    """Verify issuer-signed JWTs and resolve them to mcp-app user records.

    Also satisfies the MCP SDK's ``TokenVerifier`` protocol
    (:meth:`verify_token`), so it can be handed to the SDK directly if an
    app ever wants the SDK's own auth middleware instead of mcp-app's.
    """

    def __init__(
        self,
        config: OAuthResourceServer,
        auth_store,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.config = config
        self.auth_store = auth_store
        self._http = http_client
        self._jwk_set: PyJWKSet | None = (
            PyJWKSet.from_dict(config.jwks) if config.jwks is not None else None
        )
        self._jwks_uri = config.jwks_uri
        self._lock = asyncio.Lock()

    # -- key material -----------------------------------------------------

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=10)
        return self._http

    async def _discover_jwks_uri(self) -> str:
        issuer = self.config.issuer.rstrip("/")
        client = await self._client()
        try:
            resp = await client.get(f"{issuer}/.well-known/openid-configuration")
            resp.raise_for_status()
            uri = resp.json().get("jwks_uri")
            if uri:
                return uri
            logger.warning("openid-configuration at %s has no jwks_uri", issuer)
        except httpx.HTTPError as exc:
            logger.warning("OpenID discovery failed for %s: %s", issuer, exc)
        return f"{issuer}/.well-known/jwks.json"

    async def _fetch_jwk_set(self) -> PyJWKSet:
        if self._jwks_uri is None:
            self._jwks_uri = await self._discover_jwks_uri()
        client = await self._client()
        resp = await client.get(self._jwks_uri)
        resp.raise_for_status()
        return PyJWKSet.from_dict(resp.json())

    async def _signing_key(self, token: str):
        """Return the issuer key matching the token's ``kid``.

        Keys are cached. A ``kid`` not in the cache triggers one refetch,
        which is how issuer key rotation is picked up without a restart.
        """
        header = pyjwt.get_unverified_header(token)
        kid = header.get("kid")

        def find(jwk_set: PyJWKSet | None):
            if jwk_set is None:
                return None
            for key in jwk_set.keys:
                if kid is None or key.key_id == kid:
                    return key
            return None

        key = find(self._jwk_set)
        if key is not None or self.config.jwks is not None:
            return key
        async with self._lock:
            key = find(self._jwk_set)
            if key is None:
                self._jwk_set = await self._fetch_jwk_set()
                key = find(self._jwk_set)
        return key

    # -- verification -----------------------------------------------------

    async def verify_claims(self, token: str) -> dict | None:
        """Validate signature, ``iss``, ``aud`` and ``exp``. Claims or ``None``."""
        try:
            key = await self._signing_key(token)
        except (pyjwt.PyJWTError, httpx.HTTPError, ValueError) as exc:
            logger.info("token key lookup failed: %s", exc)
            return None
        if key is None:
            logger.info("token kid not found in issuer JWKS")
            return None
        try:
            return pyjwt.decode(
                token,
                key.key,
                algorithms=list(ALLOWED_ALGORITHMS),
                audience=self.config.audience,
                issuer=self.config.issuer,
                options={"require": ["exp"]},
            )
        except pyjwt.InvalidTokenError as exc:
            logger.info("token rejected: %s", exc)
            return None

    async def resolve_user(self, token: str) -> tuple[str, Any]:
        """Map a token to a user record and set ``current_user``.

        Returns one of:
            ``("ok", UserRecord)`` — token valid, user registered, context set.
            ``("unknown", email)`` — token valid, email not registered (403).
            ``("invalid", reason)`` — token missing, malformed, expired, wrong
            issuer or audience, or lacking the email claim (401).
        """
        claims = await self.verify_claims(token)
        if claims is None:
            return "invalid", "The access token is invalid or expired"
        email = claims.get(self.config.email_claim)
        if not isinstance(email, str) or not email:
            return "invalid", (
                f"The access token carries no '{self.config.email_claim}' claim; "
                "the authorization server must include the user's email"
            )
        email = email.lower()
        record = await self.auth_store.get_full(email)
        if record is None and email in admin_emails():
            # An operator named in ADMIN_EMAILS is admitted by declaration;
            # the record is created on first sign-in so no `users add` is
            # needed to bootstrap a deployment.
            from datetime import datetime, timezone

            from mcp_app.models import UserAuthRecord

            await self.auth_store.save(
                UserAuthRecord(email=email, created=datetime.now(timezone.utc))
            )
            record = await self.auth_store.get_full(email)
        if record is None:
            return "unknown", email
        record.profile = hydrate_profile(record.profile)
        current_user.set(record)
        return "ok", record

    async def verify_token(self, token: str):
        """MCP SDK ``TokenVerifier`` protocol: ``AccessToken`` or ``None``."""
        from mcp.server.auth.provider import AccessToken

        status, value = await self.resolve_user(token)
        if status != "ok":
            return None
        claims = await self.verify_claims(token) or {}
        return AccessToken(
            token=token,
            client_id=value.email,
            scopes=[],
            expires_at=claims.get("exp"),
            resource=self.config.audience,
            subject=claims.get("sub"),
            claims=claims,
        )


class OAuthAdminAuth:
    """Admin auth for OAuth mode: the identity provider's token, for an admin email.

    A request is admin when its bearer token verifies against the issuer
    and its email claim is in ``ADMIN_EMAILS``. No shared secret is
    involved, and the deployment issues no user tokens of its own.
    """

    issues_tokens = False

    def __init__(self, verifier: OIDCTokenVerifier):
        self.verifier = verifier

    async def verify(self, request) -> bool:
        auth = request.headers.get("authorization", "")
        if auth[:7].lower() != "bearer ":
            return False
        claims = await self.verifier.verify_claims(auth[7:].strip())
        if not claims:
            return False
        email = claims.get(self.verifier.config.email_claim)
        return isinstance(email, str) and email.lower() in admin_emails()

    def issue_token(self, email: str, duration_seconds: int | None = None) -> dict:
        raise RuntimeError("OAuth resource-server mode does not issue user tokens")
