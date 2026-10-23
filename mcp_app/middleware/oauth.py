"""Bearer-token identity middleware: the one HTTP identity layer.

Sits outside the MCP ASGI app and owns the ``current_user`` ContextVar.

* Tokens come only from the ``Authorization`` header. The ``?token=``
  query form is not accepted; the MCP authorization spec forbids it.
* A missing or invalid token gets ``401`` with a ``WWW-Authenticate``
  challenge that points at the protected-resource metadata document, so
  a standards-following client discovers the authorization server and
  starts the OAuth flow on its own.
* A valid token whose email is not registered gets ``403``: the identity
  is established, the service just isn't open to it. Re-authenticating
  would not help, so no challenge is sent. Under open admission
  (``AUTH_ADMISSION=open``) a new email is registered on its first
  request instead, until ``MAX_USERS`` records exist; past the cap the
  answer is the same ``403`` with a different description.

Public paths pass through untouched: ``/health`` and anything under
``/.well-known/`` (the metadata document must be readable before the
client has a token).
"""

import json

from mcp_app.auth import METADATA_PATH, OIDCTokenVerifier, request_base_url


class OAuthMiddleware:
    def __init__(self, app, verifier: OIDCTokenVerifier, store=None):
        self.app = app
        self.verifier = verifier
        self.config = verifier.config

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        if path == "/health" or path.startswith("/.well-known/"):
            return await self.app(scope, receive, send)

        base_url = request_base_url(scope)
        token = _bearer_token(scope)
        if not token:
            return await self._challenge(send, base_url, "Authentication required")

        status, value = await self.verifier.resolve_user(
            token, self.config.audience_for(base_url)
        )
        if status == "invalid":
            return await self._challenge(send, base_url, value)
        if status in ("unknown", "full"):
            description = (
                f"{value} is not registered with this service"
                if status == "unknown"
                else "This service is not accepting new users"
            )
            return await _send_json(
                send,
                403,
                {"error": "forbidden", "error_description": description},
            )
        await self.app(scope, receive, send)

    async def _challenge(self, send, base_url: str, description: str):
        metadata_url = base_url.rstrip("/") + METADATA_PATH
        www = (
            f'Bearer error="invalid_token", error_description="{description}", '
            f'resource_metadata="{metadata_url}"'
        )
        await _send_json(
            send,
            401,
            {"error": "invalid_token", "error_description": description},
            extra_headers=[(b"www-authenticate", www.encode())],
        )


def _bearer_token(scope: dict) -> str | None:
    for name, value in scope.get("headers", []):
        if name.lower() == b"authorization":
            auth = value.decode()
            if auth[:7].lower() == "bearer ":
                return auth[7:].strip() or None
            return None
    return None


async def _send_json(send, status: int, body: dict, extra_headers=None) -> None:
    payload = json.dumps(body).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(payload)).encode()),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": payload})
