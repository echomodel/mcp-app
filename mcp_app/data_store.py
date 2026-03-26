"""UserDataStore — abstract per-user JSON storage with filesystem implementation."""

import json
import os
from pathlib import Path
from typing import Protocol


class UserDataStore(Protocol):
    """Interface for per-user data storage.

    Speaks JSON objects by user identifier and key name.
    Storage-agnostic — does not assume filesystem.
    """

    def load(self, user: str, key: str) -> dict | list | None:
        """Load a JSON object for a user by key name."""
        ...

    def save(self, user: str, key: str, data) -> None:
        """Save a JSON object for a user by key name."""
        ...

    def list_users(self) -> list[str]:
        """List all user identifiers."""
        ...

    def delete(self, user: str, key: str) -> None:
        """Delete a JSON object for a user by key name."""
        ...


class FileSystemUserDataStore:
    """UserDataStore backed by the local filesystem.

    Each user gets a directory. Each key maps to a JSON file.
    Email-to-directory encoding: replace @ with ~.

    Reads base path from env var (configurable), falls back to
    XDG_DATA_HOME default.
    """

    def __init__(self, app_name: str = "app"):
        path = os.environ.get("APP_USERS_PATH")
        if not path:
            xdg = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
            path = str(xdg / app_name / "users")
        self.base = Path(path)

    @staticmethod
    def _encode_email(email: str) -> str:
        return email.replace("@", "~")

    @staticmethod
    def _decode_email(dirname: str) -> str:
        return dirname.replace("~", "@")

    def _user_dir(self, user: str) -> Path:
        return self.base / self._encode_email(user)

    def _key_path(self, user: str, key: str) -> Path:
        return self._user_dir(user) / f"{key}.json"

    def load(self, user: str, key: str) -> dict | list | None:
        path = self._key_path(user, key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def save(self, user: str, key: str, data) -> None:
        path = self._key_path(user, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, default=str))

    def list_users(self) -> list[str]:
        if not self.base.exists():
            return []
        return [
            self._decode_email(d.name)
            for d in self.base.iterdir()
            if d.is_dir()
        ]

    def delete(self, user: str, key: str) -> None:
        path = self._key_path(user, key)
        if path.exists():
            path.unlink()
