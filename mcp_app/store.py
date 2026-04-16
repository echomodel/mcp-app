"""UserAuthStore protocol — the contract auth and admin use to manage users."""

from typing import Protocol
from mcp_app.models import UserAuthRecord, UserRecord


class UserAuthStore(Protocol):
    """Interface for user management.

    Two implementations:
    - DataStoreAuthAdapter: local, wraps any UserDataStore
    - RemoteAuthAdapter: remote, wraps HTTP admin API

    The CLI and admin tools call these methods without knowing
    which backend is in use.
    """

    async def get(self, email: str) -> UserAuthRecord | None:
        """Get auth record for a user. Returns None if not found."""
        ...

    async def get_full(self, email: str) -> UserRecord | None:
        """Get full user record including profile."""
        ...

    async def list(self) -> list[UserAuthRecord]:
        """List all users with auth records."""
        ...

    async def save(self, record: UserAuthRecord, profile: dict | None = None) -> dict:
        """Create or update a user. Returns result dict (may include token)."""
        ...

    async def update_profile(self, email: str, updates: dict) -> dict:
        """Merge updates into a user's profile. Returns updated profile."""
        ...

    async def delete(self, email: str) -> None:
        """Delete a user's auth record."""
        ...
