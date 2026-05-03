"""Startup-time data-directory introspection and optional fs_type assertion.

mcp-app reports facts about the resolved data directory (path, fs_type,
writable, free space) and optionally asserts an operator-supplied
REQUIRED_FS_TYPE. Reporting is unconditional and lives in the log; the
assertion is opt-in via env var. The framework never enforces a
particular filesystem on its own — operators decide what is acceptable
for their deployment.

The result of the most recent ``verify_storage`` call is cached at
module level so other surfaces (e.g., the ``/health`` endpoint, an
admin diagnostic surface) can read the same verdict without re-probing
the filesystem on the request hot path.

Public surface:

- ``verify_storage(path, required_fs_type, ...)`` — run once at
  startup. Logs the data_dir line, performs the optional assertion,
  caches the result, and exits non-zero on mismatch unless told
  otherwise.
- ``get_last_check()`` — read the cached startup result.
- ``StorageCheckResult`` — the structured verdict.
"""

import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mcp_app.startup")

_FS_TYPE_CHECK_OK = "ok"
_FS_TYPE_CHECK_MISMATCH = "mismatch"
_FS_TYPE_CHECK_UNSET = "unset"
_FS_TYPE_CHECK_PATH_MISSING = "path_missing"
_FS_TYPE_CHECK_NOT_WRITABLE = "not_writable"


@dataclass
class StorageCheckResult:
    """Verdict on the data directory at startup.

    `fs_type_check` values:
      - ``ok``: REQUIRED_FS_TYPE was set and the actual fs_type matched.
      - ``mismatch``: REQUIRED_FS_TYPE was set and the actual fs_type did
        not match. Process should exit non-zero.
      - ``path_missing``: REQUIRED_FS_TYPE was set but the path didn't
        exist (and creation was disabled or failed).
      - ``not_writable``: REQUIRED_FS_TYPE was set but the path is not
        writable.
      - ``unset``: REQUIRED_FS_TYPE was not provided; no assertion ran.
    """

    path: str
    exists: bool
    writable: bool
    fs_type: str
    free_bytes: int
    required_fs_type: Optional[str]
    fs_type_check: str
    mount_source: Optional[str] = None


_last_result: Optional[StorageCheckResult] = None


def get_last_check() -> Optional[StorageCheckResult]:
    """Return the cached result of the most recent ``verify_storage`` call."""
    return _last_result


def reset_last_check() -> None:
    """Clear the cache. Test-only helper; production code should not call this."""
    global _last_result
    _last_result = None


def _detect_fs_type_linux(resolved: str) -> Optional[tuple[str, str]]:
    """Find the longest mountpoint prefix of ``resolved`` in /proc/self/mountinfo."""
    mountinfo = Path("/proc/self/mountinfo")
    if not mountinfo.exists():
        return None
    best: Optional[tuple[str, str]] = None
    best_len = -1
    try:
        for line in mountinfo.read_text().splitlines():
            # Format: "36 35 98:0 /root /mountpoint opts - fstype source super-opts"
            sep = line.find(" - ")
            if sep == -1:
                continue
            left = line[:sep].split()
            right = line[sep + 3:].split()
            if len(left) < 5 or len(right) < 2:
                continue
            mountpoint = left[4]
            fs_type = right[0]
            source = right[1]
            if resolved == mountpoint or resolved.startswith(mountpoint.rstrip("/") + "/"):
                if len(mountpoint) > best_len:
                    best = (fs_type, source)
                    best_len = len(mountpoint)
    except OSError:
        return None
    return best


def _detect_fs_type_mount_command(resolved: str) -> Optional[tuple[str, str]]:
    """Fallback for macOS/BSD: parse `/sbin/mount` output.

    macOS line shape: ``/dev/disk1s1 on / (apfs, local, journaled)``.
    We pick the longest mountpoint that is a prefix of ``resolved``.
    """
    candidates = ["/sbin/mount", "/usr/sbin/mount", "mount"]
    out = None
    for cmd in candidates:
        try:
            res = subprocess.run([cmd], capture_output=True, text=True, timeout=2)
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            continue
        if res.returncode == 0:
            out = res.stdout
            break
    if not out:
        return None
    best: Optional[tuple[str, str]] = None
    best_len = -1
    for line in out.splitlines():
        if " on " not in line or " (" not in line:
            continue
        try:
            src_part, rest = line.split(" on ", 1)
            mp_part, info_part = rest.split(" (", 1)
            fs_type = info_part.split(",")[0].strip().rstrip(")").strip()
            mountpoint = mp_part.strip()
        except ValueError:
            continue
        if resolved == mountpoint or resolved.startswith(mountpoint.rstrip("/") + "/"):
            if len(mountpoint) > best_len:
                best = (fs_type, src_part.strip())
                best_len = len(mountpoint)
    return best


def detect_fs_type(path: Path) -> tuple[str, Optional[str]]:
    """Detect (fs_type, mount_source) for ``path``. Returns ``("unknown", None)`` on failure."""
    try:
        resolved = str(path.resolve())
    except OSError:
        resolved = str(path)
    found = _detect_fs_type_linux(resolved) or _detect_fs_type_mount_command(resolved)
    if found:
        return found
    return "unknown", None


def _check_writable(path: Path) -> bool:
    if not path.exists():
        return False
    sentinel = path / f".mcp_app_write_check_{os.getpid()}"
    try:
        sentinel.write_text("")
    except OSError:
        return False
    try:
        sentinel.unlink()
    except OSError:
        pass
    return True


def _free_bytes(path: Path) -> int:
    try:
        target = path if path.exists() else path.parent
        st = os.statvfs(target)
        return st.f_bavail * st.f_frsize
    except OSError:
        return -1


def _matches_required(actual: str, required: str) -> bool:
    """Match REQUIRED_FS_TYPE: comma-separated list, prefix-friendly.

    "fuse" matches "fuse.gcsfuse" (prefix on a "." boundary).
    "fuse,nfs" matches either. Whitespace around commas is ignored.
    Empty entries are skipped.
    """
    for piece in required.split(","):
        piece = piece.strip()
        if not piece:
            continue
        if actual == piece or actual.startswith(piece + "."):
            return True
    return False


def verify_storage(
    path,
    required_fs_type: Optional[str] = None,
    *,
    create: bool = True,
    exit_on_mismatch: bool = True,
) -> StorageCheckResult:
    """Inspect the data directory, log a startup data_dir line, optionally enforce REQUIRED_FS_TYPE.

    Args:
        path: Resolved data-directory path.
        required_fs_type: Operator-declared expected fs_type. None or
            empty means no assertion. Comma-separated for alternatives;
            prefix matches on "." boundary.
        create: If True, create the directory if it doesn't exist
            (mirrors what ``FileSystemUserDataStore`` does on first
            write — surfacing the would-be path now, not on first save).
        exit_on_mismatch: When ``required_fs_type`` is set and the
            actual fs_type doesn't match (or path is missing or not
            writable), call ``sys.exit(1)``. Tests pass False to
            assert log content without aborting the test process.

    Returns the ``StorageCheckResult`` and caches it on the module so
    later surfaces can read it without re-probing.
    """
    global _last_result
    p = Path(path)

    if create:
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    exists = p.exists()
    writable = _check_writable(p) if exists else False
    fs_type, mount_source = detect_fs_type(p)
    free = _free_bytes(p)

    required = required_fs_type or None
    if required is None:
        check = _FS_TYPE_CHECK_UNSET
    elif not exists:
        check = _FS_TYPE_CHECK_PATH_MISSING
    elif not writable:
        check = _FS_TYPE_CHECK_NOT_WRITABLE
    elif _matches_required(fs_type, required):
        check = _FS_TYPE_CHECK_OK
    else:
        check = _FS_TYPE_CHECK_MISMATCH

    result = StorageCheckResult(
        path=str(p),
        exists=exists,
        writable=writable,
        fs_type=fs_type,
        free_bytes=free,
        required_fs_type=required,
        fs_type_check=check,
        mount_source=mount_source,
    )
    _last_result = result

    fields = (
        f"path={result.path} exists={str(result.exists).lower()} "
        f"writable={str(result.writable).lower()} "
        f"fs_type={result.fs_type} free_bytes={result.free_bytes} "
        f"required_fs_type={result.required_fs_type or '<unset>'}"
    )

    if check == _FS_TYPE_CHECK_UNSET:
        # Surface the no-op check at debug level so an operator looking
        # for "did the assertion run?" can see it was deliberately skipped.
        logger.debug("REQUIRED_FS_TYPE is unset; no fs_type assertion performed")
        logger.info(f"data_dir {fields}")
    elif check == _FS_TYPE_CHECK_OK:
        logger.info(f"data_dir {fields} fs_type_check=ok")
    else:
        logger.error(f"data_dir {fields} fs_type_check={check}")
        if exit_on_mismatch:
            sys.exit(1)

    return result
