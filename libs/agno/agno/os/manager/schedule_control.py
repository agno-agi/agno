"""Super Agent pauses, resumes and deletes schedules for the person in chat.

Every change goes through the handler of the API route that makes it, as the chatting person. The
rules are the API's: a person changes their own schedules, a person with the Routine permissions
pauses and resumes a Routine, and an administrator pauses, resumes and deletes any schedule and
pauses and resumes Company automation. A refusal says why, and what works.
"""

from dataclasses import replace
from typing import Any, Dict, List, Optional, Tuple
from weakref import ReferenceType, ref

from agno.db.schemas.scheduler import COMPANY_AUTOMATION_SCHEDULE_ID, Schedule
from agno.tools.company import _OptionalString
from agno.tools.toolkit import Toolkit

# What a person is told when Company automation is paused. The Scheduler page says the same.
AUTOMATION_PAUSED_EFFECT = (
    "While Company automation is paused, nothing happens on its own in Company: Ready Tasks that nobody started are not "
    "started, Tasks a Routine proposed are not accepted by auto-accept, and Projects are not completed by "
    "auto-accept. Routines still run on their own schedules and propose work, and people can still accept "
    "and start Tasks."
)
_ADMIN_ONLY = "Only an administrator can {action} it. Ask an administrator to ask here."
_ASYNC_ONLY = "Changing a schedule needs an asynchronous run. Ask again in a conversation with Super Agent."


def _kind(schedule: Schedule) -> str:
    """automation, routine (a Company Routine with a Goal), company (Company's, with no Goal) or person."""
    if schedule.id == COMPANY_AUTOMATION_SCHEDULE_ID:
        return "automation"
    if schedule.managed_by != "company":
        return "person"
    return "routine" if ((schedule.payload or {}).get("metadata") or {}).get("goal_id") else "company"


def _goal_id(schedule: Schedule) -> Optional[str]:
    return ((schedule.payload or {}).get("metadata") or {}).get("goal_id")


def _routine_name(schedule: Schedule) -> str:
    goal_id = _goal_id(schedule)
    return schedule.name.removeprefix(goal_id + ".") if goal_id else schedule.name


class ScheduleControlTools(Toolkit):
    """Pause, resume or delete one schedule, named by ID or by name."""

    def __init__(self, agent_os: Any):
        self._agent_os: ReferenceType[Any] = ref(agent_os)
        names = ["pause_schedule", "resume_schedule", "delete_schedule"]
        super().__init__(
            name="schedule_control",
            tools=[getattr(self, name) for name in names],
            async_tools=[(getattr(self, "a" + name), name) for name in names],
            # A deleted schedule and its run history cannot be brought back, so the person confirms it.
            requires_confirmation_tools=["delete_schedule"],
        )

    # ------------------------------------------------------------------ the person and their rights

    def _person(self, run_context: Any, operation: str) -> Tuple[Any, Any, Any, Any]:
        """The OS, its app, and the chatting person's authority and identity. Raises for every other caller."""
        from agno.os.manager.company_tasks import _run_context_identity, _unsigned
        from agno.tools.company import _require_human_creation

        agent_os = self._agent_os()
        app = getattr(agent_os, "_manager_app", None)
        if agent_os is None or app is None or getattr(agent_os, "_schedule_api_disable", None) is None:
            raise LookupError("The Scheduler API is not running here")
        _require_human_creation(run_context, operation)
        authority, user_id = _run_context_identity(run_context)
        if _unsigned(agent_os, authority, user_id):
            raise PermissionError(f"A signed-in person is required to {operation}")
        return agent_os, app, authority, user_id

    @staticmethod
    async def _may(authority: Any, resource: str, action: str) -> bool:
        if authority is None:
            return True
        try:
            await authority.arequire(resource, action)
        except PermissionError:
            return False
        return True

    @staticmethod
    def _administers(app: Any, request: Any) -> bool:
        """The Scheduler API's own rule for who may stop any schedule."""
        from agno.os.auth import _authorization_enforced
        from agno.os.middleware.user_scope import caller_is_admin

        return caller_is_admin(request) or not _authorization_enforced(app)

    async def _rights(self, app: Any, authority: Any, request: Any) -> Dict[str, bool]:
        return {
            "admin": self._administers(app, request),
            "schedules_write": await self._may(authority, "schedules", "write"),
            "schedules_delete": await self._may(authority, "schedules", "delete"),
            "routines_write": await self._may(authority, "routines", "write"),
        }

    @staticmethod
    def _allowed(schedule: Schedule, rights: Dict[str, bool], visible: bool) -> List[str]:
        """What this person can do to this schedule: pause, resume, delete."""
        kind = _kind(schedule)
        if kind == "automation":
            return ["pause", "resume"] if rights["admin"] else []
        if kind == "company":
            return ["pause", "delete"] if rights["admin"] else []
        if kind == "routine":
            stop = rights["admin"] or (rights["routines_write"] and rights["schedules_write"])
            return (["pause", "resume"] if stop else []) + (["delete"] if rights["admin"] else [])
        if not visible:
            return []
        return (["pause", "resume"] if rights["schedules_write"] else []) + (
            ["delete"] if rights["schedules_delete"] else []
        )

    async def _goal_names(self, agent_os: Any, schedules: List[Schedule]) -> Dict[str, Dict[str, Any]]:
        from agno.company.execution import _call

        company_db = getattr(agent_os, "_company_db", None)
        goals: Dict[str, Dict[str, Any]] = {}
        if company_db is None:
            return goals
        for goal_id in {_goal_id(schedule) for schedule in schedules} - {None}:
            try:
                goal = await _call(company_db, "get_goal", goal_id, include_deleted=True)
            except Exception:
                goal = None
            if goal is not None:
                goals[str(goal_id)] = goal
        return goals

    @staticmethod
    def _label(schedule: Schedule, goals: Dict[str, Dict[str, Any]]) -> str:
        kind = _kind(schedule)
        if kind == "automation":
            return "Company automation, the built-in hourly schedule"
        if kind == "company":
            return f"Company schedule '{schedule.name}', which names no Goal"
        if kind == "routine":
            goal = goals.get(str(_goal_id(schedule)))
            if goal is None:
                return f"Routine '{_routine_name(schedule)}', whose Goal is not stored"
            archived = ", which is archived" if goal.get("deleted_at") is not None else ""
            return f"Routine '{_routine_name(schedule)}' of Goal '{goal['name']}'{archived}"
        return f"schedule '{schedule.name}'"

    async def _all(self, agent_os: Any) -> List[Schedule]:
        from agno.scheduler import ScheduleManager

        return await ScheduleManager(agent_os.db).alist_all(raise_on_error=False)

    @staticmethod
    def _visible(schedule: Schedule, scoped_user_id: Optional[str]) -> bool:
        """Whether the Scheduler API shows this schedule to the person. Company's schedules are shared."""
        return scoped_user_id is None or schedule.user_id == scoped_user_id or schedule.managed_by == "company"

    # ------------------------------------------------------------------ changing

    async def _find(self, agent_os: Any, given: str, scoped: Optional[str]) -> Tuple[Optional[Schedule], Optional[str]]:
        """The schedule a person named by ID or by name, or what to tell them."""
        wanted = " ".join(str(given or "").split())
        schedules = await self._all(agent_os)
        by_id = [schedule for schedule in schedules if schedule.id == wanted]
        if by_id:
            return by_id[0], None
        folded = wanted.casefold()
        named = [
            schedule
            for schedule in schedules
            if self._visible(schedule, scoped)
            and folded in {schedule.name.casefold(), _routine_name(schedule).casefold()}
        ]
        if len(named) == 1:
            return named[0], None
        if not named:
            return None, f"Not done: no schedule has the ID or the name '{wanted}'. Ask the person for its ID."
        goals = await self._goal_names(agent_os, named)
        listed = "; ".join(f"{schedule.id} is {self._label(schedule, goals)}" for schedule in named)
        return None, f"Not done: {len(named)} schedules are named '{wanted}': {listed}. Call again with one ID."

    async def _change(self, action: str, given: str, run_context: Any, confirmed_name: Optional[str] = None) -> str:
        from fastapi import HTTPException

        from agno.company.routines import _person_request
        from agno.os.manager.company_tasks import _same_name
        from agno.os.middleware.user_scope import get_scoped_user_id
        from agno.run.authorization import authorization_scope
        from agno.tools.agentos import _epoch_to_iso

        try:
            agent_os, app, authority, user_id = self._person(run_context, f"{action} a schedule")
            request = _person_request(app, authority, user_id, "POST", "/schedules")
            scoped = get_scoped_user_id(request)
            schedule, problem = await self._find(agent_os, given, scoped)
            if schedule is None:
                return str(problem)
            goals = await self._goal_names(agent_os, [schedule])
            label, kind = self._label(schedule, goals), _kind(schedule)
            what = f"{label} ({schedule.id})"
            if confirmed_name is not None and not (
                _same_name(confirmed_name, schedule.name) or _same_name(confirmed_name, _routine_name(schedule))
            ):
                return (
                    f"Not done: schedule {schedule.id} is named '{_routine_name(schedule)}'. Call again with that name."
                )
            if kind == "automation" and action == "delete":
                return (
                    "Not done: Company automation cannot be deleted. An administrator can pause it with pause_schedule."
                )
            if kind == "company" and action == "resume":
                return f"Not done: {what} names no Goal, so it cannot run. It can be paused or deleted."
            rights = await self._rights(app, authority, request)
            visible = self._visible(schedule, scoped)
            if action not in self._allowed(schedule, rights, visible):
                if kind == "person" and not visible:
                    owner = f"user {schedule.user_id}" if schedule.user_id else "no user"
                    return (
                        f"Not done: schedule {schedule.id} exists and belongs to {owner}, so it is not yours to "
                        f"{action}. Its owner can {action} it, and so can an administrator."
                    )
                if kind == "person":
                    scope = "schedules:delete" if action == "delete" else "schedules:write"
                    return f"Not done: to {action} {what} you need the permission {scope}, which you do not have."
                if kind == "routine" and action != "delete":
                    return (
                        f"Not done: to {action} {what} you need the permissions routines:write and schedules:write, "
                        "which you do not have. A person who has them can do it here, and so can an administrator."
                    )
                can_pause = "pause" in self._allowed(schedule, rights, visible)
                pause = " You can pause it with pause_schedule." if can_pause and action == "delete" else ""
                return f"Not done: {what} is managed by Company. {_ADMIN_ONLY.format(action=action)}{pause}"
            routine_api = kind == "routine" and getattr(agent_os, "_routine_api_pause", None) is not None
            route = {"pause": "disable", "resume": "enable", "delete": "delete"}[action]
            handler = getattr(agent_os, f"_routine_api_{action}" if routine_api else f"_schedule_api_{route}")
            path = f"/company/routines/{schedule.id}" if routine_api else f"/schedules/{schedule.id}"
            request = _person_request(app, authority, user_id, "DELETE" if action == "delete" else "POST", path)
            saved = replace(authority, enforce_tools=False) if authority is not None else None
            with authorization_scope(lambda: saved):
                result = await handler(schedule.id, request)
        except HTTPException as exc:
            return f"Not done: {exc.detail}"
        except (LookupError, PermissionError, ValueError) as exc:
            return f"Not done: {exc}"
        if action == "delete":
            return f"Deleted {what}, with its run history. It cannot be brought back."
        if action == "pause":
            if kind == "automation":
                return (
                    f"Paused {what}, until it is resumed. Tell the person what this stops: {AUTOMATION_PAUSED_EFFECT}"
                )
            return f"Paused {what}. It does not run until it is resumed with resume_schedule."
        next_run = _epoch_to_iso((result or {}).get("next_run_at")) if isinstance(result, dict) else None
        return f"Resumed {what}." + (f" Its next run is at {next_run}." if next_run else "")

    def pause_schedule(self, schedule: str, _agno_run_context: Optional[Any] = None) -> str:
        """Pause a schedule so it stops running.

        Args:
            schedule: The schedule's ID, or its name.
        """
        return _ASYNC_ONLY

    async def apause_schedule(self, schedule: str, _agno_run_context: Optional[Any] = None) -> str:
        """Pause a schedule so it stops running, until it is resumed. Works for a person's schedule,
        a Company Routine, a Company schedule left with no Goal, and Company automation. Use it when
        a person asks to stop, kill, disable, pause or switch off a schedule or a Routine. When the
        person may not, the answer says why and who can.

        Args:
            schedule: The schedule's ID, or its name. Company automation's ID is agno-company-automation.
        """
        return await self._change("pause", schedule, _agno_run_context)

    def resume_schedule(self, schedule: str, _agno_run_context: Optional[Any] = None) -> str:
        """Resume a paused schedule.

        Args:
            schedule: The schedule's ID, or its name.
        """
        return _ASYNC_ONLY

    async def aresume_schedule(self, schedule: str, _agno_run_context: Optional[Any] = None) -> str:
        """Resume a paused schedule, so it runs again on its cron. A Routine resumes only while its
        Goal is active and its executor exists.

        Args:
            schedule: The schedule's ID, or its name. Company automation's ID is agno-company-automation.
        """
        return await self._change("resume", schedule, _agno_run_context)

    def delete_schedule(
        self, schedule_id: str, name: _OptionalString = None, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Delete a schedule and its run history.

        Args:
            schedule_id: The schedule's ID.
            name: The schedule's name; null when it is not known.
        """
        return _ASYNC_ONLY

    async def adelete_schedule(
        self, schedule_id: str, name: _OptionalString = None, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Delete a schedule and its run history, for good. The run pauses for the person to confirm
        it. Use it only when the person asked to delete or remove it; to stop it running, pause it.
        Company automation cannot be deleted.

        Args:
            schedule_id: The schedule's ID.
            name: The schedule's name, as stored, for the person to confirm. Null when the person
                gave only the ID and the name is not known: never put the ID here.
        """
        return await self._change("delete", schedule_id, _agno_run_context, confirmed_name=name)
