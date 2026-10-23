"""Shared fixtures for mcp-app's own unit tests."""

import pytest

from mcp_app.testing.issuer import TestIssuer

OPERATOR = "operator@example.com"


@pytest.fixture(scope="session")
def issuer():
    return TestIssuer()


@pytest.fixture
def auth_env(tmp_path, monkeypatch):
    """Isolated store plus the one administrator every admin test signs in as."""
    monkeypatch.setenv("APP_USERS_PATH", str(tmp_path / "users"))
    monkeypatch.setenv("ADMIN_EMAILS", OPERATOR)
    for var in ("AUTH_ISSUER", "AUTH_AUDIENCE", "AUTH_EMAIL_CLAIM", "AUTH_JWKS_URI",
                "AUTH_ADMISSION", "MAX_USERS"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path
