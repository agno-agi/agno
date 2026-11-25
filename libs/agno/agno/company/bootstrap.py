"""Rehydrate code declarations by stable identity without resetting human edits."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Optional
from uuid import NAMESPACE_URL, uuid5

from agno.company.declarations import Goal
from agno.company.execution import _call
from agno.company.routines import _declared_schedule_fields, _require_migrated_routine
from agno.db.utils import is_unique_violation
from agno.scheduler import ScheduleManager


async def _create_declared_routine(schedule_db: Any, fields: Any, owner: Optional[str], enabled: bool) -> Any:
    """Insert a Routine that declares auto_accept, or return the Routine already stored under its name.

    The insert carries the declared marker, so a Routine never exists with a policy and no grant. A
    Routine that already exists is returned as it is: its grant belongs to whoever wrote it.
    """
    import time
    from uuid import uuid4

    from agno.company.manager import _routine_provenance
    from agno.company.routines import _DECLARED
    from agno.db.schemas.scheduler import Schedule
    from agno.scheduler.cron import next_run_for

    found = await _call(schedule_db, "get_schedule_by_name", fields["name"], user_id=owner)
    if found is not None:
        return Schedule.from_dict(found)
    # No person wrote this policy. The marker says it runs as the deployment.
    row = Schedule(
        id=str(uuid4()),
        user_id=owner,
        name=fields["name"],
        endpoint=fields["endpoint"],
        payload={**fields["payload"], "_agno_company_acceptance": dict(_DECLARED)},
        cron_expr=fields["cron"],
        timezone=fields["timezone"],
        enabled=enabled,
        next_run_at=next_run_for(fields["cron"], fields["timezone"]),
        created_at=int(time.time()),
        **_routine_provenance(fields["endpoint"]),
    )
    return Schedule.from_dict(await _call(schedule_db, "create_schedule", row.to_dict()))


async def arehydrate_goal(
    db: Any,
    goal: Goal,
    registry: Any = None,
    schedule_db: Any = None,
    scoped_user_id: Optional[str] = None,
    *,
    agent_os: Any = None,
    trusted: bool = False,
):
    """Insert declared records once, repair interrupted linking, and retain later edits.

    trusted marks the deployment's own code and YAML declarations, which may carry auto_accept. The
    policy is saved when a Routine is first created; an existing Routine keeps its stored setting.
    """
    import time

    goal_id = goal.id or str(uuid5(NAMESPACE_URL, "agno:company:product:" + goal.name))
    routine_fields = []
    for routine in goal.routines:
        try:
            routine_fields.append(
                _declared_schedule_fields(goal_id, routine, registry, agent_os=agent_os, trusted=trusted)
            )
        except ValueError as exc:
            raise ValueError(
                f"Goal {goal.name!r}, Routine {routine.name!r}, "
                f"executor {routine.executor_type} {routine.executor_id!r}: {exc}"
            ) from exc
    row = await _call(db, "get_goal", goal_id, include_deleted=True)
    if row is None:
        try:
            row = await _call(
                db,
                "create_goal",
                {
                    "id": goal_id,
                    "name": goal.name,
                    "objective": goal.objective,
                    "metadata": goal.metadata,
                    "user_id": goal.user_id,
                    "created_at": int(time.time()),
                    "updated_at": None,
                    "deleted_at": None,
                },
            )
        except Exception as exc:
            if not is_unique_violation(exc):
                raise
            row = await _call(db, "get_goal", goal_id, include_deleted=True)
    if row is None:
        raise RuntimeError("Goal rehydration failed")
    from agno.company.playbook import _require_goal_scope

    _require_goal_scope(row)
    if row.get("deleted_at") is not None:
        return row
    # An existing owner remains authoritative; declarations never reassign ownership.
    for source in goal.sources:
        source_id = source.id or str(uuid5(NAMESPACE_URL, goal_id + ":" + source.type + ":" + source.reference))
        existing_source = await _call(db, "get_source", source_id, include_deleted=True)
        if existing_source is not None and existing_source["goal_id"] != goal_id:
            raise ValueError("Source id belongs to another Goal")
        if existing_source is None:
            try:
                await _call(
                    db,
                    "create_source",
                    {
                        **source.model_dump(exclude={"id"}),
                        "id": source_id,
                        "goal_id": goal_id,
                        "user_id": row["user_id"],
                        "created_at": int(time.time()),
                        "updated_at": None,
                        "deleted_at": None,
                    },
                )
            except Exception as exc:
                if not is_unique_violation(exc):
                    raise
                existing_source = await _call(db, "get_source", source_id, include_deleted=True)
                if existing_source is None or existing_source["goal_id"] != goal_id:
                    raise ValueError("Source id belongs to another Goal") from exc
    schedule_db = schedule_db if schedule_db is not None else db
    schedules = ScheduleManager(schedule_db)
    from agno.company.manager import _routine_provenance
    from agno.db.schemas.scheduler import Schedule

    # An existing Routine keeps its owner on a retry; only a new one belongs to its declarer, as on
    # POST /company/routines. Code declarations use the Goal owner.
    routine_owner = goal.user_id if goal.user_id is not None else row["user_id"]
    linked = {}
    for schedule_id in (row.get("metadata") or {}).get("routine_ids") or []:
        found = await _call(schedule_db, "get_schedule", schedule_id)
        if found is not None:
            linked[found["name"]] = found
    for routine, fields in zip(goal.routines, routine_fields):
        fields["cron"] = fields.pop("cron_expr")
        existing = linked.get(fields["name"]) or await _call(
            schedule_db, "get_schedule_by_name", fields["name"], user_id=row["user_id"]
        )
        if existing is not None:
            schedule = Schedule.from_dict(existing)
        else:
            try:
                if routine.auto_accept:
                    # The schedule manager drops an acceptance grant from every payload it writes.
                    schedule = await _create_declared_routine(schedule_db, fields, routine_owner, routine.enabled)
                else:
                    schedule = await schedules.acreate(
                        **fields,
                        user_id=routine_owner,
                        if_exists="skip",
                        enabled_on_create=routine.enabled,
                        provenance=_routine_provenance(fields["endpoint"]),
                    )
            except Exception as exc:
                if not is_unique_violation(exc):
                    raise
                existing = await _call(schedule_db, "get_schedule_by_name", fields["name"], user_id=routine_owner)
                if existing is None:
                    raise
                schedule = Schedule.from_dict(existing)
        if schedule.managed_by == "company":
            _require_migrated_routine(schedule.id, schedule.payload, schedule_db.schedules_table_name)
        if schedule.managed_by != "company" or (schedule.payload or {}).get("metadata", {}).get("goal_id") != goal_id:
            raise ValueError("Routine name is already used by another schedule")
        # An archived Routine stays out of the Goal's routine_ids until it is restored.
        if (schedule.payload or {}).get("metadata", {}).get("deleted_at") is None:
            row = await _call(db, "add_goal_routine", goal_id, schedule.id)
    return row


def rehydrate_goal(
    db: Any,
    goal: Goal,
    registry: Any = None,
    schedule_db: Any = None,
    scoped_user_id: Optional[str] = None,
    *,
    agent_os: Any = None,
    trusted: bool = False,
):
    """Synchronous startup counterpart; use arehydrate_goal inside an event loop."""
    return asyncio.run(
        arehydrate_goal(
            db,
            goal,
            registry,
            schedule_db=schedule_db,
            scoped_user_id=scoped_user_id,
            agent_os=agent_os,
            trusted=trusted,
        )
    )


async def arehydrate_product(db: Any, product: Goal, *args: Any, **kwargs: Any):
    """The agno 3.2 name of arehydrate_goal."""
    return await arehydrate_goal(db, product, *args, **kwargs)


def rehydrate_product(db: Any, product: Goal, *args: Any, **kwargs: Any):
    """The agno 3.2 name of rehydrate_goal."""
    return rehydrate_goal(db, product, *args, **kwargs)


async def _start_company(agent_os: Any) -> bool:
    """Apply CompanyConfig and the Goals declared in code. False when a database must be migrated first.

    AgentOS starts either way. Until the migration, Company refuses at first use with the same error.
    The migrate endpoint calls this again, so Company starts without a restart.
    """
    from agno.company.details import _seed_company
    from agno.exceptions import MigrationRequiredError
    from agno.utils.log import log_debug, log_error

    try:
        if agent_os._company_db is not None:
            await _seed_company(agent_os)
        for declaration in agent_os.company.goals:
            goal = declaration if isinstance(declaration, Goal) else Goal.model_validate(declaration)
            await arehydrate_goal(
                agent_os._company_db, goal, agent_os.registry, schedule_db=agent_os.db, agent_os=agent_os, trusted=True
            )
    except MigrationRequiredError as exc:
        message = f"Company is not started: {exc}"
        # The failed automatic migration was reported once already.
        (log_debug if agent_os._unmigrated_dbs or agent_os._company_start_pending else log_error)(message)
        agent_os._company_start_pending = True
        return False
    agent_os._company_start_pending = False
    return True


@asynccontextmanager
async def _company_lifespan(app: Any, agent_os: Any):
    await _start_company(agent_os)
    # Super Agent tools start Task runs through this app's executor route, as the HTTP API does.
    agent_os._company_app = app
    try:
        yield
    finally:
        agent_os._company_app = None
