"""REST admin endpoints for user management.

Mounted at /admin on the solution's ASGI app. Gated by admin-scoped
JWT — same signing key as user tokens, with scope: "admin".
"""

import os
from datetime import datetime, timezone, timedelta

import jwt as pyjwt
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp_app.models import UserAuthRecord
from mcp_app.store import UserAuthStore

_FALLBACK_TOKEN_DURATION = 315360000  # ~10 years in seconds


class InvalidTokenDurationError(ValueError):
    """Raised when TOKEN_DURATION_SECONDS env var is not a valid integer."""
    pass


def get_default_token_duration() -> int:
    """Resolve default token duration in seconds.

    Priority: TOKEN_DURATION_SECONDS env var → _FALLBACK_TOKEN_DURATION.
    Empty/unset env var silently falls back. Non-integer value raises.
    """
    raw = os.environ.get("TOKEN_DURATION_SECONDS")
    if not raw:
        return _FALLBACK_TOKEN_DURATION
    try:
        return int(raw)
    except ValueError:
        raise InvalidTokenDurationError(
            f"TOKEN_DURATION_SECONDS must be an integer, got: {raw!r}"
        )


def create_admin_app(store: UserAuthStore, data_store=None) -> Starlette:
    """Create a Starlette app with admin REST endpoints.

    Args:
        store: Auth store for user registration and verification.
        data_store: Optional data store for saving backend credentials
            (used by credential proxy middleware). If provided, POST
            /admin/users accepts an optional 'credential' field.
    """

    signing_key = os.environ.get("SIGNING_KEY")
    if not signing_key:
        raise RuntimeError(
            "SIGNING_KEY environment variable is required for admin endpoints."
        )
    audience = os.environ.get("JWT_AUD")

    def _verify_admin(request: Request) -> bool:
        """Check that the request carries a valid admin-scoped JWT."""
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return False
        try:
            claims = pyjwt.decode(
                auth[7:], signing_key, algorithms=["HS256"],
                audience=audience,
            )
            return claims.get("scope") == "admin"
        except pyjwt.InvalidTokenError:
            return False

    def _issue_token(email: str, duration_seconds: int | None = None) -> dict:
        if duration_seconds is None:
            duration_seconds = get_default_token_duration()
        """Create a signed JWT for a user."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": email,
            "iat": now,
            "exp": now + timedelta(seconds=duration_seconds),
        }
        if audience:
            payload["aud"] = audience
        token = pyjwt.encode(payload, signing_key, algorithm="HS256")
        return {
            "email": email,
            "token": token,
            "duration_seconds": duration_seconds,
        }

    async def register_user(request: Request) -> JSONResponse:
        if not _verify_admin(request):
            return JSONResponse({"error": "Forbidden"}, status_code=403)

        body = await request.json()
        email = body.get("email")
        if not email:
            return JSONResponse({"error": "email required"}, status_code=400)

        duration = body.get("duration_seconds", get_default_token_duration())

        existing = await store.get(email)
        if not existing:
            await store.save(UserAuthRecord(
                email=email,
                created=datetime.now(timezone.utc),
            ))

        # Save backend credential if provided (for credential proxy apps)
        credential = body.get("credential")
        if credential is not None and data_store is not None:
            # If credential is a plain string, wrap it for bearer-proxy
            if isinstance(credential, str):
                credential = {"token": credential}
            data_store.save(email, "credential", credential)

        return JSONResponse(_issue_token(email, duration))

    async def list_users(request: Request) -> JSONResponse:
        if not _verify_admin(request):
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        users = await store.list()
        return JSONResponse([u.model_dump(mode="json") for u in users])

    async def revoke_user(request: Request) -> JSONResponse:
        if not _verify_admin(request):
            return JSONResponse({"error": "Forbidden"}, status_code=403)

        email = request.path_params["email"]
        user = await store.get(email)
        if not user:
            return JSONResponse({"error": "Not found"}, status_code=404)

        user.revoke_after = datetime.now(timezone.utc).timestamp()
        await store.save(user)
        return JSONResponse({"revoked": email})

    async def create_token(request: Request) -> JSONResponse:
        """Issue a new token for an existing, active user."""
        if not _verify_admin(request):
            return JSONResponse({"error": "Forbidden"}, status_code=403)

        body = await request.json()
        email = body.get("email")
        if not email:
            return JSONResponse({"error": "email required"}, status_code=400)

        user = await store.get(email)
        if not user:
            return JSONResponse({"error": "User not found"}, status_code=404)

        duration = body.get("duration_seconds", get_default_token_duration())
        return JSONResponse(_issue_token(email, duration))

    return Starlette(routes=[
        Route("/users", register_user, methods=["POST"]),
        Route("/users", list_users, methods=["GET"]),
        Route("/users/{email:path}", revoke_user, methods=["DELETE"]),
        Route("/tokens", create_token, methods=["POST"]),
    ])
