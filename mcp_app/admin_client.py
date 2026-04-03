"""REST client for managing deployed mcp-app instances.

Stateless — accepts a base URL and signing key, mints admin JWTs,
and calls the /admin REST endpoints. Used by both CLI and MCP tools.
"""

from datetime import datetime, timezone, timedelta

import httpx
import jwt as pyjwt


class AdminClient:
    """Client for a deployed mcp-app instance's admin API."""

    def __init__(self, base_url: str, signing_key: str,
                 http_client: httpx.AsyncClient | None = None):
        self.base_url = base_url.rstrip("/")
        self.signing_key = signing_key
        self._http = http_client or httpx.AsyncClient()

    def _admin_token(self) -> str:
        """Mint a short-lived admin JWT."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "admin",
            "scope": "admin",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        }
        return pyjwt.encode(payload, self.signing_key, algorithm="HS256")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._admin_token()}"}

    async def health_check(self) -> dict:
        """Check if the instance is reachable and healthy."""
        resp = await self._http.get(f"{self.base_url}/health", timeout=10)
        return {"status": "healthy", "status_code": resp.status_code}

    async def list_users(self) -> list[dict]:
        """List all registered users."""
        resp = await self._http.get(
            f"{self.base_url}/admin/users",
            headers=self._headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    async def register_user(self, email: str) -> dict:
        """Register a user and return their token."""
        resp = await self._http.post(
            f"{self.base_url}/admin/users",
            headers=self._headers(),
            json={"email": email},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    async def create_token(self, email: str) -> dict:
        """Create a new token for an existing user."""
        resp = await self._http.post(
            f"{self.base_url}/admin/tokens",
            headers=self._headers(),
            json={"email": email},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    async def revoke_user(self, email: str) -> dict:
        """Revoke a user's access."""
        resp = await self._http.delete(
            f"{self.base_url}/admin/users/{email}",
            headers=self._headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
