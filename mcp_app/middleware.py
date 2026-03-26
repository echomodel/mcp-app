"""Pure ASGI JWT middleware. Works with any ASGI app — MCP, FastAPI, Starlette, etc."""

import json
from urllib.parse import parse_qs

from mcp_app.context import current_user_id
from mcp_app.verifier import JWTVerifier


class JWTMiddleware:
    """Validates JWT from Authorization header or ?token= query param.

    Sets current_user_id ContextVar on success. Rejects with 401/403
    on failure. Passes through /health without auth.
    """

    def __init__(self, app, verifier: JWTVerifier, store=None):
        self.app = app
        self.verifier = verifier
        # store accepted for uniform middleware signature but not used by JWT middleware

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        if path == "/health":
            return await self.app(scope, receive, send)

        token = self._extract_token(scope)
        if not token:
            return await self._send_error(send, 401, "Missing authentication token")

        access = await self.verifier.verify_token(token)
        if not access:
            return await self._send_error(send, 403, "Invalid or revoked token")

        tok = current_user_id.set(access.client_id)
        try:
            await self.app(scope, receive, send)
        finally:
            current_user_id.reset(tok)

    @staticmethod
    def _extract_token(scope: dict) -> str | None:
        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode()
        if auth.startswith("Bearer "):
            return auth[7:]

        query_string = scope.get("query_string", b"").decode()
        if query_string:
            params = parse_qs(query_string)
            tokens = params.get("token", [])
            if tokens:
                return tokens[0]

        return None

    @staticmethod
    async def _send_error(send, status: int, message: str) -> None:
        body = json.dumps({"error": message}).encode()
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })
