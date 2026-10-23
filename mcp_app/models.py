"""Data models for user records."""

from datetime import datetime
from pydantic import BaseModel


STATUS_APPROVED = "approved"
STATUS_PENDING = "pending"
STATUS_BLOCKED = "blocked"
USER_STATUSES = (STATUS_APPROVED, STATUS_PENDING, STATUS_BLOCKED)


class UserAuthRecord(BaseModel):
    """Auth-specific data for a user. This is what the auth framework
    stores and retrieves — not app data like food logs or orders.

    ``status`` is the admission state: ``approved`` (the default, and what
    a record without the field means) runs tools; ``pending`` signed in
    under the allowlist policy and waits for an administrator; ``blocked``
    is refused whatever the policy says. Records are never deleted to
    refuse someone, because under open admission the next sign-in would
    recreate them.
    """

    email: str
    created: datetime | None = None
    revoke_after: float | None = None
    status: str = STATUS_APPROVED


class UserRecord(BaseModel):
    """Full user record — auth fields + app profile.

    Loaded once at auth time, set on the current_user ContextVar.
    The profile field holds whatever the app stored at registration
    time — mcp-app does not interpret it.
    """

    email: str
    created: datetime | None = None
    revoke_after: float | None = None
    status: str = STATUS_APPROVED
    profile: dict | None = None
