"""Request-scoped user identity."""

from contextvars import ContextVar

# No default — calling .get() without setting raises LookupError.
# HTTP: middleware sets it from JWT claims.
# stdio: CLI sets it from mcp-app.yaml stdio.identity config.
# Tests: set it explicitly in fixtures.
# Direct SDK use: caller must set it before calling SDK methods.
current_user_id: ContextVar[str] = ContextVar("current_user_id")
