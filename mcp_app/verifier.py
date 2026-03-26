"""JWT verification using the UserAuthStore for user lookup and revocation."""

import os
from dataclasses import dataclass

import jwt as pyjwt

from mcp_app.store import UserAuthStore


@dataclass
class VerifiedToken:
    """Result of a successful token verification."""
    client_id: str
    scopes: list[str]
    expires_at: int | None = None


class JWTVerifier:
    """Validates JWTs and checks revocation against a UserAuthStore.

    Reads configuration from environment variables:
        SIGNING_KEY: JWT signing key (required for real use, defaults to "dev-key")
        JWT_AUD: Expected audience claim. If unset, audience is not checked.
    """

    def __init__(self, store: UserAuthStore):
        self.store = store
        self.signing_key = os.environ.get("SIGNING_KEY", "dev-key")
        self.audience = os.environ.get("JWT_AUD")

    async def verify_token(self, token: str) -> VerifiedToken | None:
        try:
            claims = pyjwt.decode(
                token,
                self.signing_key,
                algorithms=["HS256"],
                audience=self.audience,
            )
        except pyjwt.InvalidTokenError:
            return None

        email = claims.get("sub")
        if not email:
            return None

        user = await self.store.get(email)
        if not user:
            return None

        if user.revoke_after and claims.get("iat", 0) < user.revoke_after:
            return None

        return VerifiedToken(
            client_id=email,
            scopes=claims.get("scopes", []),
            expires_at=claims.get("exp"),
        )
