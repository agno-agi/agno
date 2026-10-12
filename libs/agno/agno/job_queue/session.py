"""Session ordering for jobs whose component requires one active turn at a time."""

from typing import Any, Dict, Iterable

LIVE_STATUSES = ("queued", "running")


def is_serialized(job: Dict[str, Any]) -> bool:
    return (job.get("payload") or {}).get("serialize_session") is True


def session_identity(job: Dict[str, Any]) -> tuple:
    # User/deployment affinity does not create a different mutable component session.
    return job.get("component_type"), job.get("component_id"), job.get("session_id")


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


def session_blocked(job: Dict[str, Any], others: Iterable[Dict[str, Any]]) -> bool:
    if not is_serialized(job):
        return False
    order = (session_seq(job), job["id"])
    for other in others:
        if other["id"] == job["id"] or session_identity(other) != session_identity(job):
            continue
        if not is_serialized(other):
            continue
        if other["status"] == "running":
            return True
        if job["status"] == "queued" and other["status"] == "queued" and (session_seq(other), other["id"]) < order:
            return True
    return False


def _session_seq_sql(table: Any) -> Any:
    from sqlalchemy import BigInteger, func

    return func.coalesce(table.c.payload["session_seq"].astext.cast(BigInteger), 0)


def _same_session_sql(table: Any, other: Any) -> Any:
    from sqlalchemy import and_

    return and_(
        other.c.component_type == table.c.component_type,
        other.c.component_id == table.c.component_id,
        other.c.session_id == table.c.session_id,
    )


def next_session_seq_query(table: Any, job: Dict[str, Any]) -> Any:
    """SQL equivalent of next_session_seq; run while holding the session advisory lock."""
    from sqlalchemy import func, select

    component_type, component_id, session_id = session_identity(job)
    return select(func.coalesce(func.max(_session_seq_sql(table)), 0) + 1).where(
        table.c.component_type == component_type,
        table.c.component_id == component_id,
        table.c.session_id == session_id,
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
            _same_session_sql(table, other),
            other_serialized,
            or_(
                other.c.status == "running",
                and_(table.c.status == "queued", other.c.status == "queued", earlier),
            ),
        )
        .correlate(table)
    )
    return or_(~serialized, ~exists(blocker))


def session_claim_lock_key(namespace: str, job: Dict[str, Any]) -> int:
    """A stable Postgres advisory-lock key scoped to one queue and component session."""
    import hashlib
    import json

    value = json.dumps((namespace, session_identity(job)), separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big", signed=True)
