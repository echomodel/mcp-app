"""Structured /health response and admin-only diagnostic detail.

The public /health response is intentionally enum-only and
identity-free: status + per-check enum, nothing more. Anything that
identifies the deployment (paths, fs_type strings, REQUIRED_FS_TYPE
values, free bytes, mount source) lives only on the admin-authenticated
surface and in startup logs. This boundary lives at
``build_health_response`` and a future contributor adding a new
check must respect it — never add a "convenient" identifying field
to the public response.

Each check declares its own enum domain. The aggregation rule that
produces the top-level ``status`` is documented per check (which
states are ``unhealthy``-eligible vs ``degraded``-only). New checks
add their key to the ``checks`` object; the response shape never
changes again.
"""

from enum import Enum
from typing import Optional

from mcp_app.storage_check import get_last_check


class HealthStatus(str, Enum):
    """Top-level ``status`` enum.

    - ``healthy`` (HTTP 200): every declared check passing.
    - ``degraded`` (HTTP 200): at least one check surfaced a non-critical
      concern; safe to serve.
    - ``unhealthy`` (HTTP 503): a critical check failed; deflect traffic.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class PersistentStorageStatus(str, Enum):
    """``checks.persistent_storage`` enum.

    Names describe the contract (does writing here survive a restart),
    not the mechanism (mount, volume, FUSE, NFS). Future check keys
    follow the same convention.
    """

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    UNAVAILABLE = "unavailable"


# Severity ladder. Aggregation picks the worst entry.
_SEVERITY_ORDER = [
    HealthStatus.HEALTHY,
    HealthStatus.DEGRADED,
    HealthStatus.UNHEALTHY,
]


# Map the internal storage_check verdict to the public enum + severity
# contribution. The framework can't know whether unset (no opt-in)
# means "intentionally ephemeral on this laptop" or "production forgot
# REQUIRED_FS_TYPE", so the worst it produces without opt-in is
# `degraded`. Only an explicit opt-in violation gives `unhealthy`.
_STORAGE_CHECK_TO_PUBLIC: dict[str, tuple[PersistentStorageStatus, HealthStatus]] = {
    "ok": (PersistentStorageStatus.VERIFIED, HealthStatus.HEALTHY),
    "unset": (PersistentStorageStatus.UNVERIFIED, HealthStatus.DEGRADED),
    "mismatch": (PersistentStorageStatus.UNAVAILABLE, HealthStatus.UNHEALTHY),
    "path_missing": (PersistentStorageStatus.UNAVAILABLE, HealthStatus.UNHEALTHY),
    "not_writable": (PersistentStorageStatus.UNAVAILABLE, HealthStatus.UNHEALTHY),
}


def _persistent_storage_outcome() -> Optional[tuple[PersistentStorageStatus, HealthStatus]]:
    """Return the public outcome for the persistent_storage check, or None.

    None means the check doesn't apply — typically a non-filesystem
    store backend that the framework doesn't introspect. The ``checks``
    object simply omits the key.
    """
    cached = get_last_check()
    if cached is None:
        return None
    outcome = _STORAGE_CHECK_TO_PUBLIC.get(cached.fs_type_check)
    if outcome is None:
        # Unknown internal state — surface as unavailable + unhealthy
        # rather than silently dropping the check.
        return PersistentStorageStatus.UNAVAILABLE, HealthStatus.UNHEALTHY
    return outcome


def _aggregate(severities: list[HealthStatus]) -> HealthStatus:
    """Worst-of-N aggregation. Empty list → healthy."""
    if not severities:
        return HealthStatus.HEALTHY
    worst = 0
    for s in severities:
        idx = _SEVERITY_ORDER.index(s)
        if idx > worst:
            worst = idx
    return _SEVERITY_ORDER[worst]


def build_health_response() -> tuple[dict, int]:
    """Compute the public /health body and HTTP status code.

    The body MUST NOT include any of:
      - resolved data path
      - actual fs_type string
      - expected REQUIRED_FS_TYPE value
      - free bytes / mount source / device / inode
      - sentinel file paths

    The check enum carries the verdict; full detail lives on the admin
    surface and in startup logs. Adding an identifying field here
    breaks the public/private boundary that platform health checks,
    monitors, and uptime probes rely on.
    """
    checks: dict[str, str] = {}
    severities: list[HealthStatus] = []

    storage = _persistent_storage_outcome()
    if storage is not None:
        public_value, severity = storage
        checks["persistent_storage"] = public_value.value
        severities.append(severity)

    overall = _aggregate(severities)
    body = {"status": overall.value, "checks": checks}
    code = 503 if overall == HealthStatus.UNHEALTHY else 200
    return body, code


def build_admin_health_detail() -> dict:
    """Return full diagnostic detail for the admin-authenticated surface.

    Includes everything the public response intentionally omits, plus
    the public status/checks for convenience so a single admin call
    answers both "what would /health return?" and "why?".
    """
    body, code = build_health_response()
    detail: dict = {
        "status": body["status"],
        "http_status": code,
        "checks": dict(body["checks"]),
        "details": {},
    }

    cached = get_last_check()
    if cached is not None:
        detail["details"]["persistent_storage"] = {
            "path": cached.path,
            "exists": cached.exists,
            "writable": cached.writable,
            "fs_type": cached.fs_type,
            "free_bytes": cached.free_bytes,
            "required_fs_type": cached.required_fs_type,
            "fs_type_check": cached.fs_type_check,
            "mount_source": cached.mount_source,
        }

    return detail
