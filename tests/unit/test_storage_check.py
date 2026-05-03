"""Tests for the data-dir startup verification."""

import logging
import os
import sys

import pytest

from mcp_app import storage_check
from mcp_app.storage_check import (
    StorageCheckResult,
    _matches_required,
    detect_fs_type,
    get_last_check,
    reset_last_check,
    verify_storage,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_last_check()
    yield
    reset_last_check()


# --- matching semantics ---

def test_matches_exact():
    assert _matches_required("apfs", "apfs")


def test_matches_prefix_on_dot_boundary():
    assert _matches_required("fuse.gcsfuse", "fuse")


def test_does_not_match_substring_without_dot():
    # 'fuse' must not match 'fuser', 'confused', etc. — only 'fuse' itself
    # or 'fuse.<something>'.
    assert not _matches_required("fuser", "fuse")


def test_matches_comma_separated_list():
    assert _matches_required("nfs", "fuse,nfs,apfs")
    assert _matches_required("fuse.gcsfuse", "fuse,nfs,apfs")


def test_matches_ignores_whitespace_and_empties():
    assert _matches_required("apfs", " apfs , , ")


def test_no_match_returns_false():
    assert not _matches_required("overlay", "fuse,nfs")


# --- inspection ---

def test_detect_fs_type_returns_known_for_existing_path(tmp_path):
    fs_type, _ = detect_fs_type(tmp_path)
    # On any supported platform tmp_path is on a real fs that one of the
    # detectors recognizes; the only acceptable fallback is 'unknown'.
    assert isinstance(fs_type, str)
    assert fs_type != ""


# --- verify_storage cases ---

def test_unset_logs_info_data_dir_line_and_debug_skip(tmp_path, caplog):
    target = tmp_path / "users"
    with caplog.at_level(logging.DEBUG, logger="mcp_app.startup"):
        result = verify_storage(target, required_fs_type=None)

    assert result.fs_type_check == "unset"
    assert result.required_fs_type is None
    assert result.exists is True  # created on startup
    assert result.writable is True

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("data_dir" in r.message and "required_fs_type=<unset>" in r.message for r in info_records), (
        f"Expected an info data_dir line with required_fs_type=<unset>; got {[r.message for r in info_records]}"
    )
    assert any("REQUIRED_FS_TYPE is unset" in r.message for r in debug_records), (
        "Expected a debug entry noting the assertion was deliberately skipped."
    )


def test_unset_does_not_exit(tmp_path):
    # Default exit_on_mismatch=True should never fire when the check is unset.
    verify_storage(tmp_path / "users", required_fs_type=None)


def test_set_and_matches_logs_single_info_with_check_ok(tmp_path, caplog):
    target = tmp_path / "users"
    target.mkdir(parents=True)
    actual_fs, _ = detect_fs_type(target)
    if actual_fs == "unknown":
        pytest.skip("fs_type detection unavailable on this platform")

    with caplog.at_level(logging.INFO, logger="mcp_app.startup"):
        result = verify_storage(target, required_fs_type=actual_fs)

    assert result.fs_type_check == "ok"
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("fs_type_check=ok" in r.message for r in info_records), (
        f"Expected info entry with fs_type_check=ok; got {[r.message for r in info_records]}"
    )


def test_set_and_mismatches_logs_error_and_exits_nonzero(tmp_path, caplog):
    target = tmp_path / "users"
    target.mkdir(parents=True)

    with caplog.at_level(logging.ERROR, logger="mcp_app.startup"):
        with pytest.raises(SystemExit) as exc_info:
            verify_storage(
                target,
                required_fs_type="definitely-not-a-real-fs-type-xyz123",
            )

    assert exc_info.value.code == 1
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("fs_type_check=mismatch" in r.message for r in error_records), (
        f"Expected error entry with fs_type_check=mismatch; got {[r.message for r in error_records]}"
    )


def test_set_and_mismatches_no_exit_when_disabled(tmp_path):
    """exit_on_mismatch=False is the test-only escape hatch."""
    target = tmp_path / "users"
    target.mkdir(parents=True)
    result = verify_storage(
        target,
        required_fs_type="definitely-not-a-real-fs-type-xyz123",
        exit_on_mismatch=False,
    )
    assert result.fs_type_check == "mismatch"


# --- caching for /health (#39 dependency) ---

def test_get_last_check_returns_most_recent_result(tmp_path):
    assert get_last_check() is None
    verify_storage(tmp_path / "users", required_fs_type=None)
    cached = get_last_check()
    assert isinstance(cached, StorageCheckResult)
    assert cached.fs_type_check == "unset"


def test_get_last_check_overwritten_on_new_call(tmp_path):
    verify_storage(tmp_path / "first", required_fs_type=None)
    first = get_last_check()
    verify_storage(tmp_path / "second", required_fs_type=None)
    second = get_last_check()
    assert first is not second
    assert "second" in second.path


# --- empty REQUIRED_FS_TYPE behaves like unset ---

def test_empty_string_required_fs_type_is_treated_as_unset(tmp_path):
    """An env var set to '' (empty) is the operator's way of explicitly
    setting nothing — same effect as not setting the var at all."""
    result = verify_storage(tmp_path / "users", required_fs_type="")
    assert result.fs_type_check == "unset"
    assert result.required_fs_type is None
