"""Remote auth adapter — implements UserAuthStore over HTTP.

Connects to a deployed mcp-app instance's /admin REST endpoints.
Mints admin JWTs locally using the signing key.
"""

from datetime import datetime, timezone, timedelta

import httpx
import jwt as pyjwt

from mcp_app.models import UserAuthRecord, UserRecord


class RemoteAuthAdapter:
    """UserAuthStore implementation backed by a remote mcp-app instance."""

    def __init__(self, base_url: str, signing_key: str,
                 http_client: httpx.AsyncClient | None = None):
        self.base_url = base_url.rstrip("/")
        self.signing_key = signing_key
        self._http = http_client or httpx.AsyncClient()

    def _admin_token(self) -> str:
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
        resp = await self._http.get(f"{self.base_url}/health", timeout=10)
        return {"status": "healthy", "status_code": resp.status_code}

    def _user_token(self, email: str, minutes: int = 5) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": email,
            "iat": now,
            "exp": now + timedelta(minutes=minutes),
        }
        return pyjwt.encode(payload, self.signing_key, algorithm="HS256")

    async def probe(self, user_email: str | None = None) -> dict:
        """End-to-end service probe.

        Hits /health, then attempts an MCP tools/list round-trip using a
        short-lived token minted for user_email. If user_email is None, the
        first registered user is used. If no user is available, returns
        liveness-only with a reason.
        """
        result = {"url": self.base_url, "health": None, "mcp": None, "tools": None}
        try:
            health = await self.health_check()
            result["health"] = health
        except Exception as exc:
            result["health"] = {"status": "unreachable", "error": str(exc)}
            return result

        if user_email is None:
            try:
                users = await self.list()
            except Exception as exc:
                result["mcp"] = {
                    "status": "skipped",
                    "reason": f"could not enumerate users: {exc}",
                }
                return result
            active = [u for u in users if u.revoke_after is None]
            if not active:
                result["mcp"] = {
                    "status": "skipped",
                    "reason": "no registered users — cannot mint a probe token",
                }
                return result
            user_email = active[0].email

        token = self._user_token(user_email)
        url = self.base_url + "/"
        try:
            tool_names = await _mcp_list_tools(url, token, self._http)
            result["mcp"] = {"status": "ok", "probed_as": user_email}
            result["tools"] = tool_names
        except Exception as exc:
            result["mcp"] = {
                "status": "error",
                "probed_as": user_email,
                "error": str(exc),
            }
        return result

    async def get(self, email: str) -> UserAuthRecord | None:
        users = await self.list()
        for u in users:
            if u.email == email:
                return u
        return None

    async def get_full(self, email: str) -> UserRecord | None:
        record = await self.get(email)
        if not record:
            return None
        return UserRecord(
            email=record.email,
            created=record.created,
            revoke_after=record.revoke_after,
        )

    async def list(self) -> list[UserAuthRecord]:
        resp = await self._http.get(
            f"{self.base_url}/admin/users",
            headers=self._headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return [UserAuthRecord(**u) for u in resp.json()]

    async def save(self, record: UserAuthRecord, profile: dict | None = None) -> dict:
        body = {"email": record.email}
        if profile is not None:
            body["profile"] = profile
        resp = await self._http.post(
            f"{self.base_url}/admin/users",
            headers=self._headers(),
            json=body,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    async def delete(self, email: str) -> None:
        resp = await self._http.delete(
            f"{self.base_url}/admin/users/{email}",
            headers=self._headers(),
            timeout=10,
        )
        resp.raise_for_status()

    async def update_profile(self, email: str, updates: dict) -> dict:
        resp = await self._http.patch(
            f"{self.base_url}/admin/users/{email}/profile",
            headers=self._headers(),
            json=updates,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    async def create_token(self, email: str) -> dict:
        resp = await self._http.post(
            f"{self.base_url}/admin/tokens",
            headers=self._headers(),
            json={"email": email},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()


async def _mcp_list_tools(
    url: str, token: str, http_client: httpx.AsyncClient | None = None,
) -> list[str]:
    """MCP tools/list round-trip over streamable HTTP.

    The server runs with stateless_http=True and json_response=True so a
    single POST with Accept: application/json is sufficient — no SSE session
    needed.
    """
    client = http_client or httpx.AsyncClient()
    try:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        tools = data.get("result", {}).get("tools", [])
        return sorted(t["name"] for t in tools)
    finally:
        if http_client is None:
            await client.aclose()
