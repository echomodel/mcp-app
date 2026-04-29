"""mcp-app: Config-driven MCP application framework."""

__version__ = "0.3.0"

from mcp_app.app import App
from mcp_app.context import current_user, register_profile
from mcp_app.data_store import UserDataStore, FileSystemUserDataStore
from mcp_app.models import UserAuthRecord, UserRecord
from mcp_app.store import UserAuthStore

# Set by CLI commands (stdio/serve) after building the app.
# Tools access via: from mcp_app import get_store
_store = None


def get_store() -> UserDataStore:
    """Get the active data store. Available after mcp-app stdio/serve starts."""
    if _store is None:
        raise RuntimeError("Store not initialized. Are you running via 'mcp-app stdio' or 'mcp-app serve'?")
    return _store


__all__ = [
    "App",
    "current_user",
    "register_profile",
    "get_store",
    "FileSystemUserDataStore",
    "UserAuthRecord",
    "UserRecord",
    "UserAuthStore",
    "UserDataStore",
]
