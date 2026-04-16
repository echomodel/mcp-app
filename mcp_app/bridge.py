"""Bridge between UserAuthStore and UserDataStore.

For simple apps that store everything per-user on the filesystem (or
similar), this adapter implements UserAuthStore by delegating to a
UserDataStore. The full user record (auth + profile) is stored under
one key per user.

Complex apps (e.g., MySQL-backed) skip this and implement UserAuthStore
directly against their database.
"""

from mcp_app.models import UserAuthRecord, UserRecord
from mcp_app.data_store import UserDataStore


class DataStoreAuthAdapter:
    """Implements UserAuthStore protocol backed by any UserDataStore.

    Stores the full user record (auth fields + profile) under one key.
    One store read per user gets everything.
    """

    USER_KEY = "user"

    def __init__(self, store: UserDataStore):
        self.store = store

    async def get(self, email: str) -> UserAuthRecord | None:
        data = self.store.load(email, self.USER_KEY)
        if data:
            return UserAuthRecord(**{k: v for k, v in data.items()
                                     if k in UserAuthRecord.model_fields})
        if email in self.store.list_users():
            return UserAuthRecord(email=email)
        return None

    async def get_full(self, email: str) -> UserRecord | None:
        """Load the full user record including profile."""
        data = self.store.load(email, self.USER_KEY)
        if data:
            return UserRecord(**data)
        if email in self.store.list_users():
            return UserRecord(email=email)
        return None

    async def list(self) -> list[UserAuthRecord]:
        results = []
        for email in self.store.list_users():
            data = self.store.load(email, self.USER_KEY)
            if data:
                results.append(UserAuthRecord(**{k: v for k, v in data.items()
                                                  if k in UserAuthRecord.model_fields}))
            else:
                results.append(UserAuthRecord(email=email))
        return results

    async def save(self, record: UserAuthRecord, profile: dict | None = None) -> dict:
        """Save auth record, optionally with profile data.

        If profile is provided, it's merged into the stored record.
        Existing profile data is preserved if not overwritten.
        """
        existing = self.store.load(record.email, self.USER_KEY) or {}
        updated = {**existing, **record.model_dump()}
        if profile is not None:
            updated["profile"] = profile
        self.store.save(record.email, self.USER_KEY, updated)
        return {"email": record.email}

    async def update_profile(self, email: str, updates: dict) -> dict:
        """Merge updates into a user's profile. User must exist.

        Returns the updated profile dict.
        """
        existing = self.store.load(email, self.USER_KEY)
        if not existing:
            raise KeyError(f"User not found: {email}")
        profile = existing.get("profile") or {}
        profile.update(updates)
        existing["profile"] = profile
        self.store.save(email, self.USER_KEY, existing)
        return profile

    async def delete(self, email: str) -> None:
        self.store.delete(email, self.USER_KEY)
