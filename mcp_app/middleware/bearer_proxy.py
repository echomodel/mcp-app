"""Bearer proxy middleware for API-proxy apps with static tokens."""

from mcp_app.middleware.credential_proxy import CredentialProxyMiddleware


class BearerProxyMiddleware(CredentialProxyMiddleware):
    """Credential proxy for static tokens (PATs, API keys).

    Reads the stored token and passes it through. No refresh.
    """

    def resolve_access_token(self, email: str, credential: dict) -> str:
        token = credential.get("token")
        if not token:
            raise ValueError("Credential missing 'token' field")
        return token
