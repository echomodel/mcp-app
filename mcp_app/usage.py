"""Usage accounting: who called which tool, how often, aggregated for admins.

Every tool call is counted in memory per (day, user, tool, outcome) and the
counts are flushed to the data volume on a timer and at shutdown, never
written per call: on an object-store mount a per-call write would be a
whole-object rewrite, and the report tolerates losing the last flush
interval on a crash. Each process writes its own file for the day
(``usage/YYYY-MM-DD/<instance>.json``, cumulative for that process and
day), so several instances never contend for one object; a report sums
every file in its window.

Emails are stored in the counters, because the report must attribute
calls, but they leave the server only masked (``al*****@e***.com``); the
usage files sit beside the user directories on the same volume and are
no more exposed than the data they describe.

The report (``usage_report``) is a framework tool registered on every app.
Over HTTP it answers only administrators (``ADMIN_EMAILS``); over stdio
the single local user is the operator.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("mcp_app.usage")

ENV_FLUSH_SECONDS = "USAGE_FLUSH_SECONDS"
DEFAULT_FLUSH_SECONDS = 60
USAGE_DIRNAME = "usage"
REPORT_TOOL_NAME = "usage_report"


def mask_email(email: str) -> str:
    """``alice@example.com`` -> ``al*****@e***.com``: enough to recognise
    your own address, not enough to address anyone."""
    local, _, domain = email.partition("@")
    if not domain:
        return local[:2] + "*****"
    tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
    return f"{local[:2]}*****@{domain[:1]}***{'.' + tld if tld else ''}"


def usage_root(store) -> Path | None:
    """Where usage files live for a store, or ``None`` when the store has
    no filesystem base (a custom backend) and usage is not recorded."""
    base = getattr(store, "base", None)
    if base is None:
        return None
    return Path(base).parent / USAGE_DIRNAME


class UsageRecorder:
    """In-memory counters for one process, flushed to ``root`` periodically."""

    def __init__(self, root: Path | None, flush_seconds: float | None = None):
        self.root = root
        self.instance = uuid.uuid4().hex[:8]
        self.flush_seconds = flush_seconds or float(
            os.environ.get(ENV_FLUSH_SECONDS, "").strip() or DEFAULT_FLUSH_SECONDS
        )
        # day -> email -> tool -> {"ok": n, "error": n}
        self._counts: dict[str, dict[str, dict[str, dict[str, int]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(lambda: {"ok": 0, "error": 0}))
        )
        self._dirty: set[str] = set()
        self._task: asyncio.Task | None = None

    @property
    def enabled(self) -> bool:
        return self.root is not None

    def record(self, email: str, tool: str, ok: bool) -> None:
        if not self.enabled:
            return
        day = datetime.now(timezone.utc).date().isoformat()
        self._counts[day][email.lower()][tool]["ok" if ok else "error"] += 1
        self._dirty.add(day)

    def flush(self) -> None:
        """Write every day that changed since the last flush."""
        if not self.enabled or not self._dirty:
            return
        for day in sorted(self._dirty):
            path = self.root / day / f"{self.instance}.json"
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "instance": self.instance,
                    "day": day,
                    "flushed": datetime.now(timezone.utc).isoformat(),
                    "users": {
                        email: dict(tools) for email, tools in self._counts[day].items()
                    },
                }
                path.write_text(json.dumps(payload, indent=1))
            except OSError as exc:
                logger.warning("usage flush failed for %s: %s", path, exc)
                return
        self._dirty.clear()

    async def run(self) -> None:
        """Flush on a timer until cancelled; a final flush on the way out."""
        try:
            while True:
                await asyncio.sleep(self.flush_seconds)
                self.flush()
        finally:
            self.flush()

    def start(self) -> None:
        if self.enabled and self._task is None:
            self._task = asyncio.get_running_loop().create_task(self.run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.flush()


def week_window(week: str, today: date | None = None) -> tuple[date, date]:
    """Monday-to-Sunday window: ``current`` runs Monday through today,
    ``prior`` is the previous full week. Both ends inclusive."""
    today = today or datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    if week == "current":
        return monday, today
    if week == "prior":
        return monday - timedelta(days=7), monday - timedelta(days=1)
    raise ValueError("week must be 'current' or 'prior'")


def read_usage(root: Path | None, start: date, end: date) -> dict[str, dict[str, dict[str, int]]]:
    """Sum every instance file in the window: email -> tool -> counts."""
    totals: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"ok": 0, "error": 0})
    )
    if root is None or not root.exists():
        return totals
    day = start
    while day <= end:
        day_dir = root / day.isoformat()
        if day_dir.is_dir():
            for path in day_dir.glob("*.json"):
                try:
                    payload = json.loads(path.read_text())
                except (OSError, json.JSONDecodeError):
                    continue
                for email, tools in (payload.get("users") or {}).items():
                    for tool, counts in tools.items():
                        totals[email][tool]["ok"] += int(counts.get("ok", 0))
                        totals[email][tool]["error"] += int(counts.get("error", 0))
        day += timedelta(days=1)
    return totals


def build_report(
    usage: dict[str, dict[str, dict[str, int]]],
    *,
    week: str,
    start: date,
    end: date,
    total_users: int,
    created: dict[str, datetime | None],
    top: int = 10,
) -> dict:
    """Assemble the JSON report. ``created`` maps email -> record creation
    time (for new-user counting); emails appear masked in the output."""
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    new_users = sum(
        1 for ts in created.values()
        if ts is not None and start_dt <= _utc(ts) < end_dt
    )
    per_user = []
    tool_totals: dict[str, int] = defaultdict(int)
    for email, tools in usage.items():
        calls = sum(c["ok"] + c["error"] for c in tools.values())
        errors = sum(c["error"] for c in tools.values())
        for tool, c in tools.items():
            tool_totals[tool] += c["ok"] + c["error"]
        per_user.append({
            "user": mask_email(email),
            "calls": calls,
            "errors": errors,
            "tools_used": len(tools),
            "tools": {tool: c["ok"] + c["error"] for tool, c in sorted(tools.items())},
        })
    per_user.sort(key=lambda u: (-u["calls"], u["user"]))
    return {
        "schema_version": "1",
        "week": week,
        "window": {"start": start.isoformat(), "end": end.isoformat(), "timezone": "UTC"},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "users": {
            "total": total_users,
            "new": new_users,
            "active": len(per_user),
        },
        "tool_calls": {
            "total": sum(u["calls"] for u in per_user),
            "errors": sum(u["errors"] for u in per_user),
            "by_tool": dict(sorted(tool_totals.items(), key=lambda kv: (-kv[1], kv[0]))),
        },
        "top_users": per_user[:top],
    }


def _utc(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


async def usage_report(week: str = "current") -> dict:
    """Usage of this deployment for a week: users, tool calls, top users.

    Administrators only; the tool is not listed for anyone else. Returns
    JSON with the window (Monday to Sunday, UTC; ``current`` runs Monday
    through today, ``prior`` is the previous full week), user totals
    (total, new, active), tool calls (total, errors, per tool), and the
    most active users with masked emails, the tools each used and their
    call counts. Call it again any time: it recomputes from the recorded
    counters, so a current-week report grows as the week goes on and a
    prior-week report is stable.

    Args:
        week: ``current`` (default) or ``prior``.
    """
    import mcp_app
    from mcp_app.bridge import DataStoreAuthAdapter

    start, end = week_window(week)
    store = mcp_app.get_store()
    recorder = getattr(mcp_app, "_usage_recorder", None)
    if recorder is not None:
        recorder.flush()
    adapter = DataStoreAuthAdapter(store)
    records = await adapter.list()
    report = build_report(
        read_usage(usage_root(store), start, end),
        week=week,
        start=start,
        end=end,
        total_users=await adapter.count(),
        created={r.email: r.created for r in records},
    )
    if usage_root(store) is None:
        report["note"] = "usage is not recorded for this store backend; counts are zero"
    return report
