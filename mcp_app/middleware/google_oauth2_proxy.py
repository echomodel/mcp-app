"""Google OAuth2 proxy middleware for apps wrapping Google APIs."""

import time

from mcp_app.middleware.credential_proxy import CredentialProxyMiddleware


class GoogleOAuth2ProxyMiddleware(CredentialProxyMiddleware):
    """Credential proxy for Google APIs with OAuth2 token refresh.

    Reads stored authorized_user credentials, refreshes the access
    token if expired, writes the refreshed token back to the store.
    Requires google-auth package.
    """

    def resolve_access_token(self, email: str, credential: dict) -> str:
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
        except ImportError:
            raise ValueError(
                "google-oauth2-proxy requires the google-auth package. "
                "Install with: pip install google-auth"
            )

        creds = Credentials.from_authorized_user_info(credential)

        if not creds.valid:
            if not creds.refresh_token:
                raise ValueError("Credential missing refresh_token — cannot refresh")
            creds.refresh(Request())

            # Write refreshed token back to store
            updated = {**credential, "token": creds.token}
            if creds.expiry:
                updated["expiry"] = creds.expiry.isoformat()
            self.store.save(email, "credential", updated)

            # Update cache with fresh token
            self._cache[email] = (creds.token, time.monotonic())

        return creds.token
