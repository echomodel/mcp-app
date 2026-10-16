"""Authentication for HTTP mode: standard MCP authorization.

mcp-app is an OAuth 2.1 *resource server*. An external authorization
server (an identity provider, typically fronting Sign in with Google)
signs the user in and issues the access token. mcp-app validates the
token against the issuer's published keys, maps the token's email claim
to a user record, and publishes RFC 9728 protected-resource metadata so
an MCP client discovers the issuer from the server URL alone.

Configuration is the issuer and the administrators. Everything about
*this* server (its public URL, and therefore the audience a token must
carry and the ``resource`` it advertises) is read from each request's
``Host`` header, which on any hostname-routing front door is the same
fact that delivered the request. ``AUTH_AUDIENCE`` pins it for the
rare deployment reached by address rather than by name.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
import jwt as pyjwt
from jwt import PyJWKSet

from mcp_app.context import current_user, hydrate_profile
from mcp_app.models import UserAuthRecord

logger = logging.getLogger("mcp_app.auth")
startup_logger = logging.getLogger("mcp_app.startup")

# Signature algorithms accepted from the issuer. Asymmetric only: a resource
# server never holds the issuer's signing secret, so HMAC is excluded by
# construction.
ALLOWED_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512")

ENV_ISSUER = "AUTH_ISSUER"
ENV_AUDIENCE = "AUTH_AUDIENCE"
ENV_EMAIL_CLAIM = "AUTH_EMAIL_CLAIM"
ENV_JWKS_URI = "AUTH_JWKS_URI"
ENV_ADMIN_EMAILS = "ADMIN_EMAILS"

METADATA_PATH = "/.well-known/oauth-protected-resource"


def admin_emails() -> frozenset[str]:
    """Operator-declared administrators: ``ADMIN_EMAILS``, comma-separated.

    Membership is the whole admin model: nothing is stored, there is no
    promotion path, and changing the set is a redeploy. Compared
    lower-cased.
    """
    raw = os.environ.get(ENV_ADMIN_EMAILS, "")
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


def request_base_url(scope: dict) -> str:
    """The public base URL of this server as the caller reached it.

    Scheme from the ASGI scope (uvicorn fills it from ``X-Forwarded-Proto``
    when run through ``App.serve``), host from the ``Host`` header. The
    ``X-Forwarded-Host`` header is deliberately ignored: any client can add
    it, whereas ``Host`` is what routed the request here. Always ends in
    ``/``, which is the form an MCP client types and an issuer registers.
    """
    host = ""
    for name, value in scope.get("headers", []):
        if name.lower() == b"host":
            host = value.decode("latin-1").strip()
            break
    if not host:
        server = scope.get("server") or ("localhost", None)
        host = server[0] if server[1] in (None, 80, 443) else f"{server[0]}:{server[1]}"
    scheme = scope.get("scheme", "http")
    return f"{scheme}://{host}/"


@dataclass
class OAuthResourceServer:
    """How HTTP callers are authenticated: tokens from an external issuer.

    Args:
        issuer: The authorization server's issuer identifier, exactly as it
            appears in the token's ``iss`` claim (trailing slash included if
            the issuer uses one). From ``AUTH_ISSUER``.
        email_claim: Name of the claim carrying the user's email. ``email``
            by default; issuers that namespace custom claims need the full
            claim name (for example ``https://example.com/email``). From
            ``AUTH_EMAIL_CLAIM``.
        audience: Value the token's ``aud`` claim must contain. ``None``
            (default) means the server's own URL as each request reached
            it, which is the API identifier an operator registers at the
            issuer. Set it only for a deployment reached by address rather
            than hostname, or one answering on several hostnames. From
            ``AUTH_AUDIENCE``.
        jwks_uri: Where to fetch the issuer's signing keys. Default: the
            ``jwks_uri`` from the issuer's OpenID discovery document, falling
            back to ``<issuer>/.well-known/jwks.json``. From ``AUTH_JWKS_URI``.
        jwks: A static JWK Set (``{"keys": [...]}``). When given, no key is
            ever fetched. For tests and air-gapped deployments; not read
            from the environment.
    """

    issuer: str
    email_claim: str = "email"
    audience: str | None = None
    jwks_uri: str | None = None
    jwks: dict | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> "OAuthResourceServer":
        """Build from the environment. ``AUTH_ISSUER`` is required for HTTP."""
        issuer = os.environ.get(ENV_ISSUER, "").strip()
        if not issuer:
            raise RuntimeError(
                f"{ENV_ISSUER} is required to serve HTTP: the OAuth 2.1 "
                "authorization server (identity provider) that issues tokens "
                "for this server, e.g. https://your-tenant.us.auth0.com/. "
                f"Set {ENV_ADMIN_EMAILS} as well, or nobody can administer it."
            )
        return cls(
            issuer=issuer,
            email_claim=os.environ.get(ENV_EMAIL_CLAIM, "").strip() or "email",
            audience=os.environ.get(ENV_AUDIENCE, "").strip() or None,
            jwks_uri=os.environ.get(ENV_JWKS_URI, "").strip() or None,
        )

    def audience_for(self, base_url: str) -> str:
        """The audience a token must carry for a request that reached ``base_url``."""
        return self.audience or base_url

    def log_startup(self) -> None:
        """One factual line about the auth configuration, in the data_dir style."""
        aud = self.audience or f"<derived from request Host; set {ENV_AUDIENCE} to pin>"
        admins = len(admin_emails())
        startup_logger.info(
            f"auth issuer={self.issuer} audience={aud} "
            f"email_claim={self.email_claim} admin_emails={admins}"
        )
        if admins == 0:
            startup_logger.warning(
                f"{ENV_ADMIN_EMAILS} is empty: no one can call /admin or "
                "bootstrap the first user"
            )

    def protected_resource_route(self):
        """RFC 9728 metadata, built per request from the URL the caller used.

        Public: clients read it before they hold a token. The ``resource``
        is the URL the client reached us by, so it matches what the client
        typed; the SDK's metadata model supplies the field names and the
        hour-long cache header.
        """
        from mcp.server.auth.routes import ProtectedResourceMetadataHandler, cors_middleware
        from mcp.shared.auth import ProtectedResourceMetadata
        from pydantic import AnyHttpUrl
        from starlette.routing import Route

        issuer = self.issuer

        async def handle(request):
            metadata = ProtectedResourceMetadata(
                resource=AnyHttpUrl(request_base_url(request.scope)),
                authorization_servers=[AnyHttpUrl(issuer)],
            )
            return await ProtectedResourceMetadataHandler(metadata).handle(request)

        return Route(
            METADATA_PATH,
            endpoint=cors_middleware(handle, ["GET", "OPTIONS"]),
            methods=["GET", "OPTIONS"],
        )


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

    async def verify_claims(self, token: str, audience: str) -> dict | None:
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
                audience=audience,
                issuer=self.config.issuer,
                options={"require": ["exp"]},
            )
        except pyjwt.InvalidTokenError as exc:
            logger.info("token rejected: %s", exc)
            return None

    def email_of(self, claims: dict) -> str | None:
        email = claims.get(self.config.email_claim)
        if isinstance(email, str) and email:
            return email.lower()
        return None

    async def resolve_user(self, token: str, audience: str) -> tuple[str, Any]:
        """Map a token to a user record and set ``current_user``.

        Returns one of:
            ``("ok", UserRecord)`` — token valid, user registered, context set.
            ``("unknown", email)`` — token valid, email not registered (403).
            ``("invalid", reason)`` — token missing, malformed, expired, wrong
            issuer or audience, or lacking the email claim (401).
        """
        claims = await self.verify_claims(token, audience)
        if claims is None:
            return "invalid", "The access token is invalid or expired"
        email = self.email_of(claims)
        if email is None:
            return "invalid", (
                f"The access token carries no '{self.config.email_claim}' claim; "
                "the authorization server must include the user's email"
            )
        record = await self.auth_store.get_full(email)
        if record is None and email in admin_emails():
            # An operator named in ADMIN_EMAILS is admitted by declaration;
            # the record is created on first sign-in so no `users add` is
            # needed to bootstrap a deployment.
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
        """MCP SDK ``TokenVerifier`` protocol: ``AccessToken`` or ``None``.

        The SDK gives no request context here, so this path needs a
        configured ``audience``; with a derived audience it refuses.
        """
        from mcp.server.auth.provider import AccessToken

        if self.config.audience is None:
            raise RuntimeError(
                "verify_token needs a configured audience; set "
                f"{ENV_AUDIENCE} to use the SDK's TokenVerifier protocol"
            )
        status, value = await self.resolve_user(token, self.config.audience)
        if status != "ok":
            return None
        claims = await self.verify_claims(token, self.config.audience) or {}
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
    """Admin auth: the identity provider's token, for an email in ``ADMIN_EMAILS``.

    No shared secret is involved, and the deployment issues no user tokens
    of its own.
    """

    def __init__(self, verifier: OIDCTokenVerifier):
        self.verifier = verifier

    async def verify(self, request) -> bool:
        auth = request.headers.get("authorization", "")
        if auth[:7].lower() != "bearer ":
            return False
        audience = self.verifier.config.audience_for(request_base_url(request.scope))
        claims = await self.verifier.verify_claims(auth[7:].strip(), audience)
        if not claims:
            return False
        email = self.verifier.email_of(claims)
        return email is not None and email in admin_emails()
