"""A stand-in identity provider for tests.

Generates an RSA key once and signs access tokens the way an OAuth 2.1
authorization server would, so the full HTTP stack (identity middleware,
admin endpoints, MCP tools) runs in-process against real signature
checks with no network and no real issuer.

The key set is handed to the ``App`` object directly
(``OAuthResourceServer(jwks=...)``); nothing about tests leaks into the
production configuration surface.

    issuer = TestIssuer()
    issuer.configure(app)                      # app.auth = issuer.config
    headers = issuer.headers("alice@example.com")
    client.post("/", json=..., headers=headers)

Tokens carry ``aud`` equal to the server URL the test client uses
(``http://test/`` by default; httpx's ``base_url="http://test"``), because
the server derives its expected audience from the request's ``Host``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from mcp_app.auth import OAuthResourceServer

DEFAULT_ISSUER = "https://issuer.test/"
DEFAULT_AUDIENCE = "http://test/"


class TestIssuer:
    __test__ = False  # not a pytest test class

    def __init__(
        self,
        issuer: str = DEFAULT_ISSUER,
        audience: str = DEFAULT_AUDIENCE,
        email_claim: str = "email",
        kid: str = "test-key-1",
    ):
        self.issuer = issuer
        self.audience = audience
        self.email_claim = email_claim
        self.kid = kid
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.private_pem = private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        jwk = json.loads(RSAAlgorithm.to_jwk(private.public_key()))
        jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
        self.jwks = {"keys": [jwk]}
        self.config = OAuthResourceServer(
            issuer=issuer, email_claim=email_claim, jwks=self.jwks
        )

    def configure(self, app) -> None:
        """Point an ``App`` at this issuer. Resets a stack built with other auth."""
        app.auth = self.config
        app._asgi = None

    def token(
        self,
        email: str | None,
        audience: str | None = None,
        expired: bool = False,
        **claims,
    ) -> str:
        """An access token for ``email`` (``None`` omits the email claim)."""
        now = datetime.now(timezone.utc)
        payload = {
            "iss": self.issuer,
            "aud": audience or self.audience,
            "sub": f"test|{email or 'anonymous'}",
            "iat": now - timedelta(hours=2) if expired else now,
            "exp": now - timedelta(hours=1) if expired else now + timedelta(hours=1),
        }
        if email is not None:
            payload[self.email_claim] = email
        payload.update(claims)
        return pyjwt.encode(payload, self.private_pem, algorithm="RS256", headers={"kid": self.kid})

    def headers(self, email: str, audience: str | None = None) -> dict:
        return {"Authorization": f"Bearer {self.token(email, audience)}"}
