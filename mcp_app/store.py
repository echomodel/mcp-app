"""UserAuthStore protocol — the contract auth uses to manage users."""

from typing import Protocol
from mcp_app.models import UserAuthRecord


class UserAuthStore(Protocol):
    """Interface for auth user management.

    Solutions implement this against their own storage — filesystem,
    database, Firestore, etc. The auth framework calls these methods
    for token verification, user registration, listing, and revocation.
    """

    async def get(self, email: str) -> UserAuthRecord | None:
        """Get auth record for a user. Returns None if not found."""
        ...

    async def list(self) -> list[UserAuthRecord]:
        """List all users with auth records."""
        ...

    async def save(self, record: UserAuthRecord) -> None:
        """Create or update a user's auth record."""
        ...

    async def delete(self, email: str) -> None:
        """Delete a user's auth record."""
        ...
