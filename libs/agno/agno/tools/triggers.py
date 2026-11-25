"""TriggerTools -- give agents the ability to create and manage triggers.

A trigger starts a run of an agent, team or workflow when an event arrives from a source, such
as a GitHub issue being opened. Sources are declared in code; these tools create, change and
remove the triggers on them. Wraps the TriggerManager, as SchedulerTools wraps the ScheduleManager.

Example:
    from agno.os.interfaces.github import GitHub
    from agno.tools.triggers import TriggerTools

    github = GitHub(repositories="acme/app")
    agent = Agent(
        model=OpenAIResponses(id="gpt-5.6-luna"),
        tools=[TriggerTools(db=db, sources=[github])],
    )
"""

import json
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from agno.db.schemas.scheduler import build_run_endpoint
from agno.db.schemas.triggers import CODE_MANAGED, NOT_DECLARED_REASON, StoredTrigger, TriggerEvent
from agno.run import RunContext
from agno.run.authorization import arequire_schedule_target, require_schedule_target, requires_permission
from agno.tools.scheduler import (
    CodeDefinedProbe,
    _manager_member_refusal,
    aarchived_endpoint_refusal,
    adraft_endpoint_refusal,
    archived_endpoint_refusal,
    code_defined_probe,
    draft_endpoint_refusal,
)
from agno.tools.toolkit import Toolkit
from agno.triggers.manager import TARGET_TYPES, TriggerManager
from agno.utils.log import log_debug, logger

# The most events one tool call lists.
MAX_LISTED_EVENTS = 100


def _error(message: str, error_type: Optional[str] = None, **details: Any) -> str:
    result: Dict[str, Any] = {"error": message}
    if error_type is not None:
        result["error_type"] = error_type
    result.update(details)
    return json.dumps(result)


def _described(trigger: StoredTrigger) -> Dict[str, Any]:
    """A trigger as a tool shows it: what it listens for and what it runs, never its saved authority."""
    return {
        "id": trigger.id,
        "name": trigger.name,
        "source_id": trigger.source_id,
        "events": trigger.events,
        "continue_on": trigger.continue_on,
        "filters": trigger.filters,
        "target_type": trigger.target_type,
        "target_id": trigger.target_id,
        "input": trigger.input,
        "enabled": trigger.enabled,
        "disabled_reason": trigger.disabled_reason,
        "description": trigger.description,
        "declared_in_code": trigger.managed_by == CODE_MANAGED,
    }


def _event_described(event: TriggerEvent) -> Dict[str, Any]:
    return {
        "id": event.id,
        "kind": event.kind,
        "event_key": event.event_key,
        "status": event.status,
        "reason": event.reason,
        "error": event.error,
        "run_id": event.run_id,
        "session_id": event.session_id,
        "created_at": event.created_at,
        "completed_at": event.completed_at,
    }


class TriggerTools(Toolkit):
    """Toolkit that lets an agent create and manage triggers.

    Args:
        db: A database adapter that stores triggers (PostgreSQL or SQLite).
        sources: The sources of events triggers may be created on, e.g. ``[github]``: the
            interfaces of the AgentOS that hand their deliveries to triggers. A trigger cannot be
            created on a source that is not listed.
        os_id: The AgentOS the triggers belong to. Only that AgentOS matches deliveries against
            them and runs their events. Without one, any AgentOS on the database that has the
            source does.
        user_id: Fixed owner for every trigger operation. When unset, the owner is taken from
            the run's ``user_id`` (injected via ``run_context``), so each user's agent only sees
            and edits that user's triggers.
        include_agents: Optional live list (e.g. ``agent_os.agents``) of the code-defined agents
            this process serves. A trigger aimed at one is exempt from the draft-only refusal:
            run routes resolve code-defined components before they consult the component catalog.
        include_teams: Same as ``include_agents`` but for teams.
        include_workflows: Same as ``include_agents`` but for workflows.
        wake: Called after an event is stored for replay, so a poller in this process runs it
            at once. Without it the replay runs at the poller's next poll.
    """

    def __init__(
        self,
        db: Any,
        sources: Optional[Sequence[Any]] = None,
        os_id: Optional[str] = None,
        user_id: Optional[str] = None,
        include_agents: Optional[Sequence[Any]] = None,
        include_teams: Optional[Sequence[Any]] = None,
        include_workflows: Optional[Sequence[Any]] = None,
        wake: Optional[Callable[[], Any]] = None,
        **kwargs: Any,
    ):
        self.manager = TriggerManager(db=db)
        self.sources = sources
        self.os_id = os_id
        self.user_id = user_id
        self.include_agents = include_agents
        self.include_teams = include_teams
        self.include_workflows = include_workflows
        self.wake = wake

        tools: List[Callable] = [
            self.list_trigger_sources,
            self.create_trigger,
            self.list_triggers,
            self.get_trigger,
            self.enable_trigger,
            self.disable_trigger,
            self.delete_trigger,
            self.get_trigger_events,
            self.replay_trigger_event,
        ]

        async_tools: List[tuple[Callable[..., Any], str]] = [
            (self.alist_trigger_sources, "list_trigger_sources"),
            (self.acreate_trigger, "create_trigger"),
            (self.alist_triggers, "list_triggers"),
            (self.aget_trigger, "get_trigger"),
            (self.aenable_trigger, "enable_trigger"),
            (self.adisable_trigger, "disable_trigger"),
            (self.adelete_trigger, "delete_trigger"),
            (self.aget_trigger_events, "get_trigger_events"),
            (self.areplay_trigger_event, "replay_trigger_event"),
        ]

        super().__init__(
            name="triggers",
            tools=tools,
            async_tools=async_tools,
            instructions=(
                "Use these tools to create and manage triggers. A trigger starts a run of an agent, team or "
                "workflow when an event arrives from a source, such as a GitHub issue being opened. "
                "When a user asks for something to happen whenever an event occurs, call list_trigger_sources "
                "to see the sources and the event kinds they send, then create_trigger with the instruction "
                "for the run as its input. Triggers only exist on the sources listed: a source is added in "
                "code, not here. To see why an event started no run, call get_trigger_events."
            ),
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _owner(self, run_context: Optional[RunContext]) -> Optional[str]:
        """Resolve the acting owner: a fixed toolkit user_id wins, else the run's user."""
        if self.user_id is not None:
            return self.user_id
        return run_context.user_id if run_context is not None else None

    @property
    def _code_defined(self) -> Optional[CodeDefinedProbe]:
        """Probe over this toolkit's in-process components, or None when it has none."""
        return code_defined_probe(self.include_agents, self.include_teams, self.include_workflows)

    def _declared_sources(self) -> Dict[str, Any]:
        return {source.id: source for source in (self.sources or [])}

    def _sources_listed(self) -> str:
        sources = [
            {"id": source.id, "type": source.type, "event_kinds": list(getattr(source, "event_kinds", ()))}
            for source in self._declared_sources().values()
        ]
        return json.dumps({"sources": sources, "count": len(sources)})

    def _taken(self, trigger: Optional[StoredTrigger]) -> bool:
        """Whether a stored trigger is one this toolkit's AgentOS takes."""
        return trigger is not None and (self.os_id is None or trigger.os_id in (None, self.os_id))

    def _fields(
        self,
        name: str,
        source_id: str,
        events: List[str],
        target_type: str,
        target_id: str,
        input: str,
        continue_on: Optional[List[str]],
        filters: Optional[str],
        description: Optional[str],
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        """Check what a new trigger names without reading the database. An error, or the checked fields.

        The same limits as the API: names and ids are trimmed and bounded, and every event kind is
        a non-empty string.
        """
        for label, value, limit in (("name", name, 255), ("target_id", target_id, 255), ("input", input, None)):
            if not isinstance(value, str) or not value.strip():
                return _error(f"{label} must not be blank"), {}
            if limit is not None and len(value.strip()) > limit:
                return _error(f"{label} is at most {limit} characters"), {}
        if description is not None and len(description) > 1024:
            return _error("description is at most 1024 characters"), {}
        for label, kinds in (("events", events), ("continue_on", continue_on or [])):
            if not all(isinstance(kind, str) and kind.strip() for kind in kinds):
                return _error(f"{label} holds event kinds, e.g. issues.opened"), {}
        if not events:
            return _error("events holds at least one event kind, e.g. issues.opened"), {}
        sources = self._declared_sources()
        source = sources.get(source_id)
        if source is None:
            declared = ", ".join(sorted(sources)) or "none"
            return (
                _error(
                    f"Source '{source_id}' is not declared. Declared sources: {declared}. "
                    "A source is added in code, not through these tools.",
                    "source_not_declared",
                ),
                {},
            )
        if target_type not in TARGET_TYPES:
            return _error(f"target_type must be one of {list(TARGET_TYPES)}, got '{target_type}'"), {}
        internal = self._internal(target_type, target_id.strip())
        if internal:
            return internal, {}
        try:
            given = json.loads(filters) if filters else None
        except json.JSONDecodeError:
            return _error("Invalid JSON in filters parameter"), {}
        if given is not None and not isinstance(given, dict):
            return _error("filters is a JSON object"), {}
        try:
            stored_filters = source.validate_filters(given)
        except ValueError as exc:
            return _error(str(exc), "invalid_filters"), {}
        return None, {
            "name": name.strip(),
            "target_id": target_id.strip(),
            "input": input.strip(),
            "events": [kind.strip() for kind in events],
            "continue_on": [kind.strip() for kind in continue_on or []],
            "filters": stored_filters,
        }

    @staticmethod
    def _target_refused(
        change: str,
        name: str,
        archived: Optional[Tuple[str, str]],
        draft: Optional[Tuple[str, str]],
    ) -> Optional[str]:
        """The refusal of a target that could only fail when the trigger fires."""
        if archived is not None:
            return _error(
                f"Cannot {change} trigger '{name}': its target {archived[0]} '{archived[1]}' is archived. "
                "Restore the component first.",
                "target_archived",
                target_type=archived[0],
                target_id=archived[1],
            )
        if draft is not None:
            return _error(
                f"Cannot {change} trigger '{name}': its target {draft[0]} '{draft[1]}' has no published "
                "version. Publish it first.",
                "target_not_published",
                target_type=draft[0],
                target_id=draft[1],
            )
        return None

    @staticmethod
    def _internal(target_type: str, target_id: str) -> Optional[str]:
        # Checked on the path the server will resolve, as the API does: an id written with an
        # escape or a dot segment is the id it comes to.
        if _manager_member_refusal(build_run_endpoint(target_type, target_id)) is not None:
            return _error(
                "Manager specialists are internal. Give the trigger Super Agent as its target instead.",
                "target_internal",
            )
        return None

    def _check_target(self, change: str, name: str, target_type: str, target_id: str, owner: Optional[str]) -> Any:
        internal = self._internal(target_type, target_id)
        if internal:
            return internal
        # Scoped to the acting owner: an unscoped probe would disclose that another owner's component exists.
        endpoint = build_run_endpoint(target_type, target_id)
        archived = archived_endpoint_refusal(self.manager.db, endpoint, user_id=owner)
        draft = (
            None
            if archived is not None
            else draft_endpoint_refusal(self.manager.db, endpoint, user_id=owner, is_code_defined=self._code_defined)
        )
        return self._target_refused(change, name, archived, draft)

    async def _acheck_target(
        self, change: str, name: str, target_type: str, target_id: str, owner: Optional[str]
    ) -> Any:
        internal = self._internal(target_type, target_id)
        if internal:
            return internal
        endpoint = build_run_endpoint(target_type, target_id)
        archived = await aarchived_endpoint_refusal(self.manager.db, endpoint, user_id=owner)
        draft = (
            None
            if archived is not None
            else await adraft_endpoint_refusal(
                self.manager.db, endpoint, user_id=owner, is_code_defined=self._code_defined
            )
        )
        return self._target_refused(change, name, archived, draft)

    @staticmethod
    def _declared_in_code(name: str) -> str:
        return _error(
            f"Trigger '{name}' is declared in code. Change it in code, or use another name.", "declared_in_code"
        )

    @staticmethod
    def _left_by_code(trigger: StoredTrigger) -> bool:
        """Whether the trigger was declared in code and turned off at a start because the code no longer declares it."""
        return trigger.managed_by == CODE_MANAGED and trigger.disabled_reason == NOT_DECLARED_REASON

    @staticmethod
    def _kept(existing: Optional[StoredTrigger], description: Optional[str]) -> Dict[str, Any]:
        """What a create over an existing name leaves as stored: the tool has no argument for these."""
        if existing is None:
            return {"description": description}
        return {
            "description": description if description is not None else existing.description,
            "key_path": existing.key_path,
            "timeout_seconds": existing.timeout_seconds,
            "max_retries": existing.max_retries,
            "retry_delay_seconds": existing.retry_delay_seconds,
        }

    def _provenance(self, run_context: Optional[RunContext]) -> Dict[str, str]:
        provenance: Dict[str, str] = {}
        if self.os_id is not None:
            provenance["os_id"] = self.os_id
        run_id = getattr(run_context, "run_id", None)
        session_id = getattr(run_context, "session_id", None)
        if run_id:
            provenance["created_by_run_id"] = str(run_id)
        if session_id:
            provenance["created_by_session_id"] = str(session_id)
        return provenance

    def _woken(self) -> None:
        if self.wake is not None:
            try:
                self.wake()
            except Exception as exc:
                log_debug(f"The trigger poller could not be woken: {exc}")

    # ------------------------------------------------------------------
    # Sync tools
    # ------------------------------------------------------------------

    @requires_permission("triggers", "read")
    def list_trigger_sources(self, run_context: Optional[RunContext] = None) -> str:
        """List the sources of events a trigger can be created on, and the event kinds each commonly sends.

        Returns:
            str: JSON string with the sources.
        """
        return self._sources_listed()

    @requires_permission("triggers", "write")
    def create_trigger(
        self,
        name: str,
        source_id: str,
        events: List[str],
        target_type: str,
        target_id: str,
        input: str,
        continue_on: Optional[List[str]] = None,
        filters: Optional[str] = None,
        description: Optional[str] = None,
        run_context: Optional[RunContext] = None,
    ) -> str:
        """Create a trigger: when one of the events arrives from the source, the target is run with the input.

        Args:
            name (str): A unique name for the trigger (e.g. "triage-issues").
            source_id (str): The source the events come from, as list_trigger_sources shows it (e.g. "github").
            events (List[str]): The event kinds that start a run (e.g. ["issues.opened"]).
            target_type (str): What to run: "agent", "team" or "workflow".
            target_id (str): The id of the agent, team or workflow to run.
            input (str): The instruction for the run. The event is added after it.
            continue_on (List[str]): Event kinds that only continue a conversation the trigger already
                started (e.g. ["issue_comment.created"] so a reply on a handled issue is a new turn).
            filters (str): JSON string of the source's filter. For GitHub: {"allow": "members"} or
                {"allow": "anyone"} for who may start a run, and {"labels": ["agent"]} to limit it to labels.
            description (str): A human-readable description of what this trigger is for.

        Returns:
            str: JSON string with the created trigger details.
        """
        refusal, fields = self._fields(
            name, source_id, events, target_type, target_id, input, continue_on, filters, description
        )
        if refusal:
            return refusal
        name, target_id = fields["name"], fields["target_id"]
        owner = self._owner(run_context)
        try:
            # Names are unique within one AgentOS, so the name is looked up among this one's triggers.
            declared = self.manager.get_by_name(name, user_id=None, os_id=self.os_id)
            if declared is not None and declared.managed_by == CODE_MANAGED:
                return self._declared_in_code(name)
            refusal = self._check_target("create", name, target_type, target_id, owner)
            if refusal:
                return refusal
            existing = self.manager.get_by_name(name, user_id=owner, os_id=self.os_id)
            existed = existing is not None
            trigger = self.manager.create(
                source_id=source_id,
                target_type=target_type,
                if_exists="update",
                **self._kept(existing, description),
                user_id=owner,
                provenance=self._provenance(run_context),
                **fields,
            )
            log_debug(f"Trigger created: {trigger.name} ({trigger.source_id})")
            return json.dumps({"status": "updated" if existed else "created", **_described(trigger)})
        except Exception as e:
            logger.exception("Failed to create trigger")
            return json.dumps({"error": str(e)})

    @requires_permission("triggers", "read")
    def list_triggers(self, enabled_only: bool = False, run_context: Optional[RunContext] = None) -> str:
        """List all existing triggers.

        Args:
            enabled_only (bool): If True, only return enabled triggers. Defaults to False.

        Returns:
            str: JSON string with the list of triggers.
        """
        try:
            rows, _ = self.manager._call(
                "get_triggers",
                enabled=True if enabled_only else None,
                user_id=self._owner(run_context),
                os_id=self.os_id,
            )
            result = [_described(StoredTrigger.from_dict(row)) for row in rows]
            return json.dumps({"triggers": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to list triggers")
            return json.dumps({"error": str(e)})

    @requires_permission("triggers", "read")
    def get_trigger(self, trigger_id: str, run_context: Optional[RunContext] = None) -> str:
        """Get details of a specific trigger by its ID.

        Args:
            trigger_id (str): The ID of the trigger to retrieve.

        Returns:
            str: JSON string with the trigger details.
        """
        try:
            trigger = self.manager.get(trigger_id, user_id=self._owner(run_context))
            if not self._taken(trigger) or trigger is None:
                return json.dumps({"error": f"Trigger not found: {trigger_id}"})
            return json.dumps(_described(trigger))
        except Exception as e:
            logger.exception("Failed to get trigger")
            return json.dumps({"error": str(e)})

    @requires_permission("triggers", "write")
    def enable_trigger(self, trigger_id: str, run_context: Optional[RunContext] = None) -> str:
        """Enable a disabled trigger so its events start runs again.

        Args:
            trigger_id (str): The ID of the trigger to enable.

        Returns:
            str: JSON string with the updated trigger details.
        """
        try:
            owner = self._owner(run_context)
            existing = self.manager.get(trigger_id, user_id=owner)
            if not self._taken(existing) or existing is None:
                return json.dumps({"error": f"Trigger not found: {trigger_id}"})
            if self._left_by_code(existing):
                return self._declared_in_code(existing.name)
            refusal = self._check_target("enable", existing.name, existing.target_type, existing.target_id, owner)
            if refusal:
                return refusal
            # Turning it on puts its target back in reach of events, so it needs what creating it needs.
            require_schedule_target(build_run_endpoint(existing.target_type, existing.target_id))
            trigger = self.manager.enable(trigger_id, user_id=owner)
            if trigger is None:
                return json.dumps({"error": f"Trigger not found: {trigger_id}"})
            return json.dumps({"status": "enabled", "id": trigger.id, "name": trigger.name, "enabled": trigger.enabled})
        except Exception as e:
            logger.exception("Failed to enable trigger")
            return json.dumps({"error": str(e)})

    @requires_permission("triggers", "write")
    def disable_trigger(self, trigger_id: str, run_context: Optional[RunContext] = None) -> str:
        """Disable a trigger so its events start nothing. Can be re-enabled later.

        Args:
            trigger_id (str): The ID of the trigger to disable.

        Returns:
            str: JSON string with the updated trigger details.
        """
        try:
            owner = self._owner(run_context)
            if not self._taken(self.manager.get(trigger_id, user_id=owner)):
                return json.dumps({"error": f"Trigger not found: {trigger_id}"})
            trigger = self.manager.disable(trigger_id, user_id=owner)
            if trigger is None:
                return json.dumps({"error": f"Trigger not found: {trigger_id}"})
            return json.dumps(
                {"status": "disabled", "id": trigger.id, "name": trigger.name, "enabled": trigger.enabled}
            )
        except Exception as e:
            logger.exception("Failed to disable trigger")
            return json.dumps({"error": str(e)})

    @requires_permission("triggers", "delete")
    def delete_trigger(self, trigger_id: str, run_context: Optional[RunContext] = None) -> str:
        """Delete a trigger by its ID. This permanently removes the trigger and its stored events.

        Args:
            trigger_id (str): The ID of the trigger to delete.

        Returns:
            str: JSON string confirming deletion.
        """
        try:
            owner = self._owner(run_context)
            existing = self.manager.get(trigger_id, user_id=owner)
            if not self._taken(existing) or existing is None:
                return json.dumps({"error": f"Trigger not found: {trigger_id}"})
            if existing.managed_by == CODE_MANAGED:
                return self._declared_in_code(existing.name)
            if self.manager.delete(trigger_id, user_id=owner):
                return json.dumps({"status": "deleted", "id": trigger_id})
            return json.dumps({"error": f"Trigger not found or could not be deleted: {trigger_id}"})
        except Exception as e:
            logger.exception("Failed to delete trigger")
            return json.dumps({"error": str(e)})

    @requires_permission("triggers", "read")
    def get_trigger_events(self, trigger_id: str, limit: int = 10, run_context: Optional[RunContext] = None) -> str:
        """Get the recent events of a trigger: the runs it started, and the events it ignored with the reason.

        Args:
            trigger_id (str): The ID of the trigger.
            limit (int): Maximum number of events to return, from 1 to 100. Defaults to 10.

        Returns:
            str: JSON string with the events, newest first.
        """
        try:
            owner = self._owner(run_context)
            if not self._taken(self.manager.get(trigger_id, user_id=owner)):
                return json.dumps({"error": f"Trigger not found: {trigger_id}"})
            events = self.manager.get_events(
                trigger_id=trigger_id, limit=max(1, min(limit, MAX_LISTED_EVENTS)), user_id=owner
            )
            result = [_event_described(event) for event in events]
            return json.dumps({"events": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to get trigger events")
            return json.dumps({"error": str(e)})

    @requires_permission("triggers", "write")
    def replay_trigger_event(self, trigger_id: str, event_id: str, run_context: Optional[RunContext] = None) -> str:
        """Run a finished event of a trigger again. The first run keeps its record; this adds a second.

        Args:
            trigger_id (str): The ID of the trigger.
            event_id (str): The ID of the event to run again, as get_trigger_events shows it.

        Returns:
            str: JSON string with the new event, which the poller runs.
        """
        try:
            owner = self._owner(run_context)
            existing = self.manager.get(trigger_id, user_id=owner)
            if not self._taken(existing) or existing is None:
                return json.dumps({"error": f"Trigger not found: {trigger_id}"})
            internal = self._internal(existing.target_type, existing.target_id)
            if internal:
                return internal
            # A replay runs the target, so it needs the caller's own right to run it.
            require_schedule_target(build_run_endpoint(existing.target_type, existing.target_id))
            row = self.manager._call("get_trigger_event", event_id, user_id=owner)
            if row is None or row["trigger_id"] != trigger_id:
                return json.dumps({"error": f"Trigger event not found: {event_id}"})
            replay = self.manager.replay_event(event_id, user_id=owner)
            if replay is None:
                return json.dumps({"error": f"Trigger event not found: {event_id}"})
            self._woken()
            return json.dumps({"status": "replayed", "replayed_event_id": event_id, **_event_described(replay)})
        except ValueError as e:
            return _error(str(e), "cannot_replay")
        except Exception as e:
            logger.exception("Failed to replay trigger event")
            return json.dumps({"error": str(e)})

    # ------------------------------------------------------------------
    # Async tools
    # ------------------------------------------------------------------

    @requires_permission("triggers", "read")
    async def alist_trigger_sources(self, run_context: Optional[RunContext] = None) -> str:
        """List the sources of events a trigger can be created on, and the event kinds each commonly sends.

        Returns:
            str: JSON string with the sources.
        """
        return self._sources_listed()

    @requires_permission("triggers", "write")
    async def acreate_trigger(
        self,
        name: str,
        source_id: str,
        events: List[str],
        target_type: str,
        target_id: str,
        input: str,
        continue_on: Optional[List[str]] = None,
        filters: Optional[str] = None,
        description: Optional[str] = None,
        run_context: Optional[RunContext] = None,
    ) -> str:
        """Create a trigger: when one of the events arrives from the source, the target is run with the input.

        Args:
            name (str): A unique name for the trigger (e.g. "triage-issues").
            source_id (str): The source the events come from, as list_trigger_sources shows it (e.g. "github").
            events (List[str]): The event kinds that start a run (e.g. ["issues.opened"]).
            target_type (str): What to run: "agent", "team" or "workflow".
            target_id (str): The id of the agent, team or workflow to run.
            input (str): The instruction for the run. The event is added after it.
            continue_on (List[str]): Event kinds that only continue a conversation the trigger already
                started (e.g. ["issue_comment.created"] so a reply on a handled issue is a new turn).
            filters (str): JSON string of the source's filter. For GitHub: {"allow": "members"} or
                {"allow": "anyone"} for who may start a run, and {"labels": ["agent"]} to limit it to labels.
            description (str): A human-readable description of what this trigger is for.

        Returns:
            str: JSON string with the created trigger details.
        """
        refusal, fields = self._fields(
            name, source_id, events, target_type, target_id, input, continue_on, filters, description
        )
        if refusal:
            return refusal
        name, target_id = fields["name"], fields["target_id"]
        owner = self._owner(run_context)
        try:
            # Names are unique within one AgentOS, so the name is looked up among this one's triggers.
            declared = await self.manager.aget_by_name(name, user_id=None, os_id=self.os_id)
            if declared is not None and declared.managed_by == CODE_MANAGED:
                return self._declared_in_code(name)
            refusal = await self._acheck_target("create", name, target_type, target_id, owner)
            if refusal:
                return refusal
            existing = await self.manager.aget_by_name(name, user_id=owner, os_id=self.os_id)
            existed = existing is not None
            trigger = await self.manager.acreate(
                source_id=source_id,
                target_type=target_type,
                if_exists="update",
                **self._kept(existing, description),
                user_id=owner,
                provenance=self._provenance(run_context),
                **fields,
            )
            log_debug(f"Trigger created: {trigger.name} ({trigger.source_id})")
            return json.dumps({"status": "updated" if existed else "created", **_described(trigger)})
        except Exception as e:
            logger.exception("Failed to create trigger")
            return json.dumps({"error": str(e)})

    @requires_permission("triggers", "read")
    async def alist_triggers(self, enabled_only: bool = False, run_context: Optional[RunContext] = None) -> str:
        """List all existing triggers.

        Args:
            enabled_only (bool): If True, only return enabled triggers. Defaults to False.

        Returns:
            str: JSON string with the list of triggers.
        """
        try:
            rows, _ = await self.manager._acall(
                "get_triggers",
                enabled=True if enabled_only else None,
                user_id=self._owner(run_context),
                os_id=self.os_id,
            )
            result = [_described(StoredTrigger.from_dict(row)) for row in rows]
            return json.dumps({"triggers": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to list triggers")
            return json.dumps({"error": str(e)})

    @requires_permission("triggers", "read")
    async def aget_trigger(self, trigger_id: str, run_context: Optional[RunContext] = None) -> str:
        """Get details of a specific trigger by its ID.

        Args:
            trigger_id (str): The ID of the trigger to retrieve.

        Returns:
            str: JSON string with the trigger details.
        """
        try:
            trigger = await self.manager.aget(trigger_id, user_id=self._owner(run_context))
            if not self._taken(trigger) or trigger is None:
                return json.dumps({"error": f"Trigger not found: {trigger_id}"})
            return json.dumps(_described(trigger))
        except Exception as e:
            logger.exception("Failed to get trigger")
            return json.dumps({"error": str(e)})

    @requires_permission("triggers", "write")
    async def aenable_trigger(self, trigger_id: str, run_context: Optional[RunContext] = None) -> str:
        """Enable a disabled trigger so its events start runs again.

        Args:
            trigger_id (str): The ID of the trigger to enable.

        Returns:
            str: JSON string with the updated trigger details.
        """
        try:
            owner = self._owner(run_context)
            existing = await self.manager.aget(trigger_id, user_id=owner)
            if not self._taken(existing) or existing is None:
                return json.dumps({"error": f"Trigger not found: {trigger_id}"})
            if self._left_by_code(existing):
                return self._declared_in_code(existing.name)
            refusal = await self._acheck_target(
                "enable", existing.name, existing.target_type, existing.target_id, owner
            )
            if refusal:
                return refusal
            # Turning it on puts its target back in reach of events, so it needs what creating it needs.
            await arequire_schedule_target(build_run_endpoint(existing.target_type, existing.target_id))
            trigger = await self.manager.aenable(trigger_id, user_id=owner)
            if trigger is None:
                return json.dumps({"error": f"Trigger not found: {trigger_id}"})
            return json.dumps({"status": "enabled", "id": trigger.id, "name": trigger.name, "enabled": trigger.enabled})
        except Exception as e:
            logger.exception("Failed to enable trigger")
            return json.dumps({"error": str(e)})

    @requires_permission("triggers", "write")
    async def adisable_trigger(self, trigger_id: str, run_context: Optional[RunContext] = None) -> str:
        """Disable a trigger so its events start nothing. Can be re-enabled later.

        Args:
            trigger_id (str): The ID of the trigger to disable.

        Returns:
            str: JSON string with the updated trigger details.
        """
        try:
            owner = self._owner(run_context)
            if not self._taken(await self.manager.aget(trigger_id, user_id=owner)):
                return json.dumps({"error": f"Trigger not found: {trigger_id}"})
            trigger = await self.manager.adisable(trigger_id, user_id=owner)
            if trigger is None:
                return json.dumps({"error": f"Trigger not found: {trigger_id}"})
            return json.dumps(
                {"status": "disabled", "id": trigger.id, "name": trigger.name, "enabled": trigger.enabled}
            )
        except Exception as e:
            logger.exception("Failed to disable trigger")
            return json.dumps({"error": str(e)})

    @requires_permission("triggers", "delete")
    async def adelete_trigger(self, trigger_id: str, run_context: Optional[RunContext] = None) -> str:
        """Delete a trigger by its ID. This permanently removes the trigger and its stored events.

        Args:
            trigger_id (str): The ID of the trigger to delete.

        Returns:
            str: JSON string confirming deletion.
        """
        try:
            owner = self._owner(run_context)
            existing = await self.manager.aget(trigger_id, user_id=owner)
            if not self._taken(existing) or existing is None:
                return json.dumps({"error": f"Trigger not found: {trigger_id}"})
            if existing.managed_by == CODE_MANAGED:
                return self._declared_in_code(existing.name)
            if await self.manager.adelete(trigger_id, user_id=owner):
                return json.dumps({"status": "deleted", "id": trigger_id})
            return json.dumps({"error": f"Trigger not found or could not be deleted: {trigger_id}"})
        except Exception as e:
            logger.exception("Failed to delete trigger")
            return json.dumps({"error": str(e)})

    @requires_permission("triggers", "read")
    async def aget_trigger_events(
        self, trigger_id: str, limit: int = 10, run_context: Optional[RunContext] = None
    ) -> str:
        """Get the recent events of a trigger: the runs it started, and the events it ignored with the reason.

        Args:
            trigger_id (str): The ID of the trigger.
            limit (int): Maximum number of events to return, from 1 to 100. Defaults to 10.

        Returns:
            str: JSON string with the events, newest first.
        """
        try:
            owner = self._owner(run_context)
            if not self._taken(await self.manager.aget(trigger_id, user_id=owner)):
                return json.dumps({"error": f"Trigger not found: {trigger_id}"})
            events = await self.manager.aget_events(
                trigger_id=trigger_id, limit=max(1, min(limit, MAX_LISTED_EVENTS)), user_id=owner
            )
            result = [_event_described(event) for event in events]
            return json.dumps({"events": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to get trigger events")
            return json.dumps({"error": str(e)})

    @requires_permission("triggers", "write")
    async def areplay_trigger_event(
        self, trigger_id: str, event_id: str, run_context: Optional[RunContext] = None
    ) -> str:
        """Run a finished event of a trigger again. The first run keeps its record; this adds a second.

        Args:
            trigger_id (str): The ID of the trigger.
            event_id (str): The ID of the event to run again, as get_trigger_events shows it.

        Returns:
            str: JSON string with the new event, which the poller runs.
        """
        try:
            owner = self._owner(run_context)
            existing = await self.manager.aget(trigger_id, user_id=owner)
            if not self._taken(existing) or existing is None:
                return json.dumps({"error": f"Trigger not found: {trigger_id}"})
            internal = self._internal(existing.target_type, existing.target_id)
            if internal:
                return internal
            # A replay runs the target, so it needs the caller's own right to run it.
            await arequire_schedule_target(build_run_endpoint(existing.target_type, existing.target_id))
            row = await self.manager._acall("get_trigger_event", event_id, user_id=owner)
            if row is None or row["trigger_id"] != trigger_id:
                return json.dumps({"error": f"Trigger event not found: {event_id}"})
            replay = await self.manager.areplay_event(event_id, user_id=owner)
            if replay is None:
                return json.dumps({"error": f"Trigger event not found: {event_id}"})
            self._woken()
            return json.dumps({"status": "replayed", "replayed_event_id": event_id, **_event_described(replay)})
        except ValueError as e:
            return _error(str(e), "cannot_replay")
        except Exception as e:
            logger.exception("Failed to replay trigger event")
            return json.dumps({"error": str(e)})
