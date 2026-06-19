"""mcp-app: Config-driven MCP application framework."""

__version__ = "0.9.0"

from mcp_app.app import App, SafeTool, mcp_transport
from mcp_app.context import current_user, register_profile
from mcp_app.data_store import UserDataStore, FileSystemUserDataStore
from mcp_app.models import UserAuthRecord, UserRecord
from mcp_app.store import UserAuthStore

# Set by CLI commands (stdio/serve) after building the app.
# Tools access via: from mcp_app import get_store
_store = None

# Active transport, set at startup by serve() ("http") / stdio() ("stdio").
# None until a transport starts. Reported as a fact; the framework does not
# itself enforce policy on it (see CONTRIBUTING — "reports facts, not policy").
_transport = None


def get_store() -> UserDataStore:
    """Get the active data store. Available after mcp-app stdio/serve starts."""
    if _store is None:
        raise RuntimeError("Store not initialized. Are you running via 'mcp-app stdio' or 'mcp-app serve'?")
    return _store


def get_transport() -> str | None:
    """The active transport — "http", "stdio", or None before one starts."""
    return _transport


def is_stdio() -> bool:
    """True only when affirmatively running over stdio (local single user).

    Fail-closed: returns False for HTTP and for the unknown/pre-startup state,
    so a tool gating a privileged local-only path on ``is_stdio()`` defaults
    to denying it rather than exposing it.
    """
    return _transport == "stdio"


__all__ = [
    "App",
    "SafeTool",
    "mcp_transport",
    "current_user",
    "register_profile",
    "get_store",
    "get_transport",
    "is_stdio",
    "FileSystemUserDataStore",
    "UserAuthRecord",
    "UserRecord",
    "UserAuthStore",
    "UserDataStore",
]
