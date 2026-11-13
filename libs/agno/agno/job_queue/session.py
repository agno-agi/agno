"""Per-session ordering for queued tickets: at most one live turn per session, in acceptance order."""

from typing import Any, Dict, Iterable, Optional

# A paused ticket (awaiting human input) still holds its session: the turns behind it
# usually refer to its outcome.
LIVE_STATUSES = ("queued", "running", "paused")
HOLDING_STATUSES = ("running", "paused")


def is_serialized(job: Dict[str, Any]) -> bool:
    return (job.get("payload") or {}).get("serialize_session") is True


def session_identity(job: Dict[str, Any]) -> Optional[str]:
    # session_id is the sessions table's primary key: every component writing to it shares one session.
    return job.get("session_id")


def session_seq(job: Dict[str, Any]) -> int:
    return int((job.get("payload") or {}).get("session_seq") or 0)


def next_session_seq(job: Dict[str, Any], others: Iterable[Dict[str, Any]]) -> int:
    """The acceptance sequence for a new ticket: after every live ticket of its session.

    Stores call this while holding the session's enqueue lock, so the sequence follows
    store acceptance order rather than wall-clock seconds."""
    seqs = [
        session_seq(other)
        for other in others
        if is_serialized(other)
        and other["status"] in LIVE_STATUSES
        and session_identity(other) == session_identity(job)
    ]
    return max(seqs, default=0) + 1


def with_session_seq(job: Dict[str, Any], seq: int) -> Dict[str, Any]:
    return {**job, "payload": {**(job.get("payload") or {}), "session_seq": seq}}


def session_blocker(job: Dict[str, Any], others: Iterable[Dict[str, Any]]) -> Optional[str]:
    """The id of the ticket this one waits behind, or None when it may run."""
    if not is_serialized(job):
        return None
    order = (session_seq(job), job["id"])
    earliest: Optional[Dict[str, Any]] = None
    for other in others:
        if other["id"] == job["id"] or session_identity(other) != session_identity(job):
            continue
        if not is_serialized(other):
            continue
        if other["status"] in HOLDING_STATUSES:
            return other["id"]
        if job["status"] == "queued" and other["status"] == "queued" and (session_seq(other), other["id"]) < order:
            if earliest is None or (session_seq(other), other["id"]) < (session_seq(earliest), earliest["id"]):
                earliest = other
    return earliest["id"] if earliest is not None else None


def session_blocked(job: Dict[str, Any], others: Iterable[Dict[str, Any]]) -> bool:
    return session_blocker(job, others) is not None


def _session_seq_sql(table: Any) -> Any:
    from sqlalchemy import BigInteger, func

    return func.coalesce(table.c.payload["session_seq"].astext.cast(BigInteger), 0)


def next_session_seq_query(table: Any, job: Dict[str, Any]) -> Any:
    """SQL equivalent of next_session_seq; run while holding the session advisory lock."""
    from sqlalchemy import func, select

    return select(func.coalesce(func.max(_session_seq_sql(table)), 0) + 1).where(
        table.c.session_id == session_identity(job),
        table.c.payload.contains({"serialize_session": True}),
        table.c.status.in_(LIVE_STATUSES),
    )


def live_session_jobs_query(table: Any, job: Dict[str, Any]) -> Any:
    """The serialized live tickets of a job's session, for session_blocker."""
    from sqlalchemy import select

    return select(table).where(
        table.c.session_id == session_identity(job),
        table.c.payload.contains({"serialize_session": True}),
        table.c.status.in_(LIVE_STATUSES),
    )


def session_claim_condition(table: Any) -> Any:
    """SQL equivalent of session_blocked, evaluated before claiming a Postgres ticket."""
    from sqlalchemy import and_, exists, or_, select

    other = table.alias("session_predecessor")
    serialized = table.c.payload.contains({"serialize_session": True})
    other_serialized = other.c.payload.contains({"serialize_session": True})
    earlier = or_(
        _session_seq_sql(other) < _session_seq_sql(table),
        and_(_session_seq_sql(other) == _session_seq_sql(table), other.c.id < table.c.id),
    )
    blocker = (
        select(other.c.id)
        .where(
            other.c.id != table.c.id,
            other.c.session_id == table.c.session_id,
            other_serialized,
            or_(
                other.c.status.in_(HOLDING_STATUSES),
                and_(table.c.status == "queued", other.c.status == "queued", earlier),
            ),
        )
        .correlate(table)
    )
    return or_(~serialized, ~exists(blocker))


def session_claim_lock_key(namespace: str, job: Dict[str, Any]) -> int:
    """A stable Postgres advisory-lock key scoped to one queue and session."""
    import hashlib
    import json

    value = json.dumps((namespace, session_identity(job)), separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big", signed=True)
