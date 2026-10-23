"""Administration as MCP tools: the admin surface every app exposes.

The tools below are registered on every app and are admin-only: over HTTP
they are listed and callable only for a principal that ``is_admin``
(an ``ADMIN_EMAILS`` entry, or a machine client in ``ADMIN_CLIENT_IDS``);
to anyone else they do not exist. Over stdio the local user is the
operator. Because they are ordinary MCP tools, every standard client can
drive them: a person in Claude, a script with the SDK client and a
machine token, and a thin CLI, all through the same ``tools/call``.

They act on the admission state of user records (``models.USER_STATUSES``):

* ``users_list``     — every record with its status; the cap in force.
* ``user_register``  — approve: creates an approved record, or flips a
                       pending or blocked one to approved. Idempotent.
* ``user_block``     — refuse from now on, whatever the admission policy;
                       creates a blocked record for an email never seen,
                       so a pre-emptive block holds. Idempotent.

Backend credentials (an API-proxy app's profile) are deliberately not a
tool argument: a secret should not pass through a chat or an operator's
shell. They enter through the user-authenticated surface.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mcp_app.models import (
    STATUS_APPROVED,
    STATUS_BLOCKED,
    STATUS_PENDING,
    UserAuthRecord,
)


def _adapter():
    import mcp_app
    from mcp_app.bridge import DataStoreAuthAdapter

    return DataStoreAuthAdapter(mcp_app.get_store())


def _cap() -> int | None:
    from mcp_app.auth import Admission

    return Admission.from_env().max_users


async def users_list() -> dict:
    """Every user record on this deployment with its admission status.

    Administrators only; the tool is not listed for anyone else. Returns
    ``users`` (email, status, created) sorted pending first, then approved,
    then blocked, plus ``counts`` per status and the ``max_users`` cap in
    force (``null`` for unlimited). Emails are shown in full: this is the
    list an administrator acts on with ``user_register`` and ``user_block``.
    """
    records = await _adapter().list()
    order = {STATUS_PENDING: 0, STATUS_APPROVED: 1, STATUS_BLOCKED: 2}
    users = sorted(
        (
            {
                "email": r.email,
                "status": r.status,
                "created": r.created.isoformat() if r.created else None,
            }
            for r in records
        ),
        key=lambda u: (order.get(u["status"], 9), u["email"]),
    )
    counts = {s: 0 for s in order}
    for u in users:
        counts[u["status"]] = counts.get(u["status"], 0) + 1
    return {"users": users, "counts": counts, "max_users": _cap()}


async def user_register(email: str) -> dict:
    """Approve a user by email so their sign-in runs tools.

    Administrators only. Creates an approved record for an email that has
    never signed in (so their first request succeeds), or approves a
    pending one (someone who signed in under the allowlist policy and is
    waiting), or lifts a block. Calling it for an already approved user
    changes nothing. Returns the email, its status, and whether a record
    was created.

    Args:
        email: The user's email as the identity provider reports it.
    """
    email = email.strip().lower()
    adapter = _adapter()
    existing = await adapter.get(email)
    if existing is None:
        await adapter.save(
            UserAuthRecord(email=email, created=datetime.now(timezone.utc), status=STATUS_APPROVED)
        )
        return {"email": email, "status": STATUS_APPROVED, "created": True}
    if existing.status != STATUS_APPROVED:
        existing.status = STATUS_APPROVED
        await adapter.save(existing)
    return {"email": email, "status": STATUS_APPROVED, "created": False}


async def user_block(email: str) -> dict:
    """Refuse a user from now on, whatever the admission policy.

    Administrators only. Marks the record blocked (the next request with
    their token is a 403, and open admission will not re-admit them), or
    creates a blocked record for an email never seen so a pre-emptive
    block holds. Their data stays in place. ``user_register`` lifts it.

    Args:
        email: The user's email as the identity provider reports it.
    """
    email = email.strip().lower()
    adapter = _adapter()
    existing = await adapter.get(email)
    if existing is None:
        await adapter.save(
            UserAuthRecord(email=email, created=datetime.now(timezone.utc), status=STATUS_BLOCKED)
        )
        return {"email": email, "status": STATUS_BLOCKED, "created": True}
    if existing.status != STATUS_BLOCKED:
        existing.status = STATUS_BLOCKED
        await adapter.save(existing)
    return {"email": email, "status": STATUS_BLOCKED, "created": False}
