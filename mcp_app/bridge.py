"""Bridge between UserAuthStore and UserDataStore.

For simple apps that store everything per-user on the filesystem (or
similar), this adapter implements UserAuthStore by delegating to a
UserDataStore. Auth records are stored under the key "auth".

Complex apps (e.g., MySQL-backed) skip this and implement UserAuthStore
directly against their database.
"""

from mcp_app.models import UserAuthRecord
from mcp_app.data_store import UserDataStore


class DataStoreAuthAdapter:
    """Implements UserAuthStore protocol backed by any UserDataStore."""

    AUTH_KEY = "auth"

    def __init__(self, store: UserDataStore):
        self.store = store

    async def get(self, email: str) -> UserAuthRecord | None:
        data = self.store.load(email, self.AUTH_KEY)
        if data:
            return UserAuthRecord(**data)
        if email in self.store.list_users():
            return UserAuthRecord(email=email)
        return None

    async def list(self) -> list[UserAuthRecord]:
        results = []
        for email in self.store.list_users():
            data = self.store.load(email, self.AUTH_KEY)
            if data:
                results.append(UserAuthRecord(**data))
            else:
                results.append(UserAuthRecord(email=email))
        return results

    async def save(self, record: UserAuthRecord) -> None:
        self.store.save(record.email, self.AUTH_KEY, record.model_dump())

    async def delete(self, email: str) -> None:
        self.store.delete(email, self.AUTH_KEY)
