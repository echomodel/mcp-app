"""REST admin endpoints for user management.

Mounted at /admin on the solution's ASGI app. Every endpoint is gated by
an ``AdminAuth`` strategy, in practice :class:`mcp_app.auth.OAuthAdminAuth`:
the identity provider's token for an email listed in ``ADMIN_EMAILS``.
The deployment issues no tokens of its own; the authorization server does.
"""

from datetime import datetime, timezone

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp_app.health_check import build_admin_health_detail
from mcp_app.models import UserAuthRecord
from mcp_app.store import UserAuthStore

SAFE_TOOL_SCHEMA_VERSION = "1"


def create_admin_app(store: UserAuthStore, *, admin_auth, safe_tool=None) -> Starlette:
    """Create a Starlette app with admin REST endpoints.

    Args:
        store: Auth store for user registration and profile storage.
            POST /admin/users accepts an optional 'profile' field saved
            alongside the auth record.
        admin_auth: Object with ``async verify(request) -> bool`` deciding
            who may call these endpoints. The ``App`` passes
            ``mcp_app.auth.OAuthAdminAuth``.
        safe_tool: Optional ``SafeTool`` declaration. When set, exposed
            via ``GET /admin/safe-tool`` so an operator can perform an
            end-to-end smoke test using the declared tool. The endpoint
            carries only metadata; the caller does the MCP handshake.
    """

    async def _verify_admin(request: Request) -> bool:
        return await admin_auth.verify(request)

    async def register_user(request: Request) -> JSONResponse:
        if not await _verify_admin(request):
            return JSONResponse({"error": "Forbidden"}, status_code=403)

        body = await request.json()
        email = body.get("email")
        if not email:
            return JSONResponse({"error": "email required"}, status_code=400)
        email = email.lower()

        existing = await store.get(email)
        if not existing:
            profile = body.get("profile")
            await store.save(
                UserAuthRecord(
                    email=email,
                    created=datetime.now(timezone.utc),
                ),
                profile=profile,
            )
        return JSONResponse({"email": email, "registered": True})

    async def list_users(request: Request) -> JSONResponse:
        if not await _verify_admin(request):
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        users = await store.list()
        return JSONResponse([u.model_dump(mode="json") for u in users])

    async def revoke_user(request: Request) -> JSONResponse:
        if not await _verify_admin(request):
            return JSONResponse({"error": "Forbidden"}, status_code=403)

        email = request.path_params["email"]
        user = await store.get(email)
        if not user:
            return JSONResponse({"error": "Not found"}, status_code=404)

        user.revoke_after = datetime.now(timezone.utc).timestamp()
        await store.save(user)
        return JSONResponse({"revoked": email})

    async def update_profile(request: Request) -> JSONResponse:
        """Merge fields into a user's profile."""
        if not await _verify_admin(request):
            return JSONResponse({"error": "Forbidden"}, status_code=403)

        email = request.path_params["email"]
        user = await store.get(email)
        if not user:
            return JSONResponse({"error": "Not found"}, status_code=404)

        body = await request.json()
        if not body or not isinstance(body, dict):
            return JSONResponse({"error": "body must be a JSON object"}, status_code=400)

        updated = await store.update_profile(email, body)
        return JSONResponse({"email": email, "profile": updated})

    async def get_profile(request: Request) -> JSONResponse:
        """Read a user's profile."""
        if not await _verify_admin(request):
            return JSONResponse({"error": "Forbidden"}, status_code=403)

        email = request.path_params["email"]
        record = await store.get_full(email)
        if not record:
            return JSONResponse({"error": "Not found"}, status_code=404)

        return JSONResponse({"email": email, "profile": record.profile})

    async def get_admin_health(request: Request) -> JSONResponse:
        """Full health diagnostic detail. Admin auth required.

        Mirrors what the public /health returns, plus the underlying
        per-check raw fields (path, fs_type, free_bytes, etc.) that
        the public response intentionally omits. Use this when /health
        reports degraded or unhealthy and you need to know why.
        """
        if not await _verify_admin(request):
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        return JSONResponse(build_admin_health_detail())

    async def get_safe_tool(request: Request) -> JSONResponse:
        """Return the solution's safe-tool declaration, or an unsupported envelope.

        Schema is versioned and additive-only: ``schema_version`` is
        always present so future readers can detect format changes.
        Consumers must tolerate unknown fields.
        """
        if not await _verify_admin(request):
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        if safe_tool is None:
            return JSONResponse({
                "schema_version": SAFE_TOOL_SCHEMA_VERSION,
                "supported": False,
                "hint": (
                    "This deployment did not declare a safe tool. "
                    "Run probe to verify the MCP layer and inspect "
                    "available tools."
                ),
            })
        return JSONResponse({
            "schema_version": SAFE_TOOL_SCHEMA_VERSION,
            "supported": True,
            "tool": {
                "name": safe_tool.name,
                "description": safe_tool.description,
                "arguments": safe_tool.arguments,
            },
        })

    return Starlette(routes=[
        Route("/users", register_user, methods=["POST"]),
        Route("/users", list_users, methods=["GET"]),
        Route("/users/{email:path}/profile", update_profile, methods=["PATCH"]),
        Route("/users/{email:path}/profile", get_profile, methods=["GET"]),
        Route("/users/{email:path}", revoke_user, methods=["DELETE"]),
        Route("/safe-tool", get_safe_tool, methods=["GET"]),
        Route("/health", get_admin_health, methods=["GET"]),
    ])
