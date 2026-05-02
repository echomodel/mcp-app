"""Remote auth adapter — implements UserAuthStore over HTTP.

Connects to a deployed mcp-app instance's /admin REST endpoints.
Mints admin JWTs locally using the signing key.
"""

from __future__ import annotations

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
        resp = await self._http.get(
            f"{self.base_url}/admin/users/{email}/profile",
            headers=self._headers(),
            timeout=10,
        )
        profile = None
        if resp.status_code == 200:
            profile = resp.json().get("profile")
        elif resp.status_code != 404:
            resp.raise_for_status()
        return UserRecord(
            email=record.email,
            created=record.created,
            revoke_after=record.revoke_after,
            profile=profile,
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

    async def get_safe_tool(self) -> dict:
        """Fetch the deployment's safe-tool declaration envelope.

        Returns the structured envelope from ``GET /admin/safe-tool``,
        which always includes ``schema_version`` and ``supported``,
        plus a ``tool`` block when a safe tool is declared, or a
        ``hint`` field otherwise.
        """
        resp = await self._http.get(
            f"{self.base_url}/admin/safe-tool",
            headers=self._headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    async def _pick_probe_user(self, user_email: str | None) -> str | None:
        """Resolve which user identity to mint a token for."""
        if user_email is not None:
            return user_email
        users = await self.list()
        active = [u for u in users if u.revoke_after is None]
        return active[0].email if active else None

    async def list_tools(self, user_email: str | None = None) -> tuple[list[dict], str]:
        """Run JSON-RPC tools/list. Returns (tools, probed_as)."""
        probed_as = await self._pick_probe_user(user_email)
        if probed_as is None:
            raise RuntimeError("No registered users — cannot mint a probe token.")
        token = self._user_token(probed_as)
        url = self.base_url + "/"
        tools = await _mcp_list_tools_full(url, token, self._http)
        return tools, probed_as

    async def call_tool(
        self,
        name: str,
        arguments: dict,
        user_email: str | None = None,
    ) -> dict:
        """Invoke a tool via JSON-RPC tools/call.

        Returns an envelope with the assembled invocation (URL, headers,
        body) and the response (status_code, body) so callers can both
        replay the request and inspect the result.
        """
        probed_as = await self._pick_probe_user(user_email)
        if probed_as is None:
            raise RuntimeError("No registered users — cannot mint a token.")
        token = self._user_token(probed_as)
        url = self.base_url + "/"
        params = {"name": name, "arguments": arguments}
        body = _mcp_body("tools/call", params, request_id=2)
        status, response_body = await mcp_request(
            url, token, "tools/call", params, self._http, request_id=2,
        )
        return {
            "probed_as": probed_as,
            "invocation": {
                "method": "POST",
                "url": url,
                "headers": _mcp_headers(token),
                "body": body,
            },
            "result": {
                "status_code": status,
                "body": response_body,
            },
        }


# Canonical JSON-RPC client for mcp-app's own admin CLI. Shared by
# probe (tools/list), safe-tool --invoke (tools/call), and the
# tools subcommand group (list/show/call). A future contributor adding a
# third consumer should reuse this helper, not re-implement.
def _mcp_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }


def _mcp_body(method: str, params: dict | None, request_id: int) -> dict:
    body = {"jsonrpc": "2.0", "method": method, "id": request_id}
    if params is not None:
        body["params"] = params
    return body


async def mcp_request(
    url: str,
    token: str,
    method: str,
    params: dict | None = None,
    http_client: httpx.AsyncClient | None = None,
    request_id: int = 1,
    timeout: float = 30,
) -> tuple[int, dict]:
    """Single-shot JSON-RPC request to a stateless mcp-app server.

    The server runs with ``stateless_http=True`` and ``json_response=True``
    so a single POST with ``Accept: application/json`` is sufficient — no
    SSE session, no 3-request handshake. Returns ``(status_code, body)``.
    """
    client = http_client or httpx.AsyncClient()
    try:
        resp = await client.post(
            url,
            headers=_mcp_headers(token),
            json=_mcp_body(method, params, request_id),
            timeout=timeout,
        )
        return resp.status_code, resp.json()
    finally:
        if http_client is None:
            await client.aclose()


async def _mcp_list_tools(
    url: str, token: str, http_client: httpx.AsyncClient | None = None,
) -> list[str]:
    """MCP tools/list round-trip — returns sorted tool names."""
    _, data = await mcp_request(url, token, "tools/list", None, http_client, request_id=1, timeout=15)
    tools = data.get("result", {}).get("tools", [])
    return sorted(t["name"] for t in tools)


async def _mcp_list_tools_full(
    url: str, token: str, http_client: httpx.AsyncClient | None = None,
) -> list[dict]:
    """MCP tools/list round-trip — returns full tool dicts (name, description, inputSchema)."""
    _, data = await mcp_request(url, token, "tools/list", None, http_client, request_id=1, timeout=15)
    return data.get("result", {}).get("tools", [])
