"""SchedulerTools -- give agents the ability to create and manage recurring schedules.

Wraps the ScheduleManager to expose schedule CRUD as agent-callable tools.
Requires a database backend that implements the scheduler DB methods and
the AgentOS server + SchedulePoller to actually execute the schedules.

Example:
    from agno.tools.scheduler import SchedulerTools

    agent = Agent(
        model=OpenAIChat(id="gpt-5.5"),
        tools=[
            SchedulerTools(
                db=scheduler_db,
                default_endpoint="/agents/my-agent/runs",
            )
        ],
    )
"""

import asyncio
import json
import time
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from agno.db.schemas.scheduler import RUN_ENDPOINT_RE, Schedule, match_run_endpoint
from agno.run import RunContext
from agno.scheduler.manager import ScheduleManager
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, logger


def _parse_target_archived_reason(disabled_reason: Optional[str]) -> Optional[Tuple[str, str]]:
    """Parse a system ``target_archived:<type>:<id>`` disabled_reason into (type, id).

    Format authority for the cascade's reason string. Deliberately NOT part of
    the enable predicate: the reason records why a row was disabled, not what
    it targets now, so refusing on it would brick a row repointed at a live
    target and miss a row that was disabled before the archive.
    """
    if not disabled_reason or not disabled_reason.startswith("target_archived:"):
        return None
    parts = disabled_reason.split(":", 2)
    if len(parts) != 3 or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def _is_archived_component(row: Optional[Dict[str, Any]]) -> bool:
    """True only for a real archived row: a dict with ``deleted_at`` set."""
    return isinstance(row, dict) and row.get("deleted_at") is not None


def _endpoint_target(endpoint: Optional[str]) -> Optional[Tuple[str, str]]:
    """(singular type, id) of the component a run endpoint addresses, else None."""
    if not endpoint:
        return None
    match = RUN_ENDPOINT_RE.match(endpoint)
    if match is None:
        return None
    return match.group(1)[:-1], match.group(2)  # "agents" -> "agent"


def _schedule_component_target(schedule: Schedule) -> Optional[Tuple[str, str]]:
    """The component *schedule* actually targets: provenance when stamped, else its run endpoint."""
    if schedule.target_id:
        return schedule.target_type or "component", schedule.target_id
    return _endpoint_target(schedule.endpoint)


# ``(target_type, target_id) -> True`` when that component is defined in code and
# served from the running process. Pure in-memory lookup: the async refusal paths
# call it directly rather than handing it to a worker thread.
CodeDefinedProbe = Callable[[str, str], bool]


def code_defined_probe(
    agents: Optional[Sequence[Any]] = None,
    teams: Optional[Sequence[Any]] = None,
    workflows: Optional[Sequence[Any]] = None,
) -> Optional[CodeDefinedProbe]:
    """A probe over the in-process components, or None when none were given.

    The component catalog cannot see a component that is defined in code: the run
    routes resolve those from the in-process lists BEFORE they consult the
    catalog, so a code-defined target answers its run endpoint no matter what a
    catalog row of the same id holds. A caller that owns those lists builds a
    probe here and hands it to the draft-only refusal; a caller that owns none
    passes nothing, and the catalog stands alone.

    The answer is per (type, id), never per id: a code-defined AGENT and a
    draft-only TEAM row can share an id, and exempting the team on the agent's
    account would arm a schedule that resolves to nothing.

    The lists are read on every probe call, not snapshotted here, so a list that
    is still empty when the probe is built - AgentOS fills its own lists after
    the toolkits and routers are wired - answers for whatever it holds at
    refusal time. Passing no list at all is the "no evidence" case and yields
    None, which leaves the catalog to decide alone.
    """
    if agents is None and teams is None and workflows is None:
        return None
    by_type: Dict[str, Optional[Sequence[Any]]] = {"agent": agents, "team": teams, "workflow": workflows}

    def probe(target_type: str, target_id: str) -> bool:
        return any(getattr(entry, "id", None) == target_id for entry in by_type.get(target_type) or [])

    return probe


def _component_type_arg(target_type: str) -> Optional[Any]:
    """``target_type`` as a ComponentType, or None when it names no real type."""
    from agno.db.base import ComponentType

    try:
        return ComponentType(target_type)
    except ValueError:
        return None


def _archived_component_refusal(
    db: Any, target_type: str, target_id: str, user_id: Optional[str] = None
) -> Optional[Tuple[str, str]]:
    """(type, id) iff that component's catalog row exists with ``deleted_at`` set.

    ``user_id`` scopes the read to the caller: without it a scoped caller gets a
    different answer for another owner's archived component than for an id that
    does not exist, which discloses that the component exists.
    """
    if db is None:
        return None
    get_component = getattr(db, "get_component", None)
    if get_component is None:
        return None
    try:
        # The type predicate matters: a code-defined component of another type
        # can hold the same id, and an archived catalog row must not be read as
        # THIS schedule's target. upsert_component refuses to rewrite a type,
        # so the type recorded when the schedule was made still identifies it.
        row = get_component(
            target_id,
            component_type=_component_type_arg(target_type),
            user_id=user_id,
            include_deleted=True,
        )
    except NotImplementedError:
        return None
    if _is_archived_component(row):
        return target_type, target_id
    return None


async def _aarchived_component_refusal(
    db: Any, target_type: str, target_id: str, user_id: Optional[str] = None
) -> Optional[Tuple[str, str]]:
    """Async variant of ``_archived_component_refusal``; same predicate."""
    if db is None:
        return None
    get_component = getattr(db, "get_component", None)
    if get_component is None:
        return None
    component_type = _component_type_arg(target_type)
    try:
        if asyncio.iscoroutinefunction(get_component):
            row = await get_component(target_id, component_type=component_type, user_id=user_id, include_deleted=True)
        else:
            # A sync adapter would hold the event loop for the whole query
            row = await asyncio.to_thread(
                partial(
                    get_component,
                    target_id,
                    component_type=component_type,
                    user_id=user_id,
                    include_deleted=True,
                )
            )
    except NotImplementedError:
        return None
    if _is_archived_component(row):
        return target_type, target_id
    return None


def archived_target_refusal(db: Any, schedule: Schedule, user_id: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """(type, id) of the still-archived component that blocks enabling *schedule*, else None.

    The verdict is the target's ACTUAL liveness, never the disabled_reason: the
    target is the provenance (target_type/target_id) when stamped, else the
    component named by the schedule's run endpoint. Enable is refused if and
    only if that component's catalog row has ``deleted_at`` set - regardless of
    why (or whether) the schedule was disabled - so a row disabled before the
    archive is still refused, and a row since repointed at a live target is not
    refused over a stale reason. A missing catalog row is a live code-defined
    target (allow); a restored or hard-deleted target no longer blocks;
    adapters without a component catalog (``get_component`` raising
    NotImplementedError) allow.

    The REST enable route and the create guards apply this same predicate;
    keep them identical.

    ``user_id`` is accepted for call-site symmetry with the create-side guards
    and deliberately not forwarded: the liveness read here is unscoped. The
    caller already holds the schedule row, which names its own target, so an
    unscoped read discloses nothing it cannot read off that row -- while a
    scoped one hides another owner's archived component behind "live" and
    lets the caller re-arm the very schedule the archive cascade disabled.
    """
    target = _schedule_component_target(schedule)
    if target is None:
        return None
    return _archived_component_refusal(db, target[0], target[1])


async def aarchived_target_refusal(
    db: Any, schedule: Schedule, user_id: Optional[str] = None
) -> Optional[Tuple[str, str]]:
    """Async variant of ``archived_target_refusal``; same predicate, and the
    same deliberately unscoped liveness read."""
    target = _schedule_component_target(schedule)
    if target is None:
        return None
    return await _aarchived_component_refusal(db, target[0], target[1])


def archived_endpoint_refusal(
    db: Any, endpoint: Optional[str], user_id: Optional[str] = None
) -> Optional[Tuple[str, str]]:
    """(type, id) when *endpoint* is a run endpoint aimed at an archived component, else None.

    Create-side twin of ``archived_target_refusal``: a schedule pointed at an
    archived component can only 404 at fire time, so creating or repointing one
    is refused up front instead of accepted and left armed.
    """
    target = _endpoint_target(endpoint)
    if target is None:
        return None
    return _archived_component_refusal(db, target[0], target[1], user_id=user_id)


async def aarchived_endpoint_refusal(
    db: Any, endpoint: Optional[str], user_id: Optional[str] = None
) -> Optional[Tuple[str, str]]:
    """Async variant of ``archived_endpoint_refusal``; same predicate."""
    target = _endpoint_target(endpoint)
    if target is None:
        return None
    return await _aarchived_component_refusal(db, target[0], target[1], user_id=user_id)


def _has_any_config(db: Any, component_id: str) -> bool:
    """True when the component carries at least one stored config version.

    Distinguishes a real draft-only component from a bare components row that
    has no configs at all; adapters without a catalog answer False (allow).
    """
    list_configs = getattr(db, "list_configs", None)
    if list_configs is None:
        return False
    try:
        return bool(list_configs(component_id, include_config=False))
    except (NotImplementedError, TypeError):
        return False


def _draft_only_component_refusal(
    db: Any,
    target_type: str,
    target_id: str,
    user_id: Optional[str] = None,
    is_code_defined: Optional[CodeDefinedProbe] = None,
) -> Optional[Tuple[str, str]]:
    """(type, id) iff that component has an unpublished config and no live version.

    ``current_version is None`` alone is not enough: a components row with no
    configs at all (a bare registry/control-plane stub) reads the same way, and
    it behaves like a code-defined target - there is nothing to publish, so
    refusing it would brick schedules that work today. Only a component that
    actually carries a config, none of which is live, is a draft-only target.

    A target the caller reports as code-defined is exempt outright, catalog row
    and all: the run routes resolve it in process, so its draft configs never
    decide whether the endpoint answers, and "publish it first" names a remedy
    that would not change the run either way. The exemption is settled before
    the catalog is read, so it can neither depend on nor disclose a row the
    caller may not see.
    """
    if db is None:
        return None
    if is_code_defined is not None and is_code_defined(target_type, target_id):
        return None
    get_component = getattr(db, "get_component", None)
    if get_component is None:
        return None
    try:
        row = get_component(target_id, component_type=_component_type_arg(target_type), user_id=user_id)
    except NotImplementedError:
        return None
    if not isinstance(row, dict) or row.get("current_version") is not None:
        return None
    if not _has_any_config(db, target_id):
        return None
    return target_type, target_id


async def _adraft_only_component_refusal(
    db: Any,
    target_type: str,
    target_id: str,
    user_id: Optional[str] = None,
    is_code_defined: Optional[CodeDefinedProbe] = None,
) -> Optional[Tuple[str, str]]:
    """Async variant of ``_draft_only_component_refusal``; same predicate."""
    if db is None:
        return None
    if is_code_defined is not None and is_code_defined(target_type, target_id):
        return None
    get_component = getattr(db, "get_component", None)
    if get_component is None:
        return None
    component_type = _component_type_arg(target_type)
    try:
        if asyncio.iscoroutinefunction(get_component):
            row = await get_component(target_id, component_type=component_type, user_id=user_id)
        else:
            row = await asyncio.to_thread(
                partial(get_component, target_id, component_type=component_type, user_id=user_id)
            )
    except NotImplementedError:
        return None
    if not isinstance(row, dict) or row.get("current_version") is not None:
        return None
    if not await asyncio.to_thread(partial(_has_any_config, db, target_id)):
        return None
    return target_type, target_id


def draft_endpoint_refusal(
    db: Any,
    endpoint: Optional[str],
    user_id: Optional[str] = None,
    is_code_defined: Optional[CodeDefinedProbe] = None,
) -> Optional[Tuple[str, str]]:
    """(type, id) when *endpoint* is aimed at a draft-only component, else None."""
    target = _endpoint_target(endpoint)
    if target is None:
        return None
    return _draft_only_component_refusal(db, target[0], target[1], user_id=user_id, is_code_defined=is_code_defined)


async def adraft_endpoint_refusal(
    db: Any,
    endpoint: Optional[str],
    user_id: Optional[str] = None,
    is_code_defined: Optional[CodeDefinedProbe] = None,
) -> Optional[Tuple[str, str]]:
    """Async variant of ``draft_endpoint_refusal``; same predicate."""
    target = _endpoint_target(endpoint)
    if target is None:
        return None
    return await _adraft_only_component_refusal(
        db, target[0], target[1], user_id=user_id, is_code_defined=is_code_defined
    )


def draft_target_refusal(
    db: Any,
    schedule: Schedule,
    user_id: Optional[str] = None,
    is_code_defined: Optional[CodeDefinedProbe] = None,
) -> Optional[Tuple[str, str]]:
    """(type, id) of the draft-only component that blocks enabling *schedule*."""
    target = _schedule_component_target(schedule)
    if target is None:
        return None
    return _draft_only_component_refusal(db, target[0], target[1], user_id=user_id, is_code_defined=is_code_defined)


async def adraft_target_refusal(
    db: Any,
    schedule: Schedule,
    user_id: Optional[str] = None,
    is_code_defined: Optional[CodeDefinedProbe] = None,
) -> Optional[Tuple[str, str]]:
    """(type, id) of the draft-only component that blocks enabling *schedule*."""
    target = _schedule_component_target(schedule)
    if target is None:
        return None
    return await _adraft_only_component_refusal(
        db, target[0], target[1], user_id=user_id, is_code_defined=is_code_defined
    )


def endpoint_drift_refusal(schedule: Schedule) -> Optional[str]:
    """Why enable must stay refused for an endpoint_drift-disabled row, else None.

    The executor disables a managed schedule whose endpoint no longer matches
    its provenance target (reason ``endpoint_drift:...``). Re-arming without
    re-checking would fail-and-disable again on the next tick - or fire the
    wrong component. Enable is allowed only once the endpoint matches the
    provenance target again; a drift-disabled row without provenance to check
    against stays refused (fail closed). Pure predicate (no I/O), shared by the
    sync and async enable paths.
    """
    reason = schedule.disabled_reason or ""
    if not reason.startswith("endpoint_drift:"):
        return None
    if (
        schedule.target_type
        and schedule.target_id
        and schedule.endpoint
        and match_run_endpoint(schedule.endpoint, schedule.target_type, schedule.target_id)
    ):
        return None
    return reason


class SchedulerTools(Toolkit):
    """Toolkit that lets an agent create and manage recurring schedules.

    The agent can ask a user "what should I do every day?" and then call
    ``create_schedule`` to set up a cron-based recurring execution via the
    existing AgentOS scheduler infrastructure.

    Args:
        db: A database adapter that implements the scheduler DB methods.
        default_endpoint: The default endpoint to call when a schedule fires
            (e.g. ``/agents/<agent_id>/runs``). The agent can override this
            per-schedule, but having a default simplifies the common case.
        default_method: HTTP method for the endpoint (default: ``POST``).
        default_timezone: Default timezone for schedules (default: ``UTC``).
        default_payload: Default payload to send with each scheduled run.
            The agent can override or extend this per-schedule.
        user_id: Fixed owner for every schedule operation. When unset, the
            owner is taken from the run's ``user_id`` (injected via
            ``run_context``), so each user's agent only sees and edits that
            user's schedules.
        include_agents: Optional live list (e.g. ``agent_os.agents``) of the
            code-defined agents this process serves. Schedules aimed at one are
            exempt from the draft-only refusal: run routes resolve code-defined
            components before they consult the component catalog, so a catalog
            row of the same id never decides whether the endpoint answers.
            Without the list the catalog is the only evidence there is, and a
            code-defined target that also carries a draft row is refused.
        include_teams: Same as ``include_agents`` but for teams.
        include_workflows: Same as ``include_agents`` but for workflows.
    """

    def __init__(
        self,
        db: Any,
        default_endpoint: Optional[str] = None,
        default_method: str = "POST",
        default_timezone: str = "UTC",
        default_payload: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        include_agents: Optional[Sequence[Any]] = None,
        include_teams: Optional[Sequence[Any]] = None,
        include_workflows: Optional[Sequence[Any]] = None,
        db_resolver: Optional[Callable[[], Any]] = None,
        **kwargs: Any,
    ):
        # With a resolver and no db yet, the manager is built lazily on first
        # access: the embedding StudioTools may learn its db only after
        # AgentOS fills the shared registry.
        self._db_resolver = db_resolver
        self._manager: Optional[ScheduleManager] = (
            ScheduleManager(db=db) if db is not None or db_resolver is None else None
        )
        # A manager built from an explicit db - or assigned through the setter -
        # is the caller's choice and is never rebuilt underneath them. Only a
        # resolver-backed one tracks the resolver.
        self._manager_pinned = self._manager is not None
        self.user_id = user_id
        self.default_endpoint = default_endpoint
        self.default_method = default_method
        self.default_timezone = default_timezone
        self.default_payload = default_payload
        self.include_agents = include_agents
        self.include_teams = include_teams
        self.include_workflows = include_workflows

        tools: List[Callable] = [
            self.create_schedule,
            self.list_schedules,
            self.get_schedule,
            self.delete_schedule,
            self.enable_schedule,
            self.disable_schedule,
            self.trigger_schedule,
            self.get_schedule_runs,
        ]

        async_tools: List[tuple[Callable[..., Any], str]] = [
            (self.acreate_schedule, "create_schedule"),
            (self.alist_schedules, "list_schedules"),
            (self.aget_schedule, "get_schedule"),
            (self.adelete_schedule, "delete_schedule"),
            (self.aenable_schedule, "enable_schedule"),
            (self.adisable_schedule, "disable_schedule"),
            (self.atrigger_schedule, "trigger_schedule"),
            (self.aget_schedule_runs, "get_schedule_runs"),
        ]

        super().__init__(
            name="scheduler",
            tools=tools,
            async_tools=async_tools,
            instructions=(
                "Use these tools to create and manage recurring scheduled tasks. "
                "When a user asks you to do something on a recurring basis (daily, weekly, etc.), "
                "convert their request into a cron expression and create a schedule. "
                "Common cron patterns: '0 9 * * *' (daily at 9am), '0 9 * * 1' (every Monday at 9am), "
                "'0 */6 * * *' (every 6 hours), '0 9 * * 1-5' (weekdays at 9am). "
                "When creating schedules for run endpoints (ending in /runs), you MUST include a "
                '\'message\' field in the payload, e.g. {"message": "Run the daily health check"}.'
            ),
            **kwargs,
        )

    @staticmethod
    def _is_run_endpoint(endpoint: str, method: str) -> bool:
        """Check if the endpoint targets an agent/team/workflow run route."""
        return method.upper() == "POST" and endpoint.rstrip("/").endswith("/runs")

    def _owner(self, run_context: Optional[RunContext]) -> Optional[str]:
        """Resolve the acting owner: a fixed toolkit user_id wins, else the run's user."""
        if self.user_id is not None:
            return self.user_id
        return run_context.user_id if run_context is not None else None

    @property
    def _code_defined(self) -> Optional[CodeDefinedProbe]:
        """Probe over this toolkit's in-process components, or None when it has none.

        Built from the attributes on every refusal rather than fixed at
        construction: the toolkit is usually created before the AgentOS whose
        component lists it is handed, so those lists are commonly assigned
        afterwards.
        """
        return code_defined_probe(self.include_agents, self.include_teams, self.include_workflows)

    # ------------------------------------------------------------------
    # Sync tools
    # ------------------------------------------------------------------

    @property
    def manager(self) -> ScheduleManager:
        if self._manager_pinned and self._manager is not None:
            return self._manager
        resolved = self._db_resolver() if self._db_resolver is not None else None
        # Rebuild whenever the resolver's answer MOVES, not just when it is
        # still None. The embedding toolkit learns its db from the registry
        # only once AgentOS declares one, so a manager built before that -- by
        # any read at all -- would otherwise hold the pre-declaration db for
        # the life of the process, splitting schedules from the catalog.
        if self._manager is None or self._manager.db is not resolved:
            self._manager = ScheduleManager(db=resolved)
        return self._manager

    @manager.setter
    def manager(self, value: ScheduleManager) -> None:
        self._manager = value
        self._manager_pinned = True

    def create_schedule(
        self,
        name: str,
        cron: str,
        description: Optional[str] = None,
        endpoint: Optional[str] = None,
        method: Optional[str] = None,
        payload: Optional[str] = None,
        timezone: Optional[str] = None,
        run_context: Optional[RunContext] = None,
    ) -> str:
        """Create a new recurring schedule that runs on a cron expression.

        Args:
            name (str): A unique name for the schedule (e.g. "daily-weather-report").
            cron (str): A 5-field cron expression (e.g. "0 9 * * *" for daily at 9am UTC).
            description (str): A human-readable description of what this schedule does.
            endpoint (str): The API endpoint to call when the schedule fires. Uses the default if not provided.
            method (str): HTTP method (GET, POST, etc.). Uses the default if not provided.
            payload (str): JSON string of the payload to send with the request. Uses the default if not provided.
            timezone (str): Timezone for the cron expression (e.g. "America/New_York"). Uses the default if not provided.

        Returns:
            str: JSON string with the created schedule details.
        """
        resolved_endpoint = endpoint or self.default_endpoint
        if not resolved_endpoint:
            return json.dumps({"error": "No endpoint provided and no default_endpoint configured"})

        resolved_payload = self.default_payload
        if payload is not None:
            try:
                resolved_payload = json.loads(payload)
            except json.JSONDecodeError:
                return json.dumps({"error": "Invalid JSON in payload parameter"})

        # Run endpoints require a "message" field in the payload
        resolved_method = method or self.default_method
        if self._is_run_endpoint(resolved_endpoint, resolved_method):
            if not resolved_payload or "message" not in resolved_payload:
                return json.dumps(
                    {
                        "error": "Schedules targeting run endpoints require a 'message' field in the payload. "
                        'Provide payload with at least: {"message": "your prompt here"}'
                    }
                )

        # A schedule aimed at an archived component can only 404 at fire time:
        # refuse the create instead of accepting an armed dead schedule. Scoped
        # to the acting owner: an unscoped probe answers "archived" for another
        # owner's component and "fine" for an id that does not exist, which
        # discloses that the component exists.
        refusal = archived_endpoint_refusal(self.manager.db, resolved_endpoint, user_id=self._owner(run_context))
        if refusal is not None:
            target_type, target_id = refusal
            return json.dumps(
                {
                    "error": f"Cannot create schedule '{name}': its target "
                    f"{target_type} '{target_id}' is archived. "
                    "Restore the component first.",
                    "error_type": "target_archived",
                    "target_type": target_type,
                    "target_id": target_id,
                }
            )
        # A schedule fires the live published version, so a draft-only target
        # can only 404 on every tick - and once the cascade disables the row,
        # the enable guard refuses to re-arm it. The REST create route applies
        # the same predicate; keep the two surfaces in step.
        draft_target = draft_endpoint_refusal(
            self.manager.db,
            resolved_endpoint,
            user_id=self._owner(run_context),
            is_code_defined=self._code_defined,
        )
        if draft_target is not None:
            target_type, target_id = draft_target
            return json.dumps(
                {
                    "error": f"Cannot create schedule '{name}': its target "
                    f"{target_type} '{target_id}' has no published version. "
                    "Publish it first.",
                    "error_type": "target_not_published",
                    "target_type": target_type,
                    "target_id": target_id,
                }
            )

        try:
            schedule = self.manager.create(
                name=name,
                cron=cron,
                endpoint=resolved_endpoint,
                method=resolved_method,
                description=description,
                payload=resolved_payload,
                timezone=timezone or self.default_timezone,
                if_exists="update",
                user_id=self._owner(run_context),
            )
            log_debug(f"Schedule created: {schedule.name} ({schedule.cron_expr})")
            return json.dumps(
                {
                    "status": "created",
                    "id": schedule.id,
                    "name": schedule.name,
                    "cron": schedule.cron_expr,
                    "endpoint": schedule.endpoint,
                    "timezone": schedule.timezone,
                    "enabled": schedule.enabled,
                    "description": schedule.description,
                }
            )
        except Exception as e:
            logger.exception("Failed to create schedule")
            return json.dumps({"error": str(e)})

    def list_schedules(self, enabled_only: bool = False, run_context: Optional[RunContext] = None) -> str:
        """List all existing schedules.

        Args:
            enabled_only (bool): If True, only return enabled schedules. Defaults to False.

        Returns:
            str: JSON string with the list of schedules.
        """
        try:
            enabled_filter = True if enabled_only else None
            schedules = self.manager.list(enabled=enabled_filter, user_id=self._owner(run_context))
            result = [
                {
                    "id": s.id,
                    "name": s.name,
                    "cron": s.cron_expr,
                    "endpoint": s.endpoint,
                    "timezone": s.timezone,
                    "enabled": s.enabled,
                    "description": s.description,
                }
                for s in schedules
            ]
            return json.dumps({"schedules": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to list schedules")
            return json.dumps({"error": str(e)})

    def get_schedule(self, schedule_id: str, run_context: Optional[RunContext] = None) -> str:
        """Get details of a specific schedule by its ID.

        Args:
            schedule_id (str): The ID of the schedule to retrieve.

        Returns:
            str: JSON string with the schedule details.
        """
        try:
            schedule = self.manager.get(schedule_id, user_id=self._owner(run_context))
            if schedule is None:
                return json.dumps({"error": f"Schedule not found: {schedule_id}"})
            return json.dumps(
                {
                    "id": schedule.id,
                    "name": schedule.name,
                    "cron": schedule.cron_expr,
                    "endpoint": schedule.endpoint,
                    "method": schedule.method,
                    "timezone": schedule.timezone,
                    "enabled": schedule.enabled,
                    "description": schedule.description,
                    "payload": schedule.payload,
                }
            )
        except Exception as e:
            logger.exception("Failed to get schedule")
            return json.dumps({"error": str(e)})

    def delete_schedule(self, schedule_id: str, run_context: Optional[RunContext] = None) -> str:
        """Delete a schedule by its ID. This permanently removes the schedule.

        Args:
            schedule_id (str): The ID of the schedule to delete.

        Returns:
            str: JSON string confirming deletion.
        """
        try:
            deleted = self.manager.delete(schedule_id, user_id=self._owner(run_context))
            if deleted:
                return json.dumps({"status": "deleted", "id": schedule_id})
            return json.dumps({"error": f"Schedule not found or could not be deleted: {schedule_id}"})
        except Exception as e:
            logger.exception("Failed to delete schedule")
            return json.dumps({"error": str(e)})

    def enable_schedule(self, schedule_id: str, run_context: Optional[RunContext] = None) -> str:
        """Enable a disabled schedule so it starts running again.

        Args:
            schedule_id (str): The ID of the schedule to enable.

        Returns:
            str: JSON string with the updated schedule details.
        """
        try:
            existing = self.manager.get(schedule_id, user_id=self._owner(run_context))
            if existing is None:
                return json.dumps({"error": f"Schedule not found: {schedule_id}"})
            # A schedule aimed at an archived component can only 404 at fire
            # time; restoring the component is the way to turn it back on. A
            # target without a catalog row is a live code-defined component.
            refusal = archived_target_refusal(self.manager.db, existing, user_id=self._owner(run_context))
            if refusal is not None:
                target_type, target_id = refusal
                return json.dumps(
                    {
                        "error": f"Cannot enable '{existing.name}': its target "
                        f"{target_type} '{target_id}' is archived. "
                        "Restore the component first.",
                        "error_type": "target_archived",
                        "target_type": target_type,
                        "target_id": target_id,
                    }
                )
            # A schedule fires the live published version, so a draft-only
            # target can only 404 on every tick. The REST enable route applies
            # the same predicate; keep the two surfaces in step.
            draft_target = draft_target_refusal(
                self.manager.db,
                existing,
                user_id=self._owner(run_context),
                is_code_defined=self._code_defined,
            )
            if draft_target is not None:
                target_type, target_id = draft_target
                return json.dumps(
                    {
                        "error": f"Cannot enable '{existing.name}': its target "
                        f"{target_type} '{target_id}' has no published version. "
                        "Publish it first.",
                        "error_type": "target_not_published",
                        "target_type": target_type,
                        "target_id": target_id,
                    }
                )
            # A drift-disabled row re-arms only once its endpoint matches its
            # provenance target again; otherwise it just fails on the next tick.
            drift = endpoint_drift_refusal(existing)
            if drift is not None:
                return json.dumps(
                    {
                        "error": f"Cannot enable '{existing.name}': it was disabled because its "
                        f"endpoint no longer matches its target ({drift}). "
                        "Repoint the endpoint back at the target first.",
                        "error_type": "endpoint_drift",
                        "target_type": existing.target_type,
                        "target_id": existing.target_id,
                    }
                )
            schedule = self.manager.enable(schedule_id, user_id=self._owner(run_context))
            if schedule is None:
                return json.dumps({"error": f"Schedule not found: {schedule_id}"})
            return json.dumps(
                {
                    "status": "enabled",
                    "id": schedule.id,
                    "name": schedule.name,
                    "enabled": schedule.enabled,
                }
            )
        except Exception as e:
            logger.exception("Failed to enable schedule")
            return json.dumps({"error": str(e)})

    def disable_schedule(self, schedule_id: str, run_context: Optional[RunContext] = None) -> str:
        """Disable a schedule so it stops running. Can be re-enabled later.

        Args:
            schedule_id (str): The ID of the schedule to disable.

        Returns:
            str: JSON string with the updated schedule details.
        """
        try:
            schedule = self.manager.disable(schedule_id, user_id=self._owner(run_context))
            if schedule is None:
                return json.dumps({"error": f"Schedule not found: {schedule_id}"})
            return json.dumps(
                {
                    "status": "disabled",
                    "id": schedule.id,
                    "name": schedule.name,
                    "enabled": schedule.enabled,
                }
            )
        except Exception as e:
            logger.exception("Failed to disable schedule")
            return json.dumps({"error": str(e)})

    def trigger_schedule(self, schedule_id: str, run_context: Optional[RunContext] = None) -> str:
        """Queue an enabled schedule to run now.

        Sets the schedule's next run time to now; the scheduler poller claims and
        executes it within one poll interval. The regular cron cadence resumes
        after the run.

        Args:
            schedule_id (str): The ID of the schedule to trigger.

        Returns:
            str: JSON string confirming the trigger.
        """
        try:
            owner = self._owner(run_context)
            schedule = self.manager.get(schedule_id, user_id=owner)
            if schedule is None:
                return json.dumps({"error": f"Schedule not found: {schedule_id}"})
            if not schedule.enabled:
                return json.dumps(
                    {"error": f"Schedule is disabled: {schedule_id}. Call enable_schedule first, then trigger it."}
                )
            self.manager.update(schedule_id, user_id=owner, next_run_at=int(time.time()))
            return json.dumps(
                {
                    "status": "triggered",
                    "id": schedule_id,
                    "note": "The scheduler poller will execute it within one poll interval.",
                }
            )
        except Exception as e:
            logger.exception("Failed to trigger schedule")
            return json.dumps({"error": str(e)})

    def get_schedule_runs(self, schedule_id: str, limit: int = 10, run_context: Optional[RunContext] = None) -> str:
        """Get the run history for a schedule.

        Args:
            schedule_id (str): The ID of the schedule to get runs for.
            limit (int): Maximum number of runs to return. Defaults to 10.

        Returns:
            str: JSON string with the list of runs.
        """
        try:
            runs = self.manager.get_runs(schedule_id, limit=limit, user_id=self._owner(run_context))
            result = [
                {
                    "id": r.id,
                    "status": r.status,
                    "triggered_at": r.triggered_at,
                    "completed_at": r.completed_at,
                    "error": r.error,
                }
                for r in runs
            ]
            return json.dumps({"runs": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to get schedule runs")
            return json.dumps({"error": str(e)})

    # ------------------------------------------------------------------
    # Async tools
    # ------------------------------------------------------------------

    async def acreate_schedule(
        self,
        name: str,
        cron: str,
        description: Optional[str] = None,
        endpoint: Optional[str] = None,
        method: Optional[str] = None,
        payload: Optional[str] = None,
        timezone: Optional[str] = None,
        run_context: Optional[RunContext] = None,
    ) -> str:
        """Create a new recurring schedule that runs on a cron expression.

        Args:
            name (str): A unique name for the schedule (e.g. "daily-weather-report").
            cron (str): A 5-field cron expression (e.g. "0 9 * * *" for daily at 9am UTC).
            description (str): A human-readable description of what this schedule does.
            endpoint (str): The API endpoint to call when the schedule fires. Uses the default if not provided.
            method (str): HTTP method (GET, POST, etc.). Uses the default if not provided.
            payload (str): JSON string of the payload to send with the request. Uses the default if not provided.
            timezone (str): Timezone for the cron expression (e.g. "America/New_York"). Uses the default if not provided.

        Returns:
            str: JSON string with the created schedule details.
        """
        resolved_endpoint = endpoint or self.default_endpoint
        if not resolved_endpoint:
            return json.dumps({"error": "No endpoint provided and no default_endpoint configured"})

        resolved_payload = self.default_payload
        if payload is not None:
            try:
                resolved_payload = json.loads(payload)
            except json.JSONDecodeError:
                return json.dumps({"error": "Invalid JSON in payload parameter"})

        # Run endpoints require a "message" field in the payload
        resolved_method = method or self.default_method
        if self._is_run_endpoint(resolved_endpoint, resolved_method):
            if not resolved_payload or "message" not in resolved_payload:
                return json.dumps(
                    {
                        "error": "Schedules targeting run endpoints require a 'message' field in the payload. "
                        'Provide payload with at least: {"message": "your prompt here"}'
                    }
                )

        # A schedule aimed at an archived component can only 404 at fire time:
        # refuse the create instead of accepting an armed dead schedule. Scoped
        # to the acting owner: an unscoped probe answers "archived" for another
        # owner's component and "fine" for an id that does not exist, which
        # discloses that the component exists.
        refusal = await aarchived_endpoint_refusal(self.manager.db, resolved_endpoint, user_id=self._owner(run_context))
        if refusal is not None:
            target_type, target_id = refusal
            return json.dumps(
                {
                    "error": f"Cannot create schedule '{name}': its target "
                    f"{target_type} '{target_id}' is archived. "
                    "Restore the component first.",
                    "error_type": "target_archived",
                    "target_type": target_type,
                    "target_id": target_id,
                }
            )
        # A schedule fires the live published version, so a draft-only target
        # can only 404 on every tick - and once the cascade disables the row,
        # the enable guard refuses to re-arm it. The REST create route applies
        # the same predicate; keep the two surfaces in step.
        draft_target = await adraft_endpoint_refusal(
            self.manager.db,
            resolved_endpoint,
            user_id=self._owner(run_context),
            is_code_defined=self._code_defined,
        )
        if draft_target is not None:
            target_type, target_id = draft_target
            return json.dumps(
                {
                    "error": f"Cannot create schedule '{name}': its target "
                    f"{target_type} '{target_id}' has no published version. "
                    "Publish it first.",
                    "error_type": "target_not_published",
                    "target_type": target_type,
                    "target_id": target_id,
                }
            )

        try:
            schedule = await self.manager.acreate(
                name=name,
                cron=cron,
                endpoint=resolved_endpoint,
                method=resolved_method,
                description=description,
                payload=resolved_payload,
                timezone=timezone or self.default_timezone,
                if_exists="update",
                user_id=self._owner(run_context),
            )
            log_debug(f"Schedule created: {schedule.name} ({schedule.cron_expr})")
            return json.dumps(
                {
                    "status": "created",
                    "id": schedule.id,
                    "name": schedule.name,
                    "cron": schedule.cron_expr,
                    "endpoint": schedule.endpoint,
                    "timezone": schedule.timezone,
                    "enabled": schedule.enabled,
                    "description": schedule.description,
                }
            )
        except Exception as e:
            logger.exception("Failed to create schedule")
            return json.dumps({"error": str(e)})

    async def alist_schedules(self, enabled_only: bool = False, run_context: Optional[RunContext] = None) -> str:
        """List all existing schedules.

        Args:
            enabled_only (bool): If True, only return enabled schedules. Defaults to False.

        Returns:
            str: JSON string with the list of schedules.
        """
        try:
            enabled_filter = True if enabled_only else None
            schedules = await self.manager.alist(enabled=enabled_filter, user_id=self._owner(run_context))
            result = [
                {
                    "id": s.id,
                    "name": s.name,
                    "cron": s.cron_expr,
                    "endpoint": s.endpoint,
                    "timezone": s.timezone,
                    "enabled": s.enabled,
                    "description": s.description,
                }
                for s in schedules
            ]
            return json.dumps({"schedules": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to list schedules")
            return json.dumps({"error": str(e)})

    async def aget_schedule(self, schedule_id: str, run_context: Optional[RunContext] = None) -> str:
        """Get details of a specific schedule by its ID.

        Args:
            schedule_id (str): The ID of the schedule to retrieve.

        Returns:
            str: JSON string with the schedule details.
        """
        try:
            schedule = await self.manager.aget(schedule_id, user_id=self._owner(run_context))
            if schedule is None:
                return json.dumps({"error": f"Schedule not found: {schedule_id}"})
            return json.dumps(
                {
                    "id": schedule.id,
                    "name": schedule.name,
                    "cron": schedule.cron_expr,
                    "endpoint": schedule.endpoint,
                    "method": schedule.method,
                    "timezone": schedule.timezone,
                    "enabled": schedule.enabled,
                    "description": schedule.description,
                    "payload": schedule.payload,
                }
            )
        except Exception as e:
            logger.exception("Failed to get schedule")
            return json.dumps({"error": str(e)})

    async def adelete_schedule(self, schedule_id: str, run_context: Optional[RunContext] = None) -> str:
        """Delete a schedule by its ID. This permanently removes the schedule.

        Args:
            schedule_id (str): The ID of the schedule to delete.

        Returns:
            str: JSON string confirming deletion.
        """
        try:
            deleted = await self.manager.adelete(schedule_id, user_id=self._owner(run_context))
            if deleted:
                return json.dumps({"status": "deleted", "id": schedule_id})
            return json.dumps({"error": f"Schedule not found or could not be deleted: {schedule_id}"})
        except Exception as e:
            logger.exception("Failed to delete schedule")
            return json.dumps({"error": str(e)})

    async def aenable_schedule(self, schedule_id: str, run_context: Optional[RunContext] = None) -> str:
        """Enable a disabled schedule so it starts running again.

        Args:
            schedule_id (str): The ID of the schedule to enable.

        Returns:
            str: JSON string with the updated schedule details.
        """
        try:
            existing = await self.manager.aget(schedule_id, user_id=self._owner(run_context))
            if existing is None:
                return json.dumps({"error": f"Schedule not found: {schedule_id}"})
            # A schedule aimed at an archived component can only 404 at fire
            # time; restoring the component is the way to turn it back on. A
            # target without a catalog row is a live code-defined component.
            refusal = await aarchived_target_refusal(self.manager.db, existing, user_id=self._owner(run_context))
            if refusal is not None:
                target_type, target_id = refusal
                return json.dumps(
                    {
                        "error": f"Cannot enable '{existing.name}': its target "
                        f"{target_type} '{target_id}' is archived. "
                        "Restore the component first.",
                        "error_type": "target_archived",
                        "target_type": target_type,
                        "target_id": target_id,
                    }
                )
            # A schedule fires the live published version, so a draft-only
            # target can only 404 on every tick. The REST enable route applies
            # the same predicate; keep the two surfaces in step.
            draft_target = await adraft_target_refusal(
                self.manager.db,
                existing,
                user_id=self._owner(run_context),
                is_code_defined=self._code_defined,
            )
            if draft_target is not None:
                target_type, target_id = draft_target
                return json.dumps(
                    {
                        "error": f"Cannot enable '{existing.name}': its target "
                        f"{target_type} '{target_id}' has no published version. "
                        "Publish it first.",
                        "error_type": "target_not_published",
                        "target_type": target_type,
                        "target_id": target_id,
                    }
                )
            # A drift-disabled row re-arms only once its endpoint matches its
            # provenance target again; otherwise it just fails on the next tick.
            drift = endpoint_drift_refusal(existing)
            if drift is not None:
                return json.dumps(
                    {
                        "error": f"Cannot enable '{existing.name}': it was disabled because its "
                        f"endpoint no longer matches its target ({drift}). "
                        "Repoint the endpoint back at the target first.",
                        "error_type": "endpoint_drift",
                        "target_type": existing.target_type,
                        "target_id": existing.target_id,
                    }
                )
            schedule = await self.manager.aenable(schedule_id, user_id=self._owner(run_context))
            if schedule is None:
                return json.dumps({"error": f"Schedule not found: {schedule_id}"})
            return json.dumps(
                {
                    "status": "enabled",
                    "id": schedule.id,
                    "name": schedule.name,
                    "enabled": schedule.enabled,
                }
            )
        except Exception as e:
            logger.exception("Failed to enable schedule")
            return json.dumps({"error": str(e)})

    async def adisable_schedule(self, schedule_id: str, run_context: Optional[RunContext] = None) -> str:
        """Disable a schedule so it stops running. Can be re-enabled later.

        Args:
            schedule_id (str): The ID of the schedule to disable.

        Returns:
            str: JSON string with the updated schedule details.
        """
        try:
            schedule = await self.manager.adisable(schedule_id, user_id=self._owner(run_context))
            if schedule is None:
                return json.dumps({"error": f"Schedule not found: {schedule_id}"})
            return json.dumps(
                {
                    "status": "disabled",
                    "id": schedule.id,
                    "name": schedule.name,
                    "enabled": schedule.enabled,
                }
            )
        except Exception as e:
            logger.exception("Failed to disable schedule")
            return json.dumps({"error": str(e)})

    async def atrigger_schedule(self, schedule_id: str, run_context: Optional[RunContext] = None) -> str:
        """Queue an enabled schedule to run now.

        Sets the schedule's next run time to now; the scheduler poller claims and
        executes it within one poll interval. The regular cron cadence resumes
        after the run.

        Args:
            schedule_id (str): The ID of the schedule to trigger.

        Returns:
            str: JSON string confirming the trigger.
        """
        try:
            owner = self._owner(run_context)
            schedule = await self.manager.aget(schedule_id, user_id=owner)
            if schedule is None:
                return json.dumps({"error": f"Schedule not found: {schedule_id}"})
            if not schedule.enabled:
                return json.dumps(
                    {"error": f"Schedule is disabled: {schedule_id}. Call enable_schedule first, then trigger it."}
                )
            await self.manager.aupdate(schedule_id, user_id=owner, next_run_at=int(time.time()))
            return json.dumps(
                {
                    "status": "triggered",
                    "id": schedule_id,
                    "note": "The scheduler poller will execute it within one poll interval.",
                }
            )
        except Exception as e:
            logger.exception("Failed to trigger schedule")
            return json.dumps({"error": str(e)})

    async def aget_schedule_runs(
        self, schedule_id: str, limit: int = 10, run_context: Optional[RunContext] = None
    ) -> str:
        """Get the run history for a schedule.

        Args:
            schedule_id (str): The ID of the schedule to get runs for.
            limit (int): Maximum number of runs to return. Defaults to 10.

        Returns:
            str: JSON string with the list of runs.
        """
        try:
            runs = await self.manager.aget_runs(schedule_id, limit=limit, user_id=self._owner(run_context))
            result = [
                {
                    "id": r.id,
                    "status": r.status,
                    "triggered_at": r.triggered_at,
                    "completed_at": r.completed_at,
                    "error": r.error,
                }
                for r in runs
            ]
            return json.dumps({"runs": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to get schedule runs")
            return json.dumps({"error": str(e)})
