"""JWT middleware for data-owning apps (user-identity)."""

from mcp_app.context import current_user_id
from mcp_app.middleware.common import extract_token, send_error
from mcp_app.verifier import JWTVerifier


class JWTMiddleware:
    """Validates JWT from Authorization header or ?token= query param.

    Sets current_user_id ContextVar on success. Rejects with 401/403
    on failure. Passes through /health without auth.
    """

    def __init__(self, app, verifier: JWTVerifier, store=None):
        self.app = app
        self.verifier = verifier

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

        tok = current_user_id.set(access.client_id)
        try:
            await self.app(scope, receive, send)
        finally:
            current_user_id.reset(tok)
