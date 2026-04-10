"""User context — identity and profile for the current request/session."""

from contextvars import ContextVar
from typing import Type

from mcp_app.models import UserRecord


_profile_model: Type | None = None
_profile_expand: bool = True


def register_profile(model: Type, expand: bool = True) -> None:
    """Register the app's profile model (Pydantic BaseModel).

    Called by the app at import time. When a user record is loaded,
    the profile data is validated and hydrated as this model.
    If not registered, profile remains a raw dict.

    Args:
        model: Pydantic BaseModel class for profile validation.
        expand: If True, CLI generates individual flags from model
            fields (e.g., --token). If False, CLI accepts the profile
            as a JSON string or @file (e.g., --profile @creds.json).
    """
    global _profile_model, _profile_expand
    _profile_model = model
    _profile_expand = expand


def get_profile_model() -> Type | None:
    """Return the registered profile model, or None."""
    return _profile_model


def get_profile_expand() -> bool:
    """Return whether profile fields should be expanded as CLI flags."""
    return _profile_expand


def hydrate_profile(raw: dict | None) -> object:
    """Validate and hydrate raw profile data with the registered model."""
    if raw is None:
        return None
    if _profile_model is not None:
        return _profile_model(**raw)
    return raw


# No default — calling .get() without setting raises LookupError.
# HTTP: middleware sets it after JWT validation and user record load.
# stdio: CLI sets it from yaml config + store.
current_user: ContextVar[UserRecord] = ContextVar("current_user")
