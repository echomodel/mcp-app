"""Data models for auth records."""

from datetime import datetime
from pydantic import BaseModel


class UserAuthRecord(BaseModel):
    """Auth-specific data for a user. This is what the auth framework
    stores and retrieves — not app data like food logs or orders."""

    email: str
    created: datetime | None = None
    revoke_after: float | None = None
