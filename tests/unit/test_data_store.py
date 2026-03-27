"""Tests for FileSystemUserDataStore."""

import os
import pytest

from mcp_app.data_store import FileSystemUserDataStore


@pytest.fixture
def store(tmp_path):
    os.environ["APP_USERS_PATH"] = str(tmp_path / "users")
    yield FileSystemUserDataStore(app_name="test-app")
    del os.environ["APP_USERS_PATH"]


def test_save_and_load(store):
    store.save("alice@test.com", "daily/2026-01-01", [{"food": "apple"}])
    data = store.load("alice@test.com", "daily/2026-01-01")
    assert data == [{"food": "apple"}]


def test_load_missing_returns_none(store):
    assert store.load("nobody@test.com", "daily/2026-01-01") is None


def test_list_users_empty(store):
    assert store.list_users() == []


def test_list_users_after_save(store):
    store.save("alice@test.com", "auth", {"email": "alice@test.com"})
    store.save("bob@test.com", "auth", {"email": "bob@test.com"})
    users = store.list_users()
    assert set(users) == {"alice@test.com", "bob@test.com"}


def test_delete(store):
    store.save("alice@test.com", "auth", {"email": "alice@test.com"})
    store.delete("alice@test.com", "auth")
    assert store.load("alice@test.com", "auth") is None


def test_email_encoding(store):
    store.save("user@example.com", "test", {"ok": True})
    # Directory should use ~ not @
    user_dir = store.base / "user~example.com"
    assert user_dir.exists()
    assert (user_dir / "test.json").exists()


def test_email_decoding_in_list(store):
    store.save("user@example.com", "auth", {})
    users = store.list_users()
    assert "user@example.com" in users


def test_overwrite(store):
    store.save("alice@test.com", "data", {"v": 1})
    store.save("alice@test.com", "data", {"v": 2})
    data = store.load("alice@test.com", "data")
    assert data == {"v": 2}
