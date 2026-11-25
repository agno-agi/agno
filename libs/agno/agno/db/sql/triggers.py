"""Trigger storage shared by the SQL adapters.

The adapters resolve tables and own the transaction. Async adapters use
AsyncSession.run_sync, so these same statements execute through their async driver.
"""

import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError  # noqa: F401  (adapters catch it by this name)

from agno.db.schemas.triggers import (
    EVENT_PENDING,
    EVENT_RUNNING,
    UNFINISHED_EVENT_STATUSES,
    validate_trigger_update,
)


def _row(result: Any) -> Optional[Dict[str, Any]]:
    return dict(result._mapping) if result is not None else None


def _taken_by(triggers: Any, os_id: str) -> Any:
    """The triggers one AgentOS takes: its own, and the ones tied to no AgentOS."""
    return or_(triggers.c.os_id == os_id, triggers.c.os_id.is_(None))


# --- Triggers ---


def get_trigger(sess: Any, triggers: Any, trigger_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    stmt = select(triggers).where(triggers.c.id == trigger_id)
    if user_id is not None:
        stmt = stmt.where(triggers.c.user_id == user_id)
    return _row(sess.execute(stmt).fetchone())


def get_trigger_by_name(
    sess: Any, triggers: Any, name: str, user_id: Optional[str] = None, os_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    stmt = select(triggers).where(triggers.c.name == name)
    # Names are unique per owner: None matches only unowned triggers, never another owner's.
    stmt = stmt.where(triggers.c.user_id.is_(None) if user_id is None else triggers.c.user_id == user_id)
    # And per AgentOS: None matches only a trigger tied to no AgentOS, never another one's.
    stmt = stmt.where(triggers.c.os_id.is_(None) if os_id is None else triggers.c.os_id == os_id)
    return _row(sess.execute(stmt).fetchone())


def get_triggers(
    sess: Any,
    triggers: Any,
    source_id: Optional[str] = None,
    enabled: Optional[bool] = None,
    managed_by: Optional[str] = None,
    limit: int = 100,
    page: int = 1,
    user_id: Optional[str] = None,
    os_id: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    conditions = []
    if source_id is not None:
        conditions.append(triggers.c.source_id == source_id)
    if enabled is not None:
        conditions.append(triggers.c.enabled == enabled)
    if managed_by is not None:
        conditions.append(triggers.c.managed_by == managed_by)
    if os_id is not None:
        conditions.append(_taken_by(triggers, os_id))
    if user_id is not None:
        conditions.append(triggers.c.user_id == user_id)
    total = sess.execute(select(func.count()).select_from(triggers).where(*conditions)).scalar() or 0
    stmt = (
        select(triggers)
        .where(*conditions)
        # The id breaks ties, so paging never repeats or skips triggers created in the same second.
        .order_by(triggers.c.created_at.desc(), triggers.c.id.desc())
        .limit(limit)
        .offset((page - 1) * limit)
    )
    return [dict(row._mapping) for row in sess.execute(stmt).fetchall()], int(total)


def create_trigger(sess: Any, triggers: Any, trigger_data: Dict[str, Any]) -> Dict[str, Any]:
    sess.execute(triggers.insert().values(**trigger_data))
    return trigger_data


def update_trigger(
    sess: Any, triggers: Any, trigger_id: str, user_id: Optional[str] = None, **kwargs: Any
) -> Optional[Dict[str, Any]]:
    validate_trigger_update(kwargs)
    stmt = update(triggers).where(triggers.c.id == trigger_id)
    if user_id is not None:
        stmt = stmt.where(triggers.c.user_id == user_id)
    if sess.execute(stmt.values(updated_at=int(time.time()), **kwargs)).rowcount == 0:
        return None
    return get_trigger(sess, triggers, trigger_id, user_id=user_id)


def delete_trigger(sess: Any, triggers: Any, events: Any, trigger_id: str, user_id: Optional[str] = None) -> bool:
    stmt = triggers.delete().where(triggers.c.id == trigger_id)
    if user_id is not None:
        stmt = stmt.where(triggers.c.user_id == user_id)
    if sess.execute(stmt).rowcount == 0:
        return False
    sess.execute(events.delete().where(events.c.trigger_id == trigger_id))
    return True


# --- Trigger events ---


def create_trigger_event(sess: Any, events: Any, event_data: Dict[str, Any]) -> bool:
    """Store an event. The unique constraint refuses a delivery already stored for this trigger."""
    sess.execute(events.insert().values(**event_data))
    return True


def is_stored_trigger_event(sess: Any, events: Any, event_data: Dict[str, Any]) -> bool:
    """Whether this delivery is already stored for this trigger."""
    stmt = select(events.c.id).where(
        events.c.source_id == event_data["source_id"],
        events.c.delivery_id == event_data["delivery_id"],
        events.c.trigger_id == event_data["trigger_id"],
    )
    return sess.execute(stmt).first() is not None


def get_trigger_event(sess: Any, events: Any, event_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    stmt = select(events).where(events.c.id == event_id)
    if user_id is not None:
        stmt = stmt.where(events.c.user_id == user_id)
    return _row(sess.execute(stmt).fetchone())


def get_trigger_events(
    sess: Any,
    events: Any,
    trigger_id: Optional[str] = None,
    source_id: Optional[str] = None,
    statuses: Optional[Sequence[str]] = None,
    delivery_id: Optional[str] = None,
    event_key: Optional[str] = None,
    limit: int = 20,
    page: int = 1,
    user_id: Optional[str] = None,
    started_run: Optional[bool] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    conditions = []
    if started_run is not None:
        conditions.append(events.c.run_id.isnot(None) if started_run else events.c.run_id.is_(None))
    if trigger_id is not None:
        conditions.append(events.c.trigger_id == trigger_id)
    if source_id is not None:
        conditions.append(events.c.source_id == source_id)
    if statuses is not None:
        conditions.append(events.c.status.in_(list(statuses)))
    if delivery_id is not None:
        conditions.append(events.c.delivery_id == delivery_id)
    if event_key is not None:
        conditions.append(events.c.event_key == event_key)
    if user_id is not None:
        conditions.append(events.c.user_id == user_id)
    total = sess.execute(select(func.count()).select_from(events).where(*conditions)).scalar() or 0
    # Event ids sort in the order events were received.
    stmt = select(events).where(*conditions).order_by(events.c.id.desc()).limit(limit).offset((page - 1) * limit)
    return [dict(row._mapping) for row in sess.execute(stmt).fetchall()], int(total)


def update_trigger_event(
    sess: Any, events: Any, event_id: str, held_by: Optional[str] = None, **kwargs: Any
) -> Optional[Dict[str, Any]]:
    """Update an event. With held_by, only while that claim holds the event and it is being handled.

    The claim stays named on an event that has ended, so a write its worker makes late, such as
    handing the event back on shutdown, must not reopen it.
    """
    stmt = update(events).where(events.c.id == event_id)
    if held_by is not None:
        stmt = stmt.where(events.c.claimed_by == held_by, events.c.status == EVENT_RUNNING)
    if sess.execute(stmt.values(**kwargs)).rowcount == 0:
        return None
    return get_trigger_event(sess, events, event_id)


def claim_trigger_event(
    sess: Any,
    events: Any,
    worker_id: str,
    stale_after_seconds: int,
    triggers: Any = None,
    os_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Claim the oldest event that may run now, in one statement.

    An event may run when it is pending, or when the worker that held it stopped renewing its claim.
    It waits while an earlier event for the same trigger and key is unfinished, or while another one
    for that key is running, so one conversation has one run at a time, in the order events arrived.
    Events with no key never wait for each other.

    With ``os_id``, only an event whose trigger that AgentOS takes is claimed: several AgentOS apps
    on one database each run their own events, and replicas of one app share its events.
    """
    now = int(time.time())
    stale_before = now - stale_after_seconds
    candidate = events.alias("candidate")
    other = events.alias("other")
    same_conversation_busy = (
        select(other.c.id)
        .where(
            other.c.trigger_id == candidate.c.trigger_id,
            other.c.event_key == candidate.c.event_key,
            other.c.id != candidate.c.id,
            or_(
                and_(other.c.status.in_(UNFINISHED_EVENT_STATUSES), other.c.id < candidate.c.id),
                and_(other.c.status == EVENT_RUNNING, other.c.claimed_at > stale_before),
            ),
        )
        .exists()
    )
    own = []
    if os_id is not None and triggers is not None:
        own.append(candidate.c.trigger_id.in_(select(triggers.c.id).where(_taken_by(triggers, os_id))))
    oldest = (
        select(candidate.c.id)
        .where(
            or_(
                candidate.c.status == EVENT_PENDING,
                and_(candidate.c.status == EVENT_RUNNING, candidate.c.claimed_at <= stale_before),
            ),
            ~same_conversation_busy,
            *own,
        )
        .order_by(candidate.c.id.asc())
        .limit(1)
        # Two workers never wait on the same row; SQLite has one writer and ignores this.
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    stmt = (
        update(events)
        .where(events.c.id == oldest)
        .values(status=EVENT_RUNNING, claimed_by=worker_id, claimed_at=now)
        .returning(*events.c)
    )
    return _row(sess.execute(stmt).fetchone())


def claim_trigger_event_of(
    sess: Any, events: Any, triggers: Any, worker_id: str, stale_after_seconds: int, os_id: str
) -> Optional[Dict[str, Any]]:
    """Claim as ``claim_trigger_event`` does, among the events whose trigger one AgentOS takes."""
    return claim_trigger_event(sess, events, worker_id, stale_after_seconds, triggers=triggers, os_id=os_id)


def renew_trigger_event_claim(sess: Any, events: Any, event_id: str, worker_id: str) -> bool:
    """Keep a claim alive while its run goes on. False when the claim no longer holds the event."""
    stmt = (
        update(events)
        .where(events.c.id == event_id, events.c.claimed_by == worker_id, events.c.status == EVENT_RUNNING)
        .values(claimed_at=int(time.time()))
    )
    return sess.execute(stmt).rowcount > 0


def delete_trigger_events(sess: Any, events: Any, before: int, statuses: Sequence[str]) -> int:
    """Delete events in the given states that were stored before the cutoff."""
    stmt = events.delete().where(events.c.created_at < before, events.c.status.in_(list(statuses)))
    return int(sess.execute(stmt).rowcount or 0)
