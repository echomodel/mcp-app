"""Remote admin client — implements UserAuthStore over HTTP.

Talks to a deployed mcp-app instance's /admin REST endpoints and MCP
endpoint with an access token the caller already holds. The adapter
never mints anything: in 2.x the authorization server issues tokens,
and the token presented here is the operator's own, which the server
checks against ``ADMIN_EMAILS``.

Without a token the adapter can still do everything a deployment
exposes publicly: health, the protected-resource metadata document,
and the unauthenticated challenge an MCP client sees first.
"""

from __future__ import annotations

import httpx

from mcp_app.auth import METADATA_PATH
from mcp_app.models import UserAuthRecord, UserRecord


class NotSignedInError(RuntimeError):
    """Raised when an admin operation needs an access token and none is held.

    Typed so CLI helpers can turn it into a one-line message rather than a
    stack trace. The default message is suitable for direct display.
    """

    def __init__(self, message: str | None = None):
        super().__init__(
            message
            or "This operation needs an administrator's access token from the "
            "identity provider, and this client has none. Manage users from an "
            "MCP client signed in as an administrator, or use the local store "
            "(`connect local`)."
        )


class RemoteAuthAdapter:
    """UserAuthStore implementation backed by a remote mcp-app instance."""

    def __init__(self, base_url: str, access_token: str | None = None,
                 http_client: httpx.AsyncClient | None = None):
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self._http = http_client or httpx.AsyncClient()

    async def aclose(self) -> None:
        """Close the underlying httpx client.

        The adapter owns a persistent ``httpx.AsyncClient`` so it can
        amortize connection pool setup across multiple requests in the
        same event loop. CLI callers that wrap each verb in its own
        ``asyncio.run`` must call ``aclose`` before the loop exits —
        otherwise the client's pool ends up referencing a closed loop
        and Python 3.14's stricter asyncio raises
        ``RuntimeError: Event loop is closed`` on the next request.
        """
        await self._http.aclose()

    # -- public surface: no token needed ----------------------------------

    async def health_check(self) -> dict:
        resp = await self._http.get(f"{self.base_url}/health", timeout=10)
        return {"status": "healthy", "status_code": resp.status_code}

    async def discovery(self) -> dict:
        """The RFC 9728 protected-resource metadata document."""
        resp = await self._http.get(f"{self.base_url}{METADATA_PATH}", timeout=10)
        resp.raise_for_status()
        return resp.json()

    async def probe(self) -> dict:
        """Verify the OAuth front door without signing in.

        Hits /health, reads the metadata document (which names the issuer),
        then sends one unauthenticated MCP request and checks that the 401
        challenge points back at that document. Passing means the framework
        layer is wired: an MCP client can discover the issuer and start the
        sign-in flow. Tool listing needs a signed-in client.
        """
        result = {"url": self.base_url, "health": None, "oauth": None}
        try:
            result["health"] = await self.health_check()
        except Exception as exc:
            result["health"] = {"status": "unreachable", "error": str(exc)}
            return result

        oauth: dict = {"status": "error"}
        try:
            metadata = await self.discovery()
            oauth["issuer"] = (metadata.get("authorization_servers") or [None])[0]
            oauth["resource"] = metadata.get("resource")
            resp = await self._http.post(
                self.base_url + "/",
                headers={"Content-Type": "application/json",
                         "Accept": "application/json, text/event-stream"},
                json=_mcp_body("tools/list", None, 1),
                timeout=15,
            )
            challenge = resp.headers.get("www-authenticate", "")
            oauth["challenge"] = challenge
            if resp.status_code == 401 and "resource_metadata=" in challenge:
                oauth["status"] = "ok"
            else:
                oauth["error"] = (
                    f"expected 401 with a resource_metadata challenge, "
                    f"got {resp.status_code}"
                )
        except Exception as exc:
            oauth["error"] = str(exc)
        result["oauth"] = oauth
        return result

    # -- admin surface: the operator's token ------------------------------

    def _headers(self) -> dict:
        if not self.access_token:
            raise NotSignedInError()
        return {"Authorization": f"Bearer {self.access_token}"}

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

    async def count(self) -> int:
        return len(await self.list())

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

    # -- MCP surface: the operator acts as themselves ----------------------

    async def list_tools(self) -> list[dict]:
        """Run JSON-RPC tools/list as the token holder. Returns full tool dicts."""
        if not self.access_token:
            raise NotSignedInError()
        return await _mcp_list_tools_full(self.base_url + "/", self.access_token, self._http)

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Invoke a tool via JSON-RPC tools/call as the token holder.

        Returns an envelope with the assembled invocation (URL, headers,
        body) and the response (status_code, body) so callers can both
        replay the request and inspect the result.
        """
        if not self.access_token:
            raise NotSignedInError()
        url = self.base_url + "/"
        params = {"name": name, "arguments": arguments}
        body = _mcp_body("tools/call", params, request_id=2)
        status, response_body = await mcp_request(
            url, self.access_token, "tools/call", params, self._http, request_id=2,
        )
        return {
            "invocation": {
                "method": "POST",
                "url": url,
                "headers": _mcp_headers(self.access_token),
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


async def _mcp_list_tools_full(
    url: str, token: str, http_client: httpx.AsyncClient | None = None,
) -> list[dict]:
    """MCP tools/list round-trip — returns full tool dicts (name, description, inputSchema)."""
    _, data = await mcp_request(url, token, "tools/list", None, http_client, request_id=1, timeout=15)
    return data.get("result", {}).get("tools", [])
