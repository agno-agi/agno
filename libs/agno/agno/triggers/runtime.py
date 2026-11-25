"""The trigger runtime of one AgentOS: it stores declared triggers, matches deliveries and runs events."""

import hashlib
from typing import Any, Dict, List, Optional, Sequence

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.scheduler import build_run_endpoint
from agno.db.schemas.triggers import (
    CODE_MANAGED,
    EVENT_IGNORED,
    EVENT_PENDING,
    HANDLED_EVENT_STATUSES,
    NO_TRIGGER_ID,
    NOT_DECLARED_REASON,
    UNNAMED_OS_ID,
    StoredTrigger,
    TriggerEvent,
    new_trigger_event_id,
)
from agno.triggers.executor import CHECK_SENDER_KEY, TriggerExecutor, acall_db
from agno.triggers.manager import TriggerManager
from agno.triggers.poller import TriggerPoller
from agno.triggers.source import Delivery
from agno.triggers.trigger import Events, Schedule, Trigger
from agno.utils.log import log_debug

# Run metadata key that names the trigger a schedule was declared by.
SCHEDULE_TRIGGER_METADATA_KEY = "trigger_name"

# managed_by of a schedule that a trigger declared, followed by the AgentOS that declared it.
TRIGGER_MANAGED = "trigger"


def schedule_manager_of(os_id: str) -> str:
    """managed_by of the schedules the triggers of one AgentOS declare.

    The schedules table has no column for an AgentOS, so the id rides in the provenance field.
    """
    return f"{TRIGGER_MANAGED}:{os_id}"


def supports_triggers(db: Any) -> bool:
    """Whether a database stores triggers."""
    base = AsyncBaseDb if isinstance(db, AsyncBaseDb) else BaseDb
    claim = getattr(type(db), "claim_trigger_event", None)
    return claim is not None and claim is not base.claim_trigger_event


def require_trigger_storage(db: Any) -> None:
    if db is None:
        raise ValueError("Triggers need a database: pass db= to AgentOS")
    if not supports_triggers(db):
        raise ValueError(
            "Triggers are stored in PostgreSQL or SQLite: use PostgresDb, AsyncPostgresDb, SqliteDb or "
            f"AsyncSqliteDb as the AgentOS db. {type(db).__name__} does not store triggers."
        )


def session_id_for(trigger_id: str, key: str) -> str:
    """The session every event with this key continues, for one trigger."""
    return "trg_" + hashlib.sha256(f"{trigger_id}\n{key}".encode()).hexdigest()[:40]


async def adeclare_triggers(
    db: Any, triggers: Sequence[Trigger], with_schedules: bool = True, os_id: str = UNNAMED_OS_ID
) -> None:
    """Write the triggers declared in code to storage, and turn off the ones code no longer declares.

    A declared trigger replaces a stored one of its name and keeps its stored enabled state. One that
    is no longer declared is disabled with a reason and keeps its history; declaring it again enables it.

    Every row is marked with the AgentOS that declared it, and only rows with that mark are turned
    off. Another AgentOS on the same database, and a row that carries no mark, are left alone. A row
    with no mark becomes the property of the AgentOS that declares a trigger of its name.

    Args:
        with_schedules: Also look through the stored schedules for ones a trigger declared. An AgentOS
            that declares no trigger and runs no scheduler skips it: nothing would fire them.
        os_id: The AgentOS declaring the triggers. Replicas of one AgentOS pass the same id.
    """
    events = [trigger for trigger in triggers if isinstance(trigger.on, Events)]
    schedules = [trigger for trigger in triggers if isinstance(trigger.on, Schedule)]

    if supports_triggers(db):
        manager = TriggerManager(db)
        declared = set()
        for trigger in events:
            assert isinstance(trigger.on, Events)
            stored = await manager.acreate(
                name=trigger.name,
                source_id=trigger.on.source_id,
                events=list(trigger.on.kinds),
                target_type=trigger.target_type,
                target_id=trigger.target_id,
                input=trigger.input,
                continue_on=trigger.continue_on,
                filters=trigger.on.filters,
                description=trigger.description,
                timeout_seconds=trigger.timeout_seconds,
                max_retries=trigger.max_retries,
                retry_delay_seconds=trigger.retry_delay_seconds,
                if_exists="update",
                provenance={"managed_by": CODE_MANAGED, "os_id": os_id},
            )
            declared.add(trigger.name)
            if not stored.enabled and stored.disabled_reason == NOT_DECLARED_REASON:
                await manager.aenable(stored.id)
        stale: List[StoredTrigger] = []
        page = 1
        while True:
            rows = await manager.alist(managed_by=CODE_MANAGED, enabled=True, limit=100, page=page)
            stale.extend(row for row in rows if row.os_id == os_id and row.user_id is None and row.name not in declared)
            if len(rows) < 100:
                break
            page += 1
        for row in stale:
            await manager.adisable(row.id, reason=NOT_DECLARED_REASON)

    if not with_schedules:
        return
    from agno.scheduler import ScheduleManager

    schedule_manager = ScheduleManager(db)
    owner = schedule_manager_of(os_id)
    declared_schedules = set()
    for trigger in schedules:
        assert isinstance(trigger.on, Schedule)
        schedule = await _adeclare_schedule(db, schedule_manager, trigger, owner)
        declared_schedules.add(trigger.name)
        if not schedule.enabled and schedule.disabled_reason == NOT_DECLARED_REASON:
            await schedule_manager.aupdate(schedule.id, enabled=True, disabled_reason=None)
    for schedule in await schedule_manager.alist_all(raise_on_error=False):
        # Only a schedule this AgentOS's triggers declared. What a schedule's payload says is not
        # proof of that: anyone who can write a schedule can write its payload.
        if schedule.managed_by != owner:
            continue
        if schedule.enabled and schedule.user_id is None and schedule.name not in declared_schedules:
            await schedule_manager.aupdate(schedule.id, enabled=False, disabled_reason=NOT_DECLARED_REASON)


async def _adeclare_schedule(db: Any, schedule_manager: Any, trigger: Trigger, owner: str) -> Any:
    """Store the schedule a trigger declares, and mark it as declared by this AgentOS's triggers."""
    assert isinstance(trigger.on, Schedule)

    async def store() -> Any:
        return await schedule_manager.acreate(
            name=trigger.name,
            cron=trigger.on.cron,  # type: ignore[union-attr]
            endpoint=build_run_endpoint(trigger.target_type, trigger.target_id),
            description=trigger.description,
            payload={"message": trigger.input, "metadata": {SCHEDULE_TRIGGER_METADATA_KEY: trigger.name}},
            timezone=trigger.on.timezone,  # type: ignore[union-attr]
            timeout_seconds=trigger.timeout_seconds,
            max_retries=trigger.max_retries,
            retry_delay_seconds=trigger.retry_delay_seconds,
            if_exists="update",
            provenance={"managed_by": owner},
        )

    try:
        schedule = await store()
    except Exception:
        # Another replica stored the same schedule between this one's read and its insert, and the
        # unique name refused the second insert. The row is there now: store over it.
        if await acall_db(db, "get_schedule_by_name", trigger.name, user_id=None) is None:
            raise
        schedule = await store()
    # A schedule of this name that no control plane manages, or that an AgentOS's triggers declared
    # before, becomes this AgentOS's. One managed by something else keeps its manager.
    unmanaged = schedule.managed_by is None or str(schedule.managed_by).startswith(f"{TRIGGER_MANAGED}:")
    if schedule.managed_by != owner and unmanaged:
        await acall_db(db, "stamp_schedule_provenance", schedule.id, managed_by=owner)
        schedule.managed_by = owner
    return schedule


class TriggerRuntime:
    """Receives deliveries from sources, stores one event row for each trigger they concern, and runs them."""

    def __init__(
        self,
        db: Any,
        triggers: Sequence[Trigger],
        sources: Sequence[Any],
        base_url: str,
        internal_service_token: str,
        poll_interval: float = 15,
        os_id: str = UNNAMED_OS_ID,
    ) -> None:
        """
        Args:
            os_id: The AgentOS this runtime belongs to. It matches deliveries against that AgentOS's
                triggers and runs their events, and leaves the triggers of any other AgentOS on the
                same database alone. Replicas of one AgentOS pass the same id and share its events.
        """
        require_trigger_storage(db)
        self.db = db
        self.os_id = os_id
        self.triggers = list(triggers)
        self.sources: Dict[str, Any] = {source.id: source for source in sources}
        # prepare and on_complete live in code, so they are looked up here by the trigger's name.
        self.declared: Dict[str, Trigger] = {
            trigger.name: trigger for trigger in self.triggers if isinstance(trigger.on, Events)
        }
        self.executor = TriggerExecutor(base_url=base_url, internal_service_token=internal_service_token)
        self.poller = TriggerPoller(
            db=db, executor=self.executor, runtime=self, poll_interval=poll_interval, os_id=os_id
        )

    async def astart(self, with_schedules: bool = True) -> None:
        """Store the declared triggers, then start running events."""
        await adeclare_triggers(self.db, self.triggers, with_schedules=with_schedules, os_id=self.os_id)
        await self.poller.start()

    async def astop(self) -> None:
        await self.poller.stop()

    async def _handled(self, trigger_id: str, key: Optional[str]) -> bool:
        """Whether this trigger already accepted an event for this key."""
        if key is None:
            return False
        _, total = await acall_db(
            self.db,
            "get_trigger_events",
            trigger_id=trigger_id,
            event_key=key,
            statuses=list(HANDLED_EVENT_STATUSES),
            limit=1,
        )
        return total > 0

    def _row(
        self,
        delivery: Delivery,
        trigger: Optional[Dict[str, Any]],
        status: str,
        reason: Optional[str] = None,
        check_sender: bool = False,
    ) -> Dict[str, Any]:
        runs = status == EVENT_PENDING
        # An event that starts nothing is stored trimmed: it only has to explain why.
        stored = dict(delivery.stored if runs else delivery.trimmed)
        if check_sender:
            stored[CHECK_SENDER_KEY] = True
        trigger_id = trigger["id"] if trigger is not None else NO_TRIGGER_ID
        return TriggerEvent(
            id=new_trigger_event_id(),
            source_id=delivery.source_id,
            delivery_id=delivery.delivery_id,
            trigger_id=trigger_id,
            kind=delivery.kind,
            event_key=delivery.key,
            status=status,
            reason=reason,
            event=stored,
            session_id=session_id_for(trigger_id, delivery.key) if runs and delivery.key else None,
            user_id=trigger.get("user_id") if trigger is not None else None,
        ).to_dict()

    async def areceive(self, source: Any, delivery: Delivery) -> Dict[str, Any]:
        """Match a verified delivery against the enabled triggers of its source and store the result.

        Every row is stored before this returns, so the delivery can be acknowledged: one pending
        row for each trigger the event starts or continues, and an ignored row, with the reason,
        for each trigger that listens for the kind but does not take this event. A delivery no
        trigger listens for is stored once, as ignored. Nothing slow happens here.
        """
        rows: List[Dict[str, Any]] = []
        if delivery.ignore_reason is not None:
            rows.append(self._row(delivery, None, EVENT_IGNORED, delivery.ignore_reason))
        else:
            triggers, _ = await acall_db(
                self.db, "get_triggers", source_id=delivery.source_id, enabled=True, limit=1000, os_id=self.os_id
            )
            for trigger in triggers:
                starts = delivery.kind in (trigger.get("events") or [])
                continues = delivery.kind in (trigger.get("continue_on") or [])
                if not starts and not continues:
                    continue
                verdict = source.check(delivery.event, trigger.get("filters") or {})
                if verdict.reason is not None and not verdict.check_sender:
                    rows.append(self._row(delivery, trigger, EVENT_IGNORED, verdict.reason))
                elif not starts and not await self._handled(trigger["id"], delivery.key):
                    reason = f"{delivery.kind} continues a conversation, and {trigger['name']} has not handled "
                    rows.append(self._row(delivery, trigger, EVENT_IGNORED, reason + (delivery.key or "this event")))
                else:
                    rows.append(self._row(delivery, trigger, EVENT_PENDING, check_sender=verdict.check_sender))
            if not rows:
                rows.append(self._row(delivery, None, EVENT_IGNORED, f"no trigger listens for {delivery.kind}"))

        results = []
        for row in rows:
            created = await acall_db(self.db, "create_trigger_event", row)
            results.append({"trigger_id": row["trigger_id"] or None, "status": row["status"], "duplicate": not created})
            if row["reason"]:
                results[-1]["reason"] = row["reason"]
            if created:
                results[-1]["event_id"] = row["id"]
        if any(result["status"] == EVENT_PENDING and not result["duplicate"] for result in results):
            self.poller.wake()
        accepted = any(result["status"] == EVENT_PENDING for result in results)
        log_debug(f"Trigger delivery {delivery.delivery_id} ({delivery.kind}): {results}")
        return {
            "status": "accepted" if accepted else "ignored",
            "delivery_id": delivery.delivery_id,
            # A redelivery finds its rows already stored and starts nothing.
            "duplicate": all(result["duplicate"] for result in results),
            "events": results,
        }
