"""Base credential proxy middleware for API-proxy apps."""

import time

from mcp_app.context import current_user_id
from mcp_app.middleware.common import extract_token, send_error, rewrite_auth_header
from mcp_app.verifier import JWTVerifier


class CredentialProxyMiddleware:
    """Base class for credential proxy middleware.

    Validates JWT, looks up stored backend credential for the user,
    resolves an access token via subclass, rewrites the Authorization
    header, and passes the request through. The inner app receives a
    valid backend API token — it doesn't know about JWTs.

    Subclasses implement resolve_access_token().
    """

    CACHE_TTL = 300  # 5 minutes

    def __init__(self, app, verifier: JWTVerifier, store=None):
        self.app = app
        self.verifier = verifier
        self.store = store
        # In-memory cache: email -> (access_token, loaded_at)
        self._cache: dict[str, tuple[str, float]] = {}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        if path == "/health":
            return await self.app(scope, receive, send)

        token = extract_token(scope)
        if not token:
            return await send_error(send, 401, "Missing authentication token")

        access = await self.verifier.verify_token(token)
        if not access:
            return await send_error(send, 403, "Invalid or revoked token")

        email = access.client_id

        try:
            upstream_token = self._get_cached_or_resolve(email)
        except ValueError as e:
            return await send_error(send, 502, f"Credential error: {e}")

        if upstream_token is None:
            return await send_error(send, 403, "No credential stored for user")

        scope = dict(scope)
        scope["headers"] = rewrite_auth_header(scope["headers"], upstream_token)

        tok = current_user_id.set(email)
        try:
            await self.app(scope, receive, send)
        finally:
            current_user_id.reset(tok)

    def _get_cached_or_resolve(self, email: str) -> str | None:
        """Check cache, then resolve from store."""
        now = time.monotonic()

        if email in self._cache:
            cached_token, loaded_at = self._cache[email]
            if now - loaded_at < self.CACHE_TTL:
                return cached_token

        if not self.store:
            raise ValueError("No store configured for credential lookup")

        credential = self.store.load(email, "credential")
        if credential is None:
            self._cache.pop(email, None)
            return None

        access_token = self.resolve_access_token(email, credential)
        self._cache[email] = (access_token, now)
        return access_token

    def resolve_access_token(self, email: str, credential: dict) -> str:
        """Resolve an access token from stored credential data.

        Subclasses implement this.
        """
        raise NotImplementedError
