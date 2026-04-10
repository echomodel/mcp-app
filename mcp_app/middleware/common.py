"""Shared ASGI utilities for auth middleware."""

import json
from urllib.parse import parse_qs


def extract_token(scope: dict) -> str | None:
    """Extract JWT from Authorization header or ?token= query param."""
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


async def send_error(send, status: int, message: str) -> None:
    """Send a JSON error response."""
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


def rewrite_auth_header(headers: list[tuple[bytes, bytes]], token: str) -> list:
    """Replace the Authorization header with an upstream bearer token."""
    new_auth = f"Bearer {token}".encode()
    result = []
    found = False
    for key, value in headers:
        if key == b"authorization":
            result.append((key, new_auth))
            found = True
        else:
            result.append((key, value))
    if not found:
        result.append((b"authorization", new_auth))
    return result
