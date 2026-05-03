"""Unit tests for the structured /health response builder."""

from unittest.mock import patch

import pytest

from mcp_app.health_check import (
    HealthStatus,
    PersistentStorageStatus,
    build_admin_health_detail,
    build_health_response,
)
from mcp_app.storage_check import StorageCheckResult, reset_last_check


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_last_check()
    yield
    reset_last_check()


def _stub_check(fs_type_check: str, **overrides) -> StorageCheckResult:
    defaults = dict(
        path="/tmp/test/users",
        exists=True,
        writable=True,
        fs_type="apfs",
        free_bytes=1_000_000,
        required_fs_type=None,
        fs_type_check=fs_type_check,
        mount_source="/dev/disk1s1",
    )
    defaults.update(overrides)
    return StorageCheckResult(**defaults)


# --- response shape ---

def test_response_has_status_and_checks_keys():
    body, code = build_health_response()
    assert "status" in body
    assert "checks" in body
    assert isinstance(body["checks"], dict)
    assert isinstance(code, int)


def test_no_storage_check_yields_healthy_with_empty_checks():
    """Custom store backends that don't trigger verify_storage shouldn't crash /health."""
    body, code = build_health_response()
    assert body == {"status": "healthy", "checks": {}}
    assert code == 200


# --- per-state mapping for persistent_storage ---

@pytest.mark.parametrize("internal,public,severity,code", [
    ("ok", "verified", "healthy", 200),
    ("unset", "unverified", "degraded", 200),
    ("mismatch", "unavailable", "unhealthy", 503),
    ("path_missing", "unavailable", "unhealthy", 503),
    ("not_writable", "unavailable", "unhealthy", 503),
])
def test_persistent_storage_states(internal, public, severity, code):
    with patch("mcp_app.health_check.get_last_check", return_value=_stub_check(internal)):
        body, http_code = build_health_response()

    assert body["status"] == severity
    assert body["checks"]["persistent_storage"] == public
    assert http_code == code


def test_unhealthy_returns_503():
    """The 503 mapping is what makes platform health checks deflect traffic."""
    with patch("mcp_app.health_check.get_last_check", return_value=_stub_check("mismatch")):
        body, code = build_health_response()
    assert code == 503
    assert body["status"] == "unhealthy"


def test_unverified_is_degraded_not_unhealthy():
    """Without REQUIRED_FS_TYPE opt-in we cannot say the env is broken —
    only that the check wasn't run. Hence degraded, not unhealthy."""
    with patch("mcp_app.health_check.get_last_check", return_value=_stub_check("unset")):
        body, code = build_health_response()
    assert body["status"] == "degraded"
    assert code == 200  # still safe to serve


# --- public response is identity-free ---

_FORBIDDEN = {"path", "fs_type", "required_fs_type", "free_bytes", "mount_source", "writable"}


@pytest.mark.parametrize("internal", ["ok", "unset", "mismatch", "path_missing", "not_writable"])
def test_public_response_is_identity_free_under_each_outcome(internal):
    """Identifying fields belong on /admin/health, never on /health."""
    with patch("mcp_app.health_check.get_last_check", return_value=_stub_check(internal)):
        body, _ = build_health_response()

    leaked = _FORBIDDEN & set(body.keys())
    assert not leaked, f"Public response leaked: {leaked}"
    # Check value types — must be strings, not detail dicts
    for k, v in body["checks"].items():
        assert isinstance(v, str), f"checks.{k} should be string, got {type(v)}"


# --- admin surface returns full detail ---

def test_admin_detail_includes_full_storage_fields():
    cached = _stub_check("ok", path="/var/lib/foo/users", fs_type="fuse.gcsfuse",
                         required_fs_type="fuse", free_bytes=42)
    with patch("mcp_app.health_check.get_last_check", return_value=cached):
        detail = build_admin_health_detail()

    assert detail["status"] == "healthy"
    assert detail["http_status"] == 200
    storage = detail["details"]["persistent_storage"]
    assert storage["path"] == "/var/lib/foo/users"
    assert storage["fs_type"] == "fuse.gcsfuse"
    assert storage["required_fs_type"] == "fuse"
    assert storage["free_bytes"] == 42
    assert storage["fs_type_check"] == "ok"


def test_admin_detail_has_no_storage_when_check_absent():
    detail = build_admin_health_detail()
    assert detail["status"] == "healthy"
    assert detail["details"] == {}


def test_admin_detail_carries_503_for_unhealthy():
    """The admin surface reports the same http_status the public surface would."""
    with patch("mcp_app.health_check.get_last_check", return_value=_stub_check("mismatch")):
        detail = build_admin_health_detail()
    assert detail["http_status"] == 503
    assert detail["status"] == "unhealthy"


# --- enum sanity ---

def test_health_status_values_are_string_enums():
    assert HealthStatus.HEALTHY.value == "healthy"
    assert HealthStatus.DEGRADED.value == "degraded"
    assert HealthStatus.UNHEALTHY.value == "unhealthy"


def test_persistent_storage_status_values_are_string_enums():
    assert PersistentStorageStatus.VERIFIED.value == "verified"
    assert PersistentStorageStatus.UNVERIFIED.value == "unverified"
    assert PersistentStorageStatus.UNAVAILABLE.value == "unavailable"
