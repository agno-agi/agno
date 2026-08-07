"""StudioTools -- give agents the ability to compose agents, teams, and workflows.

Uses the AgentOS Registry (tools, models, dbs, functions) and the core
component APIs (Agent, Team, Workflow, Step) to dynamically create, edit,
version, and execute components described in natural language.

Typical use:
    from agno.tools.studio import StudioTools

    studio_agent = Agent(
        model=Claude(id="claude-sonnet-4-5"),
        tools=[StudioTools(registry=registry, db=db)],
    )

    studio_agent.print_response(
        "Create an agent named 'math-tutor' that uses claude-sonnet-4-5 and "
        "the calculator toolkit."
    )

Semantics:
    * create_* persists a new component with a single published config.
    * edit_* loads the component, applies the patch, and saves it:
      - with versions=True the edit is saved as a draft (an existing draft is
        updated in place; otherwise a new draft version is created). Use
        publish_component() to promote the draft to published+current.
      - with versions=False (default) the edit is published immediately as a
        new current version. Each edit creates a new published version; prior
        versions remain in history (they are immutable).
    * run_* execute a component as the current user, with one sub-session per
      calling conversation and PAUSED results that carry their unresolved
      requirements. The implementation is StudioRunnerTools
      (agno.tools.studio_runner), which platforms can also mount standalone
      as a dispatch-only surface -- discovery and execution without the
      Studio's mutation tools.

Enable flags:
    * Default: only agent operations are exposed (agents=True, teams=False,
      workflows=False). Discovery functions are always available.
    * Pass teams=True / workflows=True to also expose those operations.
    * Passing agents=False without enabling teams or workflows leaves only
      discovery tools registered.
    * Passing agents_list auto-enables teams and workflows (you can build them
      from those agents). Passing teams_list auto-enables workflows. Explicit
      False overrides the auto-enable.
    * Versioning tools (list_versions, get_version, publish_component,
      set_current_version, delete_version) are exposed only when versions=True.
    * Schedule tools (create_schedule, list_schedules, get_schedule,
      get_schedule_runs, trigger_schedule, enable_schedule, disable_schedule,
      delete_schedule) are exposed only when schedules=True. create_schedule is
      Studio's own (component-aware targets); the management tools are shared
      with SchedulerTools.

Persistence:
    * Studio saves ONLY the component it creates/edits. It does NOT cascade to
      member agents or step agents -- those are assumed to be code-defined
      (registry / passed-in lists) or separately persisted by a prior create_*.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union

from agno.run import RunContext
from agno.tools.function import Function
from agno.tools.studio_runner import AmbiguousComponentNameError, StudioRunnerError, StudioRunnerTools, _slugify
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, logger

if TYPE_CHECKING:
    from agno.agent.agent import Agent
    from agno.db.base import BaseDb
    from agno.models.base import Model
    from agno.registry.registry import Registry
    from agno.scheduler.manager import ScheduleManager
    from agno.team.team import Team
    from agno.tools.scheduler import SchedulerTools
    from agno.workflow.workflow import Workflow

Component = Union["Agent", "Team", "Workflow"]
TeamMember = Union["Agent", "Team"]

_SCHEDULE_TARGET_TYPES = ("agent", "team", "workflow")


class StudioTools(Toolkit):
    """Toolkit that lets an agent compose agents, teams, and workflows.

    Args:
        registry: Registry holding models, tools, databases, and code-defined
            agents/teams available for composition.
        db: Database for persisting components. Falls back to ``registry.dbs[0]``.
        agents_list: Optional live list (e.g. ``agent_os.agents``) used only for
            discovery in ``list_agents()``. Studio-created components are NOT
            appended to this list -- they are DB components, so appending would
            duplicate them in AgentOS's ``/agents`` response.
        teams_list: Same as ``agents_list`` but for teams.
        workflows_list: Same as ``agents_list`` but for workflows.
        default_model_id: Model id to use when a caller omits one.
        default_num_history_runs: History depth for created agents and teams
            when a caller omits ``num_history_runs``. None lets the
            component's own default apply.
        agents: Expose agent operations. Defaults to True.
        teams: Expose team operations. Defaults to False (see module docstring
            for auto-enable rules).
        workflows: Expose workflow operations. Defaults to False.
        versions: Expose versioning tools (list_versions, get_version,
            publish_component, set_current_version, delete_version). Defaults
            to False; without versioning, edits publish immediately instead of
            producing drafts.
        list_limit: Cap on DB components returned by each list tool (default
            100). The list payloads report 'db_total' so a capped list is
            visible as capped.
        schedules: Expose schedule tools: Studio's own create_schedule
            (component-aware targets) plus the SchedulerTools management tools
            (list_schedules, get_schedule, get_schedule_runs, trigger_schedule,
            enable_schedule, disable_schedule, delete_schedule). Defaults to
            False. Requires the optional scheduler dependencies (croniter and
            pytz -- ``pip install agno[scheduler]``); when they are missing,
            the first schedule tool call that needs them returns an error JSON.
    """

    def __init__(
        self,
        registry: "Registry",
        db: Optional["BaseDb"] = None,
        agents_list: Optional[List["Agent"]] = None,
        teams_list: Optional[List["Team"]] = None,
        workflows_list: Optional[List["Workflow"]] = None,
        default_model_id: Optional[str] = None,
        default_num_history_runs: Optional[int] = None,
        agents: Optional[bool] = None,
        teams: Optional[bool] = None,
        workflows: Optional[bool] = None,
        versions: bool = False,
        schedules: bool = False,
        list_limit: int = 100,
        **kwargs: Any,
    ):
        self.registry = registry
        self.db: Optional["BaseDb"] = db if db is not None else (registry.dbs[0] if registry.dbs else None)
        self.agents_list = agents_list
        self.teams_list = teams_list
        self.workflows_list = workflows_list
        self.default_model_id = default_model_id
        self.default_num_history_runs = default_num_history_runs

        # Execution and component resolution live on StudioRunnerTools -- the
        # standalone dispatch toolkit. Studio registers its run tools from this
        # embedded instance and delegates its own lookups to it, so the builder
        # and a dispatcher resolve and run components one way.
        self._runner_tools = StudioRunnerTools(
            registry=registry,
            db=self.db,
            agents_list=agents_list,
            teams_list=teams_list,
            workflows_list=workflows_list,
            # The Studio holds the registry as its build palette and its run_* are
            # the smoke test for what it just composed, so its reach over registry
            # components is the point rather than an accident. A standalone runner
            # mounted on a router gets the narrower default.
            include_all_components=True,
            list_limit=list_limit,
        )

        self.enable_agents, self.enable_teams, self.enable_workflows = _resolve_flags(
            agents=agents,
            teams=teams,
            workflows=workflows,
            has_agents_list=agents_list is not None,
            has_teams_list=teams_list is not None,
        )
        self.enable_versions: bool = versions
        self.enable_schedules: bool = schedules
        # Schedule management is shared with SchedulerTools; Studio owns only
        # create_schedule (component targets, internally built endpoint).
        self._scheduler_tools: Optional["SchedulerTools"] = None
        if self.enable_schedules:
            from agno.tools.scheduler import SchedulerTools

            self._scheduler_tools = SchedulerTools(db=self.db)

        tools: List[Callable] = [
            # Discovery -- always available regardless of flags.
            self.list_models,
            self.list_tools,
            self.list_functions,
            self.list_dbs,
            self.list_agents,
            self.list_teams,
            self.list_workflows,
        ]

        if self.enable_agents:
            tools.extend(
                [
                    self.get_agent,
                    self.create_agent,
                    self.edit_agent,
                    self.delete_agent,
                    self.run_agent,
                ]
            )
        if self.enable_teams:
            tools.extend(
                [
                    self.get_team,
                    self.create_team,
                    self.edit_team,
                    self.delete_team,
                    self.run_team,
                ]
            )
        if self.enable_workflows:
            tools.extend(
                [
                    self.get_workflow,
                    self.create_workflow,
                    self.edit_workflow,
                    self.delete_workflow,
                    self.run_workflow,
                ]
            )

        # Versioning works on any component type, but is opt-in.
        if self.enable_versions:
            tools.extend(
                [
                    self.list_versions,
                    self.get_version,
                    self.publish_component,
                    self.set_current_version,
                    self.delete_version,
                ]
            )

        # Schedules target an existing component by id; opt-in.
        if self._scheduler_tools is not None:
            tools.extend(
                [
                    self.create_schedule,
                    self._scheduler_tools.list_schedules,
                    self._scheduler_tools.get_schedule,
                    self._scheduler_tools.get_schedule_runs,
                    self._scheduler_tools.trigger_schedule,
                    self._scheduler_tools.enable_schedule,
                    self._scheduler_tools.disable_schedule,
                    self._scheduler_tools.delete_schedule,
                ]
            )

        async_tools: List[tuple[Callable[..., Any], str]] = [
            (self.alist_models, "list_models"),
            (self.alist_tools, "list_tools"),
            (self.alist_functions, "list_functions"),
            (self.alist_dbs, "list_dbs"),
            (self.alist_agents, "list_agents"),
            (self.alist_teams, "list_teams"),
            (self.alist_workflows, "list_workflows"),
        ]
        if self.enable_agents:
            async_tools.extend(
                [
                    (self.aget_agent, "get_agent"),
                    (self.acreate_agent, "create_agent"),
                    (self.aedit_agent, "edit_agent"),
                    (self.adelete_agent, "delete_agent"),
                    (self.arun_agent, "run_agent"),
                ]
            )
        if self.enable_teams:
            async_tools.extend(
                [
                    (self.aget_team, "get_team"),
                    (self.acreate_team, "create_team"),
                    (self.aedit_team, "edit_team"),
                    (self.adelete_team, "delete_team"),
                    (self.arun_team, "run_team"),
                ]
            )
        if self.enable_workflows:
            async_tools.extend(
                [
                    (self.aget_workflow, "get_workflow"),
                    (self.acreate_workflow, "create_workflow"),
                    (self.aedit_workflow, "edit_workflow"),
                    (self.adelete_workflow, "delete_workflow"),
                    (self.arun_workflow, "run_workflow"),
                ]
            )
        if self.enable_versions:
            async_tools.extend(
                [
                    (self.alist_versions, "list_versions"),
                    (self.aget_version, "get_version"),
                    (self.apublish_component, "publish_component"),
                    (self.aset_current_version, "set_current_version"),
                    (self.adelete_version, "delete_version"),
                ]
            )
        if self._scheduler_tools is not None:
            async_tools.extend(
                [
                    (self.acreate_schedule, "create_schedule"),
                    (self._scheduler_tools.alist_schedules, "list_schedules"),
                    (self._scheduler_tools.aget_schedule, "get_schedule"),
                    (self._scheduler_tools.aget_schedule_runs, "get_schedule_runs"),
                    (self._scheduler_tools.atrigger_schedule, "trigger_schedule"),
                    (self._scheduler_tools.aenable_schedule, "enable_schedule"),
                    (self._scheduler_tools.adisable_schedule, "disable_schedule"),
                    (self._scheduler_tools.adelete_schedule, "delete_schedule"),
                ]
            )

        instruction_lines = [
            "Compose agents, teams, and workflows from registry primitives.",
            "Discovery: call list_tools/list_functions/list_models/list_dbs first. Tool and function names "
            "are exact and case-sensitive -- do NOT guess.",
            "Create: create_agent/create_team/create_workflow. When the user mentions specific "
            "tools, you MUST include ALL of those names in tool_names; do not silently drop any.",
            "Created agents and teams remember the session by default; pass "
            "add_history_to_context=False only for stateless components.",
            "Edit: ALWAYS call get_agent/get_team/get_workflow first to read the current state, "
            "then call edit_agent/edit_team/edit_workflow with only the fields that change.",
            "Run tools execute a component as the current user; a PAUSED result is waiting on human "
            "approval -- relay its requirements and keep the run_id/session_id for the resume.",
            "Component lookups accept an exact id or a display name; an ambiguous display name returns "
            "an error listing the matching ids -- retry with the exact id. Deletes require the exact id.",
            "Call a given component sequentially within a turn: parallel runs of the same component "
            "share one session and can overwrite each other.",
        ]
        if self.enable_versions:
            instruction_lines.extend(
                [
                    "Edits produce a draft. Call publish_component to promote the draft to published+current.",
                    "Versioning: list_versions shows all config versions; set_current_version rolls "
                    "back to a prior published version; delete_version removes a draft.",
                ]
            )
        else:
            instruction_lines.append("Edits are published immediately as the new current version.")
        if self.enable_teams:
            instruction_lines.append(
                "Team rules: member_ids must be ids returned by create_agent or present in list_agents."
            )
        if self.enable_workflows:
            instruction_lines.append(
                "Workflow rules: each step_spec is a dict with 'name' and exactly one of "
                "'agent_id', 'team_id', or 'function_name'. Use function_name values from list_functions."
            )
        if self.enable_schedules:
            instruction_lines.append(
                "Schedules: create_schedule targets an existing component by target_type "
                "('agent'/'team'/'workflow') + target_id (ids from list_agents/list_teams/list_workflows) "
                "and requires a message. Cron is 5-field; timezone is an IANA name. trigger_schedule "
                "queues an enabled schedule to run now via the platform poller."
            )

        # Toolkit instructions are only injected into the system message when
        # add_instructions is set, so default it on.
        kwargs.setdefault("add_instructions", True)
        super().__init__(
            name="studio",
            tools=tools,
            async_tools=async_tools,
            instructions="\n".join(instruction_lines),
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Registry lookups
    # ------------------------------------------------------------------

    def _find_model(self, model_id: Optional[str]) -> Optional["Model"]:
        target = model_id or self.default_model_id
        if target is None:
            return self.registry.models[0] if self.registry.models else None
        for model in self.registry.models:
            if getattr(model, "id", None) == target:
                return model
        return None

    def _find_db(self, db_id: Optional[str]) -> Optional["BaseDb"]:
        if db_id is None:
            return self.db
        return self.registry.get_db(db_id)

    def _find_tool(self, name: str) -> Optional[Any]:
        """Match by Toolkit.name, Function.name, callable __name__, or toolkit function key.

        Top-level name matches take precedence over functions found inside a
        toolkit. When a name matches more than one distinct registry entry
        (e.g. two toolkits sharing a name), a ValueError is raised instead of
        silently returning the first match -- resolving to whichever entry was
        registered first would wire the agent to the wrong tool.
        """
        matches: List[Any] = []
        function_matches: List[Any] = []
        for tool in self.registry.tools:
            if isinstance(tool, Toolkit):
                if tool.name == name:
                    matches.append(tool)
                elif name in tool.functions:
                    member = tool.functions[name]
                    # Stamp the attribution so a component saved with this bare
                    # Function keeps its "toolkit" key (see Registry.rehydrate_function).
                    if isinstance(tool.name, str) and tool.name:
                        member.owning_toolkit = tool.name
                    function_matches.append(member)
            elif isinstance(tool, Function):
                if tool.name == name:
                    matches.append(tool)
            elif callable(tool) and getattr(tool, "__name__", None) == name:
                matches.append(tool)

        candidates = matches or function_matches
        if not candidates:
            return None
        if len(candidates) > 1:
            raise ValueError(
                f"Tool name '{name}' is ambiguous: it matches {len(candidates)} registry entries. "
                "Give each tool a distinct name (e.g. MCPTools(name=...)) so it can be selected unambiguously."
            )
        return candidates[0]

    def _resolve_tools(self, names: Optional[List[str]]) -> List[Any]:
        if not names:
            return []
        resolved: List[Any] = []
        missing: List[str] = []
        for name in names:
            found = self._find_tool(name)
            if found is None:
                missing.append(name)
            else:
                resolved.append(found)
        if missing:
            raise ValueError(f"Tools not found in registry: {missing}")
        # Persisting a component serializes each toolkit's functions; a toolkit
        # with none (e.g. an MCP toolkit that never connected) would be silently
        # dropped from the config, permanently. Refuse instead.
        empty_toolkits = [t.name for t in resolved if isinstance(t, Toolkit) and not t.functions]
        if empty_toolkits:
            raise ValueError(
                f"Toolkits have no functions and cannot be persisted: {empty_toolkits}. "
                "An MCP toolkit has no functions until it is connected. Connect it before "
                "creating or editing components with it (AgentOS connects MCP tools found in "
                "the registry and on agents/teams/workflows at startup)."
            )
        return resolved

    def _normalize_tool_names(self, names: List[str]) -> List[str]:
        """Collapse toolkit function names back to their toolkit name."""
        func_to_toolkit: Dict[str, str] = {}
        for tool in self.registry.tools:
            if isinstance(tool, Toolkit):
                for fn_name in tool.functions:
                    func_to_toolkit[fn_name] = tool.name

        normalized: List[str] = []
        for name in names:
            mapped = func_to_toolkit.get(name, name)
            if mapped not in normalized:
                normalized.append(mapped)
        return normalized

    # ------------------------------------------------------------------
    # Component lookup -- delegated to the embedded StudioRunnerTools so the
    # builder and a standalone dispatcher resolve components one way: exact
    # ids first (code-defined, then DB), then display names (code-defined,
    # then DB, where an ambiguous name raises AmbiguousComponentNameError),
    # then the identifier's slug as an id.
    # ------------------------------------------------------------------

    def _iter_agents(self) -> List["Agent"]:
        return self._runner_tools._iter_agents()

    def _iter_teams(self) -> List["Team"]:
        return self._runner_tools._iter_teams()

    def _iter_workflows(self) -> List["Workflow"]:
        return self._runner_tools._iter_workflows()

    def _find_agent(self, agent_id: str) -> Optional["Agent"]:
        return self._runner_tools._find_agent(agent_id)

    def _find_team(self, team_id: str) -> Optional["Team"]:
        return self._runner_tools._find_team(team_id)

    def _find_workflow(self, workflow_id: str) -> Optional["Workflow"]:
        return self._runner_tools._find_workflow(workflow_id)

    # Edit-base lookups: like _find_*, but DB components load from the latest
    # draft when versioning is enabled, so successive partial edits accumulate
    # instead of each resetting to the published config.

    def _find_agent_for_edit(self, agent_id: str) -> Optional["Agent"]:
        for a in self._iter_agents():
            if getattr(a, "id", None) == agent_id:
                return a
        if self._runner_tools._db_component_exists("agent", agent_id):
            return self._load_agent_from_db(agent_id, version=self._edit_base_version(agent_id))
        resolved = self._runner_tools._resolve_db_id_by_name_or_slug("agent", agent_id)
        if resolved is None:
            return None
        return self._load_agent_from_db(resolved, version=self._edit_base_version(resolved))

    def _find_team_for_edit(self, team_id: str) -> Optional["Team"]:
        for t in self._iter_teams():
            if getattr(t, "id", None) == team_id:
                return t
        if self._runner_tools._db_component_exists("team", team_id):
            return self._load_team_from_db(team_id, version=self._edit_base_version(team_id))
        resolved = self._runner_tools._resolve_db_id_by_name_or_slug("team", team_id)
        if resolved is None:
            return None
        return self._load_team_from_db(resolved, version=self._edit_base_version(resolved))

    def _find_workflow_for_edit(self, workflow_id: str) -> Optional["Workflow"]:
        for w in self._iter_workflows():
            if getattr(w, "id", None) == workflow_id:
                return w
        if self._runner_tools._db_component_exists("workflow", workflow_id):
            return self._load_workflow_from_db(workflow_id, version=self._edit_base_version(workflow_id))
        resolved = self._runner_tools._resolve_db_id_by_name_or_slug("workflow", workflow_id)
        if resolved is None:
            return None
        return self._load_workflow_from_db(resolved, version=self._edit_base_version(resolved))

    def _is_code_defined(self, component_id: str, candidates: List[Any], component_type: str) -> bool:
        """True if the identifier refers to a code-defined (registry/list) component.

        Code-defined components are not DB-backed, so editing them would write an
        unreachable DB row that the live object always shadows. edit_* rejects
        these instead of silently persisting a draft no one can load.

        A display-name match only counts when the identifier is not an exact DB
        id: exact ids resolve to the DB component on every other path (id-first
        order), so the edit guard must agree.
        """
        for c in candidates:
            if getattr(c, "id", None) == component_id:
                return True
        for c in candidates:
            if getattr(c, "name", None) == component_id:
                return not self._runner_tools._db_component_exists(component_type, component_id)
        return False

    def _edit_base_version(self, component_id: str) -> Optional[int]:
        """Version to base an edit on: the latest draft when versioning is
        enabled, else None (the current published version)."""
        if not self.enable_versions:
            return None
        return self._latest_draft_version(component_id)

    def _latest_draft_version(self, component_id: str) -> Optional[int]:
        if self.db is None:
            return None
        configs = self.db.list_configs(component_id, include_config=False)
        drafts: List[int] = [
            c["version"] for c in configs if c.get("stage") == "draft" and isinstance(c.get("version"), int)
        ]
        return max(drafts) if drafts else None

    def _load_agent_from_db(self, agent_id: str, version: Optional[int] = None) -> Optional["Agent"]:
        return self._runner_tools._load_agent_from_db(agent_id, version=version)

    def _load_team_from_db(self, team_id: str, version: Optional[int] = None) -> Optional["Team"]:
        return self._runner_tools._load_team_from_db(team_id, version=version)

    def _load_workflow_from_db(self, workflow_id: str, version: Optional[int] = None) -> Optional["Workflow"]:
        return self._runner_tools._load_workflow_from_db(workflow_id, version=version)

    # ------------------------------------------------------------------
    # Discovery tools
    # ------------------------------------------------------------------

    def list_models(self) -> str:
        """List models available in the registry.

        Returns:
            str: JSON object with 'models' (each {id, provider}) and 'count'.
        """
        try:
            models = [{"id": getattr(m, "id", None), "provider": type(m).__name__} for m in self.registry.models]
            return json.dumps({"models": models, "count": len(models)})
        except Exception as e:
            logger.exception("Failed to list models")
            return json.dumps({"error": str(e) or type(e).__name__})

    def list_tools(self) -> str:
        """List toolkits and functions available in the registry.

        Returns:
            str: JSON object with 'tools' (each {name, kind, functions?}) and 'count'.
                'kind' is 'toolkit', 'function', or 'callable'.
        """
        try:
            result: List[Dict[str, Any]] = []
            for tool in self.registry.tools:
                if isinstance(tool, Toolkit):
                    result.append({"name": tool.name, "kind": "toolkit", "functions": list(tool.functions.keys())})
                elif isinstance(tool, Function):
                    result.append({"name": tool.name, "kind": "function"})
                elif callable(tool):
                    result.append({"name": getattr(tool, "__name__", repr(tool)), "kind": "callable"})
            return json.dumps({"tools": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to list tools")
            return json.dumps({"error": str(e) or type(e).__name__})

    def list_functions(self) -> str:
        """List raw functions available in the registry for workflow steps.

        Returns:
            str: JSON object with 'functions' (each {name, description, signature}) and 'count'.
        """
        try:
            import inspect

            result: List[Dict[str, Any]] = []
            for func in self.registry.functions:
                name = getattr(func, "__name__", None) or "anonymous"
                signature = None
                try:
                    signature = str(inspect.signature(func))
                except (TypeError, ValueError):
                    pass
                result.append(
                    {
                        "name": name,
                        "description": inspect.getdoc(func),
                        "signature": signature,
                    }
                )
            return json.dumps({"functions": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to list functions")
            return json.dumps({"error": str(e) or type(e).__name__})

    def list_dbs(self) -> str:
        """List databases available in the registry.

        Returns:
            str: JSON object with 'dbs' (each {id, class}) and 'count'.
        """
        try:
            dbs = [{"id": getattr(d, "id", None), "class": type(d).__name__} for d in self.registry.dbs]
            return json.dumps({"dbs": dbs, "count": len(dbs)})
        except Exception as e:
            logger.exception("Failed to list dbs")
            return json.dumps({"error": str(e) or type(e).__name__})

    def list_agents(self) -> str:
        """List all known agents: code-defined (registry / agents_list) plus DB components.

        Returns:
            str: JSON object with 'agents' (each {id, name, model_id, tools, source}), 'count', and
                'db_total' (DB components in storage; more than the db rows shown means the list
                is capped -- capped components still resolve by exact id). 'source' is 'code' for
                registry/list-defined agents, 'db' for DB components.
        """
        try:
            result: List[Dict[str, Any]] = []
            seen_ids: set[str] = set()
            idless_names: set[str] = set()  # code ids, plus the names of code components that have no id
            for a in self._iter_agents():
                aid = getattr(a, "id", None)
                name = getattr(a, "name", None)
                if aid is not None:
                    seen_ids.add(aid)
                elif name is not None:
                    idless_names.add(name)
                result.append(
                    {
                        "id": aid,
                        "name": name,
                        "model_id": getattr(getattr(a, "model", None), "id", None),
                        "tools": _summarize_tools(getattr(a, "tools", None)),
                        "source": "code",
                    }
                )
            db_rows, db_total = self._list_db_components("agent")
            # A DB component duplicates a code one when they share an id, or -- for a
            # code component with no id -- when they share a name. A name collision with
            # a code component that HAS its own id is a genuinely distinct component and
            # must stay listed (it is what get_/run_/edit_ resolve to).
            for row in db_rows:
                if row["id"] in seen_ids or row["name"] in idless_names:
                    continue
                result.append({**row, "source": "db"})
            return json.dumps({"agents": result, "count": len(result), "db_total": db_total})
        except Exception as e:
            logger.exception("Failed to list agents")
            return json.dumps({"error": str(e) or type(e).__name__})

    def list_teams(self) -> str:
        """List all known teams: code-defined plus DB components.

        Returns:
            str: JSON object with 'teams' (each {id, name, model_id, member_ids?, source}), 'count',
                and 'db_total' (DB components in storage; a capped list is visible as capped).
        """
        try:
            result: List[Dict[str, Any]] = []
            seen_ids: set[str] = set()
            idless_names: set[str] = set()  # code ids, plus the names of code components that have no id
            for team in self._iter_teams():
                tid = getattr(team, "id", None)
                name = getattr(team, "name", None)
                if tid is not None:
                    seen_ids.add(tid)
                elif name is not None:
                    idless_names.add(name)
                members = getattr(team, "members", None) or []
                member_ids = [getattr(m, "id", None) for m in members] if not callable(members) else []
                result.append(
                    {
                        "id": tid,
                        "name": name,
                        "model_id": getattr(getattr(team, "model", None), "id", None),
                        "member_ids": member_ids,
                        "source": "code",
                    }
                )
            db_rows, db_total = self._list_db_components("team")
            # A DB component duplicates a code one when they share an id, or -- for a
            # code component with no id -- when they share a name. A name collision with
            # a code component that HAS its own id is a genuinely distinct component and
            # must stay listed (it is what get_/run_/edit_ resolve to).
            for row in db_rows:
                if row["id"] in seen_ids or row["name"] in idless_names:
                    continue
                result.append({**row, "source": "db"})
            return json.dumps({"teams": result, "count": len(result), "db_total": db_total})
        except Exception as e:
            logger.exception("Failed to list teams")
            return json.dumps({"error": str(e) or type(e).__name__})

    def list_workflows(self) -> str:
        """List all known workflows: code-defined plus DB components.

        Returns:
            str: JSON object with 'workflows' (each {id, name, description, steps?, source}), 'count',
                and 'db_total' (DB components in storage; a capped list is visible as capped).
        """
        try:
            result: List[Dict[str, Any]] = []
            seen_ids: set[str] = set()
            idless_names: set[str] = set()  # code ids, plus the names of code components that have no id
            for wf in self._iter_workflows():
                wid = getattr(wf, "id", None)
                name = getattr(wf, "name", None)
                if wid is not None:
                    seen_ids.add(wid)
                elif name is not None:
                    idless_names.add(name)
                steps = getattr(wf, "steps", None) or []
                result.append(
                    {
                        "id": wid,
                        "name": name,
                        "description": getattr(wf, "description", None),
                        "steps": [getattr(s, "name", None) for s in steps] if isinstance(steps, list) else [],
                        "source": "code",
                    }
                )
            db_rows, db_total = self._list_db_components("workflow")
            # A DB component duplicates a code one when they share an id, or -- for a
            # code component with no id -- when they share a name. A name collision with
            # a code component that HAS its own id is a genuinely distinct component and
            # must stay listed (it is what get_/run_/edit_ resolve to).
            for row in db_rows:
                if row["id"] in seen_ids or row["name"] in idless_names:
                    continue
                result.append({**row, "source": "db"})
            return json.dumps({"workflows": result, "count": len(result), "db_total": db_total})
        except Exception as e:
            logger.exception("Failed to list workflows")
            return json.dumps({"error": str(e) or type(e).__name__})

    def _list_db_components(self, component_type: str) -> tuple[List[Dict[str, Any]], int]:
        """Thin summaries of DB components of a given type plus the total DB count.

        The total makes a capped list visible as capped: components beyond the
        cap still resolve by exact id."""
        return self._runner_tools._list_db_component_rows(component_type)

    # ------------------------------------------------------------------
    # Read one
    # ------------------------------------------------------------------

    def get_agent(self, agent_id: str) -> str:
        """Read an agent's current published config. Call this before edit_agent.

        Returns the published version; pending draft edits are not reflected here.

        Args:
            agent_id (str): The id or name of the agent.
        """
        try:
            agent = self._find_agent(agent_id)
        except StudioRunnerError as e:
            return json.dumps({"error": str(e) or type(e).__name__})
        except Exception as e:
            logger.exception("Failed to resolve agent")
            return json.dumps({"error": f"Failed to resolve agent '{agent_id}': {str(e) or type(e).__name__}"})
        if agent is None:
            return json.dumps({"error": f"Agent not found: {agent_id}"})
        return json.dumps(
            {
                "id": getattr(agent, "id", None),
                "name": getattr(agent, "name", None),
                "model_id": getattr(getattr(agent, "model", None), "id", None),
                "instructions": getattr(agent, "instructions", None),
                "description": getattr(agent, "description", None),
                "tools": self._normalize_tool_names(_summarize_tools(getattr(agent, "tools", None))),
                "add_history_to_context": getattr(agent, "add_history_to_context", None),
                "num_history_runs": getattr(agent, "num_history_runs", None),
                "add_datetime_to_context": getattr(agent, "add_datetime_to_context", None),
            },
            default=str,
        )

    def get_team(self, team_id: str) -> str:
        """Read a team's current published config. Call this before edit_team.

        Returns the published version; pending draft edits are not reflected here.

        Args:
            team_id (str): The id or name of the team.
        """
        try:
            team = self._find_team(team_id)
        except StudioRunnerError as e:
            return json.dumps({"error": str(e) or type(e).__name__})
        except Exception as e:
            logger.exception("Failed to resolve team")
            return json.dumps({"error": f"Failed to resolve team '{team_id}': {str(e) or type(e).__name__}"})
        if team is None:
            return json.dumps({"error": f"Team not found: {team_id}"})
        members = getattr(team, "members", None) or []
        return json.dumps(
            {
                "id": getattr(team, "id", None),
                "name": getattr(team, "name", None),
                "model_id": getattr(getattr(team, "model", None), "id", None),
                "instructions": getattr(team, "instructions", None),
                "description": getattr(team, "description", None),
                "member_ids": [getattr(m, "id", None) for m in members] if not callable(members) else [],
                "add_history_to_context": getattr(team, "add_history_to_context", None),
                "num_history_runs": getattr(team, "num_history_runs", None),
                "add_datetime_to_context": getattr(team, "add_datetime_to_context", None),
            },
            default=str,
        )

    def get_workflow(self, workflow_id: str) -> str:
        """Read a workflow's current published config. Call this before edit_workflow.

        Returns the published version; pending draft edits are not reflected here.

        Args:
            workflow_id (str): The id or name of the workflow.
        """
        try:
            wf = self._find_workflow(workflow_id)
        except StudioRunnerError as e:
            return json.dumps({"error": str(e) or type(e).__name__})
        except Exception as e:
            logger.exception("Failed to resolve workflow")
            return json.dumps({"error": f"Failed to resolve workflow '{workflow_id}': {str(e) or type(e).__name__}"})
        if wf is None:
            return json.dumps({"error": f"Workflow not found: {workflow_id}"})
        steps = getattr(wf, "steps", None) or []
        step_summaries: List[Dict[str, Any]] = []
        for step in steps if isinstance(steps, list) else []:
            executor = getattr(step, "executor", None)
            function_name = None
            if executor is not None:
                function_name = getattr(executor, "name", None) or getattr(executor, "__name__", None)
            step_summaries.append(
                {
                    "name": getattr(step, "name", None),
                    "agent_id": getattr(getattr(step, "agent", None), "id", None),
                    "team_id": getattr(getattr(step, "team", None), "id", None),
                    "function_name": function_name,
                }
            )
        return json.dumps(
            {
                "id": getattr(wf, "id", None),
                "name": getattr(wf, "name", None),
                "description": getattr(wf, "description", None),
                "steps": step_summaries,
            },
            default=str,
        )

    # ------------------------------------------------------------------
    # Create (published v1)
    # ------------------------------------------------------------------

    def create_agent(
        self,
        name: str,
        instructions: str,
        model_id: Optional[str] = None,
        tool_names: Optional[List[str]] = None,
        db_id: Optional[str] = None,
        description: Optional[str] = None,
        add_history_to_context: bool = True,
        num_history_runs: Optional[int] = None,
        add_datetime_to_context: bool = True,
    ) -> str:
        """Create a new agent and persist it as a published component.

        Args:
            name (str): Display name; also used as the id.
            instructions (str): System instructions for the agent.
            model_id (Optional[str]): Model id from the registry (see list_models).
            tool_names (Optional[List[str]]): Toolkit or function names from the registry
                (see list_tools). Include EVERY tool the user mentioned.
            db_id (Optional[str]): Database id from the registry. Uses the default if omitted.
            description (Optional[str]): Optional human-readable description.
            add_history_to_context (bool): Include prior turns of the session so the
                agent remembers the conversation. Defaults to True; pass False for a
                stateless agent.
            num_history_runs (Optional[int]): How many prior runs to include when
                history is on. Omit for the default.
            add_datetime_to_context (bool): Add the current date and time to the
                agent's context so it can date and time-reference reliably.
                Defaults to True; pass False to omit.

        Returns:
            str: JSON with {status, id, name, model_id, tools, add_history_to_context,
            add_datetime_to_context, db_version}.
        """
        from agno.agent.agent import Agent

        try:
            model = self._find_model(model_id)
            if model is None:
                return json.dumps({"error": f"Model not found: {model_id or 'default'}"})
            tools = self._resolve_tools(tool_names)
            db = self._find_db(db_id)
            if db is None:
                message = f"Db not found: {db_id}" if db_id is not None else "StudioTools has no db configured."
                return json.dumps({"error": message})

            agent_id = self._unique_component_id(name, db)
            agent = Agent(
                id=agent_id,
                name=name,
                model=model,
                tools=tools or None,
                instructions=instructions,
                db=db,
                description=description,
                add_history_to_context=add_history_to_context,
                num_history_runs=num_history_runs if num_history_runs is not None else self.default_num_history_runs,
                add_datetime_to_context=add_datetime_to_context,
            )

            version = _persist_only(agent, db)
            log_debug(f"StudioTools created agent id={agent_id} version={version}")
            return json.dumps(
                {
                    "status": "created",
                    "id": agent_id,
                    "name": name,
                    "model_id": getattr(model, "id", None),
                    "tools": _summarize_tools(tools),
                    "add_history_to_context": add_history_to_context,
                    "add_datetime_to_context": add_datetime_to_context,
                    "db_version": version,
                }
            )
        except Exception as e:
            logger.exception("Failed to create agent")
            return json.dumps({"error": str(e) or type(e).__name__})

    def create_team(
        self,
        name: str,
        instructions: str,
        member_ids: List[str],
        model_id: Optional[str] = None,
        db_id: Optional[str] = None,
        description: Optional[str] = None,
        add_history_to_context: bool = True,
        num_history_runs: Optional[int] = None,
        add_datetime_to_context: bool = True,
    ) -> str:
        """Create a new team and persist it as a published component.

        Args:
            name (str): Display name; also used as the id.
            instructions (str): Instructions that steer the team leader.
            member_ids (List[str]): Ids of existing agents or teams (see list_agents/list_teams).
            model_id (Optional[str]): Model id for the team leader.
            db_id (Optional[str]): Database id from the registry.
            description (Optional[str]): Optional description.
            add_history_to_context (bool): Include prior turns of the session so the
                team remembers the conversation. Defaults to True; pass False for a
                stateless team.
            num_history_runs (Optional[int]): How many prior runs to include when
                history is on. Omit for the default.
            add_datetime_to_context (bool): Add the current date and time to the
                team's context so it can date and time-reference reliably.
                Defaults to True; pass False to omit.

        Returns:
            str: JSON with {status, id, name, model_id, member_ids, add_history_to_context,
            add_datetime_to_context, db_version}.
        """
        from agno.team.team import Team

        try:
            model = self._find_model(model_id)
            if model is None:
                return json.dumps({"error": f"Model not found: {model_id or 'default'}"})

            try:
                members, missing = self._resolve_members(member_ids)
            except ValueError as e:
                # Ambiguity and id-less refusals are validation of model input,
                # not system failures: no traceback in the operator log.
                return json.dumps({"error": str(e)})
            if missing:
                return json.dumps({"error": f"Members not found: {missing}"})
            if not members:
                return json.dumps({"error": "A team must have at least one member"})

            db = self._find_db(db_id)
            if db is None:
                message = f"Db not found: {db_id}" if db_id is not None else "StudioTools has no db configured."
                return json.dumps({"error": message})
            team_id = self._unique_component_id(name, db)
            team = Team(
                id=team_id,
                name=name,
                model=model,
                members=members,
                instructions=instructions,
                db=db,
                description=description,
                add_history_to_context=add_history_to_context,
                num_history_runs=num_history_runs if num_history_runs is not None else self.default_num_history_runs,
                add_datetime_to_context=add_datetime_to_context,
            )

            version = _persist_only(team, db)
            log_debug(f"StudioTools created team id={team_id} members={member_ids} version={version}")
            return json.dumps(
                {
                    "status": "created",
                    "id": team_id,
                    "name": name,
                    "model_id": getattr(model, "id", None),
                    "member_ids": [getattr(m, "id", None) for m in members],
                    "add_history_to_context": add_history_to_context,
                    "add_datetime_to_context": add_datetime_to_context,
                    "db_version": version,
                }
            )
        except Exception as e:
            logger.exception("Failed to create team")
            return json.dumps({"error": str(e) or type(e).__name__})

    def create_workflow(
        self,
        name: str,
        description: str,
        step_specs: List[Dict[str, Any]],
        db_id: Optional[str] = None,
    ) -> str:
        """Create a new workflow and persist it as a published component.

        Args:
            name (str): Display name; also used as the id.
            description (str): What the workflow does.
            step_specs (List[dict]): Ordered steps. Each dict has 'name' and exactly
                one of 'agent_id', 'team_id', or 'function_name'. Optional: 'description'.
            db_id (Optional[str]): Database id from the registry.

        Returns:
            str: JSON with {status, id, name, description, steps, db_version}.
        """
        from agno.workflow.workflow import Workflow

        try:
            steps, err = self._build_steps(step_specs)
            if err is not None:
                return json.dumps({"error": err})

            db = self._find_db(db_id)
            if db is None:
                message = f"Db not found: {db_id}" if db_id is not None else "StudioTools has no db configured."
                return json.dumps({"error": message})
            workflow_id = self._unique_component_id(name, db)
            workflow = Workflow(
                id=workflow_id,
                name=name,
                description=description,
                steps=steps,
                db=db,
            )

            version = _persist_only(workflow, db)
            log_debug(f"StudioTools created workflow id={workflow_id} steps={len(steps)} version={version}")
            return json.dumps(
                {
                    "status": "created",
                    "id": workflow_id,
                    "name": name,
                    "description": description,
                    "steps": [s.name for s in steps],
                    "db_version": version,
                }
            )
        except Exception as e:
            logger.exception("Failed to create workflow")
            return json.dumps({"error": str(e) or type(e).__name__})

    # ------------------------------------------------------------------
    # Edit (produces a draft version)
    # ------------------------------------------------------------------

    def edit_agent(
        self,
        agent_id: str,
        instructions: Optional[str] = None,
        model_id: Optional[str] = None,
        tool_names: Optional[List[str]] = None,
        description: Optional[str] = None,
        add_history_to_context: Optional[bool] = None,
        num_history_runs: Optional[int] = None,
        add_datetime_to_context: Optional[bool] = None,
    ) -> str:
        """Edit an agent.

        Always call get_agent(agent_id) first to read the current state, then
        pass only the fields that should change. With versioning enabled the
        edit is saved as a draft (use publish_component to promote it);
        otherwise it is published immediately as the new current version.

        Args:
            agent_id (str): The id or display name of the agent to edit.
            instructions (Optional[str]): New instructions. Omit to keep.
            model_id (Optional[str]): New model id from the registry. Omit to keep.
            tool_names (Optional[List[str]]): New tool list (replaces existing). Omit to keep.
            description (Optional[str]): New description. Omit to keep.
            add_history_to_context (Optional[bool]): Whether the agent sees prior turns
                of the session. Omit to keep.
            num_history_runs (Optional[int]): New history depth. Omit to keep.
            add_datetime_to_context (Optional[bool]): Whether the agent sees the
                current date and time. Omit to keep.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTools has no db configured; cannot edit components."})
        try:
            # _is_code_defined does DB I/O; keep it inside the try so a db failure here
            # returns a structured error like every other resolve path, not an unhandled raise.
            if self._is_code_defined(agent_id, self._iter_agents(), "agent"):
                hint = ""
                try:
                    shadowed = self._runner_tools._resolve_db_id_by_name_or_slug("agent", agent_id)
                    if shadowed is not None:
                        hint = f" A Studio-created agent with this name exists: use its exact id '{shadowed}'."
                except AmbiguousComponentNameError:
                    pass
                return json.dumps(
                    {
                        "error": f"Cannot edit code-defined agent: {agent_id}. "
                        f"Only Studio-created components are editable.{hint}"
                    }
                )
            agent = self._find_agent_for_edit(agent_id)
        except StudioRunnerError as e:
            return json.dumps({"error": str(e) or type(e).__name__})
        except Exception as e:
            logger.exception("Failed to resolve agent")
            return json.dumps({"error": f"Failed to resolve agent '{agent_id}': {str(e) or type(e).__name__}"})
        if agent is None:
            return json.dumps({"error": f"Agent not found: {agent_id}"})

        try:
            agent = agent.deep_copy()
            if getattr(agent, "id", None) is None:
                agent.id = agent_id
            agent.db = self.db
            if instructions is not None:
                agent.instructions = instructions
            if description is not None:
                agent.description = description
            if model_id is not None:
                model = self._find_model(model_id)
                if model is None:
                    return json.dumps({"error": f"Model not found: {model_id}"})
                agent.model = model
            if tool_names is not None:
                agent.tools = self._resolve_tools(tool_names) or None
            if add_history_to_context is not None:
                agent.add_history_to_context = add_history_to_context
            if num_history_runs is not None:
                agent.num_history_runs = num_history_runs
                # Mirror Agent.__init__'s resolution: num_history_runs wins
                # over num_history_messages.
                agent.num_history_messages = None
            if add_datetime_to_context is not None:
                agent.add_datetime_to_context = add_datetime_to_context

            result = self._save_edit(agent)
            log_debug(f"StudioTools edited agent id={agent.id} result={result}")
            return json.dumps({"status": "edited", "id": getattr(agent, "id", None) or agent_id, **result})
        except Exception as e:
            logger.exception("Failed to edit agent")
            return json.dumps({"error": str(e) or type(e).__name__})

    def edit_team(
        self,
        team_id: str,
        instructions: Optional[str] = None,
        model_id: Optional[str] = None,
        member_ids: Optional[List[str]] = None,
        description: Optional[str] = None,
        add_history_to_context: Optional[bool] = None,
        num_history_runs: Optional[int] = None,
        add_datetime_to_context: Optional[bool] = None,
    ) -> str:
        """Edit a team.

        Always call get_team(team_id) first to read the current state, then
        pass only the fields that should change. With versioning enabled the
        edit is saved as a draft (use publish_component to promote it);
        otherwise it is published immediately as the new current version.

        Args:
            team_id (str): The id or display name of the team to edit.
            instructions (Optional[str]): New instructions. Omit to keep.
            model_id (Optional[str]): New model id. Omit to keep.
            member_ids (Optional[List[str]]): New member ids (replaces existing). Omit to keep.
            description (Optional[str]): New description. Omit to keep.
            add_history_to_context (Optional[bool]): Whether the team sees prior turns
                of the session. Omit to keep.
            num_history_runs (Optional[int]): New history depth. Omit to keep.
            add_datetime_to_context (Optional[bool]): Whether the team sees the
                current date and time. Omit to keep.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTools has no db configured; cannot edit components."})
        try:
            # _is_code_defined does DB I/O; keep it inside the try so a db failure here
            # returns a structured error like every other resolve path, not an unhandled raise.
            if self._is_code_defined(team_id, self._iter_teams(), "team"):
                hint = ""
                try:
                    shadowed = self._runner_tools._resolve_db_id_by_name_or_slug("team", team_id)
                    if shadowed is not None:
                        hint = f" A Studio-created team with this name exists: use its exact id '{shadowed}'."
                except AmbiguousComponentNameError:
                    pass
                return json.dumps(
                    {
                        "error": f"Cannot edit code-defined team: {team_id}. "
                        f"Only Studio-created components are editable.{hint}"
                    }
                )
            team = self._find_team_for_edit(team_id)
        except StudioRunnerError as e:
            return json.dumps({"error": str(e) or type(e).__name__})
        except Exception as e:
            logger.exception("Failed to resolve team")
            return json.dumps({"error": f"Failed to resolve team '{team_id}': {str(e) or type(e).__name__}"})
        if team is None:
            return json.dumps({"error": f"Team not found: {team_id}"})

        try:
            team = team.deep_copy()
            if getattr(team, "id", None) is None:
                team.id = team_id
            team.db = self.db
            if instructions is not None:
                team.instructions = instructions
            if description is not None:
                team.description = description
            if model_id is not None:
                model = self._find_model(model_id)
                if model is None:
                    return json.dumps({"error": f"Model not found: {model_id}"})
                team.model = model
            if member_ids is not None:
                try:
                    members, missing = self._resolve_members(member_ids)
                except ValueError as e:
                    return json.dumps({"error": str(e)})
                if missing:
                    return json.dumps({"error": f"Members not found: {missing}"})
                if not members:
                    return json.dumps({"error": "A team must have at least one member"})
                team.members = members
            else:
                # Team.from_dict resolves members through the registry and db only,
                # dropping (with a warning) any it cannot supply -- a code-defined
                # agents_list entry, for one. Re-serializing that rebuild would
                # publish a roster silently shrunk by an unrelated edit.
                resolved_id = getattr(team, "id", None) or team_id
                row = self.db.get_config(component_id=resolved_id, version=self._edit_base_version(resolved_id))
                stored_config = row.get("config") if isinstance(row, dict) else None
                stored_members = (stored_config or {}).get("members") or []
                rebuilt_members = team.members if isinstance(team.members, list) else []
                if len(rebuilt_members) < len(stored_members):
                    return json.dumps(
                        {
                            "error": f"Editing '{resolved_id}' would drop members its rebuild cannot resolve "
                            f"({len(rebuilt_members)} of {len(stored_members)} resolved). Register the "
                            "missing members in the registry or database, then retry."
                        }
                    )
            if add_history_to_context is not None:
                team.add_history_to_context = add_history_to_context
            if num_history_runs is not None:
                team.num_history_runs = num_history_runs
                # Mirror Team.__init__'s resolution: num_history_runs wins
                # over num_history_messages.
                team.num_history_messages = None
            if add_datetime_to_context is not None:
                team.add_datetime_to_context = add_datetime_to_context

            result = self._save_edit(team)
            log_debug(f"StudioTools edited team id={team.id} result={result}")
            return json.dumps({"status": "edited", "id": getattr(team, "id", None) or team_id, **result})
        except Exception as e:
            logger.exception("Failed to edit team")
            return json.dumps({"error": str(e) or type(e).__name__})

    def edit_workflow(
        self,
        workflow_id: str,
        description: Optional[str] = None,
        step_specs: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Edit a workflow.

        Always call get_workflow(workflow_id) first to read the current state,
        then pass only the fields that should change. With versioning enabled
        the edit is saved as a draft (use publish_component to promote it);
        otherwise it is published immediately as the new current version.

        Args:
            workflow_id (str): The id or display name of the workflow to edit.
            description (Optional[str]): New description. Omit to keep.
            step_specs (Optional[List[dict]]): New ordered steps (replaces existing). Omit to keep.
                Same shape as create_workflow.step_specs.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTools has no db configured; cannot edit components."})
        try:
            # _is_code_defined does DB I/O; keep it inside the try so a db failure here
            # returns a structured error like every other resolve path, not an unhandled raise.
            if self._is_code_defined(workflow_id, self._iter_workflows(), "workflow"):
                hint = ""
                try:
                    shadowed = self._runner_tools._resolve_db_id_by_name_or_slug("workflow", workflow_id)
                    if shadowed is not None:
                        hint = f" A Studio-created workflow with this name exists: use its exact id '{shadowed}'."
                except AmbiguousComponentNameError:
                    pass
                return json.dumps(
                    {
                        "error": f"Cannot edit code-defined workflow: {workflow_id}. "
                        f"Only Studio-created components are editable.{hint}"
                    }
                )
            wf = self._find_workflow_for_edit(workflow_id)
        except StudioRunnerError as e:
            return json.dumps({"error": str(e) or type(e).__name__})
        except Exception as e:
            logger.exception("Failed to resolve workflow")
            return json.dumps({"error": f"Failed to resolve workflow '{workflow_id}': {str(e) or type(e).__name__}"})
        if wf is None:
            return json.dumps({"error": f"Workflow not found: {workflow_id}"})

        try:
            wf = wf.deep_copy()
            if getattr(wf, "id", None) is None:
                wf.id = workflow_id
            wf.db = self.db
            if description is not None:
                wf.description = description
            if step_specs is not None:
                steps, err = self._build_steps(step_specs)
                if err is not None:
                    return json.dumps({"error": err})
                wf.steps = steps

            result = self._save_edit(wf)
            log_debug(f"StudioTools edited workflow id={wf.id} result={result}")
            return json.dumps({"status": "edited", "id": getattr(wf, "id", None) or workflow_id, **result})
        except Exception as e:
            logger.exception("Failed to edit workflow")
            return json.dumps({"error": str(e) or type(e).__name__})

    # ------------------------------------------------------------------
    # Versioning / configs
    # ------------------------------------------------------------------

    def list_versions(self, component_id: str) -> str:
        """List all config versions for a component.

        Args:
            component_id (str): The component id.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTools has no db configured."})
        try:
            component = self.db.get_component(component_id) or {}
            current_version = component.get("current_version")
            configs = self.db.list_configs(component_id, include_config=False)
            versions = [
                {
                    "version": c.get("version"),
                    "stage": c.get("stage"),
                    "label": c.get("label"),
                    "created_at": c.get("created_at"),
                    "is_current": current_version is not None and c.get("version") == current_version,
                }
                for c in configs
            ]
            return json.dumps({"component_id": component_id, "versions": versions, "count": len(versions)})
        except Exception as e:
            logger.exception("Failed to list versions")
            return json.dumps({"error": str(e) or type(e).__name__})

    def get_version(self, component_id: str, version: Optional[int] = None) -> str:
        """Get a specific config version. If version is omitted, returns the current version.

        Args:
            component_id (str): The component id.
            version (Optional[int]): Version number, or omit for the current version.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTools has no db configured."})
        try:
            config = self.db.get_config(component_id=component_id, version=version)
            if config is None:
                return json.dumps({"error": f"Version not found: component_id={component_id} version={version}"})
            return json.dumps(config, default=str)
        except Exception as e:
            logger.exception("Failed to get version")
            return json.dumps({"error": str(e) or type(e).__name__})

    def publish_component(self, component_id: str, version: Optional[int] = None) -> str:
        """Promote a draft to published (and make it the current version).

        Args:
            component_id (str): The component id.
            version (Optional[int]): The draft version to publish. If omitted, publishes the
                latest draft. Re-publishing an already-published version is a no-op and
                returns status "already_published".
        """
        if self.db is None:
            return json.dumps({"error": "StudioTools has no db configured."})
        try:
            configs = self.db.list_configs(component_id, include_config=False)
            target = version
            if target is None:
                drafts = [c for c in configs if c.get("stage") == "draft"]
                if not drafts:
                    return json.dumps({"error": "No draft version to publish."})
                target = max(d.get("version", 0) for d in drafts)
            else:
                # Explicit version: validate it exists and is not already published.
                match = next((c for c in configs if c.get("version") == target), None)
                if match is None:
                    return json.dumps({"error": f"Version not found: {component_id} v{target}"})
                if match.get("stage") == "published":
                    self._sync_component_row(component_id, target)
                    return json.dumps({"status": "already_published", "id": component_id, "version": target})

            result = self.db.upsert_config(component_id=component_id, version=target, stage="published")
            published_version = result.get("version", target)
            self._sync_component_row(component_id, published_version)
            return json.dumps(
                {
                    "status": "published",
                    "id": component_id,
                    "version": published_version,
                }
            )
        except Exception as e:
            logger.exception("Failed to publish component")
            return json.dumps({"error": str(e) or type(e).__name__})

    def set_current_version(self, component_id: str, version: int) -> str:
        """Roll back to a previously published version (make it current).

        Args:
            component_id (str): The component id.
            version (int): A published version to set as current.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTools has no db configured."})
        try:
            ok = self.db.set_current_version(component_id, version=version)
            if not ok:
                return json.dumps({"error": f"Component or version not found: {component_id} v{version}"})
            return json.dumps({"status": "set_current", "id": component_id, "version": version})
        except Exception as e:
            logger.exception("Failed to set current version")
            return json.dumps({"error": str(e) or type(e).__name__})

    def delete_version(self, component_id: str, version: int) -> str:
        """Delete a draft config version. Published and current versions cannot be deleted.

        Args:
            component_id (str): The component id.
            version (int): The draft version to delete.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTools has no db configured."})
        try:
            deleted = self.db.delete_config(component_id, version=version)
            if not deleted:
                return json.dumps({"error": f"Version not found: {component_id} v{version}"})
            return json.dumps({"status": "deleted", "id": component_id, "version": version})
        except Exception as e:
            logger.exception("Failed to delete version")
            return json.dumps({"error": str(e) or type(e).__name__})

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_agent(self, agent_id: str) -> str:
        """Hard-delete an agent DB component.

        Args:
            agent_id (str): The exact id of the agent to delete. Display names
                do not resolve for destructive operations.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTools has no db configured; cannot delete components."})
        try:
            from agno.db.base import ComponentType

            component = self.db.get_component(agent_id, component_type=ComponentType.AGENT)
            if component is None:
                resolved = self._runner_tools._resolve_db_id_by_name_or_slug("agent", agent_id)
                if resolved is not None:
                    return json.dumps(
                        {"error": f"Delete requires the exact id: '{agent_id}' resolves to '{resolved}'."}
                    )
                return json.dumps({"error": f"Agent not found: {agent_id}"})
            deleted = self.db.delete_component(agent_id, hard_delete=True)
            if not deleted:
                return json.dumps({"error": f"Agent not found: {agent_id}"})
            return json.dumps({"status": "deleted", "id": agent_id})
        except Exception as e:
            logger.exception("Failed to delete agent")
            return json.dumps({"error": str(e) or type(e).__name__})

    def delete_team(self, team_id: str) -> str:
        """Hard-delete a team component.

        Args:
            team_id (str): The exact id of the team to delete. Display names
                do not resolve for destructive operations.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTools has no db configured; cannot delete components."})
        try:
            from agno.db.base import ComponentType

            component = self.db.get_component(team_id, component_type=ComponentType.TEAM)
            if component is None:
                resolved = self._runner_tools._resolve_db_id_by_name_or_slug("team", team_id)
                if resolved is not None:
                    return json.dumps({"error": f"Delete requires the exact id: '{team_id}' resolves to '{resolved}'."})
                return json.dumps({"error": f"Team not found: {team_id}"})
            deleted = self.db.delete_component(team_id, hard_delete=True)
            if not deleted:
                return json.dumps({"error": f"Team not found: {team_id}"})
            return json.dumps({"status": "deleted", "id": team_id})
        except Exception as e:
            logger.exception("Failed to delete team")
            return json.dumps({"error": str(e) or type(e).__name__})

    def delete_workflow(self, workflow_id: str) -> str:
        """Hard-delete a workflow component.

        Args:
            workflow_id (str): The exact id of the workflow to delete. Display
                names do not resolve for destructive operations.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTools has no db configured; cannot delete components."})
        try:
            from agno.db.base import ComponentType

            component = self.db.get_component(workflow_id, component_type=ComponentType.WORKFLOW)
            if component is None:
                resolved = self._runner_tools._resolve_db_id_by_name_or_slug("workflow", workflow_id)
                if resolved is not None:
                    return json.dumps(
                        {"error": f"Delete requires the exact id: '{workflow_id}' resolves to '{resolved}'."}
                    )
                return json.dumps({"error": f"Workflow not found: {workflow_id}"})
            deleted = self.db.delete_component(workflow_id, hard_delete=True)
            if not deleted:
                return json.dumps({"error": f"Workflow not found: {workflow_id}"})
            return json.dumps({"status": "deleted", "id": workflow_id})
        except Exception as e:
            logger.exception("Failed to delete workflow")
            return json.dumps({"error": str(e) or type(e).__name__})

    # ------------------------------------------------------------------
    # Public run methods. StudioRunnerTools owns the run semantics
    # (current-user identity, per-conversation sub-sessions, PAUSED results
    # that carry their unresolved requirements); these forward to it and add
    # an 'id' key beside the runner's typed key. __init__ registers THESE
    # methods for the model, so the model-facing payload carries both keys
    # and a subclass override sits on the model's path. The paths are
    # separate methods: a policy gate must override run_agent AND arun_agent
    # (async_mode picks one), or it guards only half the surface. Only a
    # standalone StudioRunnerTools serves the typed key alone.
    # ------------------------------------------------------------------

    @staticmethod
    def _alias_runner_result(result: str) -> str:
        """The runner payload plus an 'id' key holding the resolved component id.

        Error payloads carry no id and pass through unchanged."""
        try:
            payload = json.loads(result)
        except Exception:
            return result
        if isinstance(payload, dict) and "error" not in payload:
            for key in ("agent_id", "team_id", "workflow_id"):
                if key in payload:
                    payload.setdefault("id", payload[key])
                    return json.dumps(payload, default=str)
        return result

    # These are what the model calls, not the embedded runner's bound methods, so a
    # subclass override sits on the path -- the sync and async halves separately,
    # as everywhere else in agno. They carry the `_agno_run_context` channel for
    # the same reason the runner does: the framework fills it, it is kept out of
    # the model-facing schema, and a model-supplied value for it is dropped.

    def run_agent(self, agent_id: str, message: str, _agno_run_context: Optional[RunContext] = None) -> str:
        """Run an agent by id or display name. Forwards to StudioRunnerTools.

        Args:
            agent_id (str): Id of the agent to run (a display name or its slug also resolves).
            message (str): The message to send.

        Returns:
            str: JSON object with 'agent_id', 'id', 'run_id', 'session_id', 'status',
                'content' and, when paused, 'requirements'.
        """
        return self._alias_runner_result(self._runner_tools.run_agent(agent_id, message, _agno_run_context))

    def run_team(self, team_id: str, message: str, _agno_run_context: Optional[RunContext] = None) -> str:
        """Run a team by id or display name. Forwards to StudioRunnerTools.

        Args:
            team_id (str): Id of the team to run (a display name or its slug also resolves).
            message (str): The message to send.

        Returns:
            str: JSON object with 'team_id', 'id', 'run_id', 'session_id', 'status',
                'content' and, when paused, 'requirements'.
        """
        return self._alias_runner_result(self._runner_tools.run_team(team_id, message, _agno_run_context))

    def run_workflow(self, workflow_id: str, message: str, _agno_run_context: Optional[RunContext] = None) -> str:
        """Run a workflow by id or display name. Forwards to StudioRunnerTools.

        Args:
            workflow_id (str): Id of the workflow to run (a display name or its slug also resolves).
            message (str): Input to pass to the first step.

        Returns:
            str: JSON object with 'workflow_id', 'id', 'run_id', 'session_id', 'status',
                'content' and, when paused, 'requirements'.
        """
        return self._alias_runner_result(self._runner_tools.run_workflow(workflow_id, message, _agno_run_context))

    async def arun_agent(self, agent_id: str, message: str, _agno_run_context: Optional[RunContext] = None) -> str:
        """Async variant of run_agent.

        Args:
            agent_id (str): Id of the agent to run (a display name or its slug also resolves).
            message (str): The message to send.
        """
        return self._alias_runner_result(await self._runner_tools.arun_agent(agent_id, message, _agno_run_context))

    async def arun_team(self, team_id: str, message: str, _agno_run_context: Optional[RunContext] = None) -> str:
        """Async variant of run_team.

        Args:
            team_id (str): Id of the team to run (a display name or its slug also resolves).
            message (str): The message to send.
        """
        return self._alias_runner_result(await self._runner_tools.arun_team(team_id, message, _agno_run_context))

    async def arun_workflow(
        self, workflow_id: str, message: str, _agno_run_context: Optional[RunContext] = None
    ) -> str:
        """Async variant of run_workflow.

        Args:
            workflow_id (str): Id of the workflow to run (a display name or its slug also resolves).
            message (str): Input to pass to the first step.
        """
        return self._alias_runner_result(
            await self._runner_tools.arun_workflow(workflow_id, message, _agno_run_context)
        )

    # ------------------------------------------------------------------
    # Schedules (component-aware)
    # ------------------------------------------------------------------

    def create_schedule(
        self,
        name: str,
        cron: str,
        target_type: str,
        target_id: str,
        message: str,
        timezone: str = "UTC",
        description: Optional[str] = None,
    ) -> str:
        """Create (or update) a schedule that runs an existing component on a cron cadence.

        Args:
            name (str): Unique schedule name (e.g. "daily-news-digest"). Re-using an
                existing name updates that schedule in place.
            cron (str): 5-field cron expression (e.g. "0 9 * * *" for daily at 9am).
            target_type (str): One of 'agent', 'team', or 'workflow'.
            target_id (str): Id (or name) of an existing component -- use ids from
                list_agents/list_teams/list_workflows.
            message (str): The message sent to the component on every scheduled run.
            timezone (str): IANA timezone name for the cron expression
                (e.g. "America/New_York"). Defaults to "UTC".
            description (Optional[str]): Human-readable description of the schedule.

        Returns:
            str: JSON with {status, id, name, cron, target_type, target_id, endpoint,
                timezone, enabled, next_run_at}.
        """
        try:
            component_id, target_error = self._resolve_schedule_target(target_type, target_id)
            if target_error is not None:
                return json.dumps({"error": target_error})
            if not message or not message.strip():
                return json.dumps(
                    {
                        "error": "message must be a non-empty string; it is the prompt "
                        "sent to the component on every scheduled run."
                    }
                )
            manager = self._get_schedule_manager()
            schedule = manager.create(
                name=name,
                cron=cron,
                endpoint=f"/{target_type}s/{component_id}/runs",
                method="POST",
                description=description,
                payload={"message": message},
                timezone=timezone,
                if_exists="update",
            )
            log_debug(f"StudioTools created schedule name={name} target={target_type}:{component_id}")
            return json.dumps(
                {
                    "status": "created",
                    "id": schedule.id,
                    "name": schedule.name,
                    "cron": schedule.cron_expr,
                    "target_type": target_type,
                    "target_id": component_id,
                    "endpoint": schedule.endpoint,
                    "timezone": schedule.timezone,
                    "enabled": schedule.enabled,
                    "next_run_at": schedule.next_run_at,
                }
            )
        except Exception as e:
            logger.exception("Failed to create schedule")
            return json.dumps({"error": str(e) or type(e).__name__})

    # ------------------------------------------------------------------
    # Async tools
    # ------------------------------------------------------------------

    async def alist_models(self) -> str:
        """Async variant of list_models."""
        return await self._run_sync_tool(self.list_models)

    async def alist_tools(self) -> str:
        """Async variant of list_tools."""
        return await self._run_sync_tool(self.list_tools)

    async def alist_functions(self) -> str:
        """Async variant of list_functions."""
        return await self._run_sync_tool(self.list_functions)

    async def alist_dbs(self) -> str:
        """Async variant of list_dbs."""
        return await self._run_sync_tool(self.list_dbs)

    async def alist_agents(self) -> str:
        """Async variant of list_agents."""
        return await self._run_sync_tool(self.list_agents)

    async def alist_teams(self) -> str:
        """Async variant of list_teams."""
        return await self._run_sync_tool(self.list_teams)

    async def alist_workflows(self) -> str:
        """Async variant of list_workflows."""
        return await self._run_sync_tool(self.list_workflows)

    async def aget_agent(self, agent_id: str) -> str:
        """Async variant of get_agent."""
        return await self._run_sync_tool(self.get_agent, agent_id)

    async def aget_team(self, team_id: str) -> str:
        """Async variant of get_team."""
        return await self._run_sync_tool(self.get_team, team_id)

    async def aget_workflow(self, workflow_id: str) -> str:
        """Async variant of get_workflow."""
        return await self._run_sync_tool(self.get_workflow, workflow_id)

    async def acreate_agent(
        self,
        name: str,
        instructions: str,
        model_id: Optional[str] = None,
        tool_names: Optional[List[str]] = None,
        db_id: Optional[str] = None,
        description: Optional[str] = None,
        add_history_to_context: bool = True,
        num_history_runs: Optional[int] = None,
        add_datetime_to_context: bool = True,
    ) -> str:
        """Async variant of create_agent."""
        return await self._run_sync_tool(
            self.create_agent,
            name,
            instructions,
            model_id=model_id,
            tool_names=tool_names,
            db_id=db_id,
            description=description,
            add_history_to_context=add_history_to_context,
            num_history_runs=num_history_runs,
            add_datetime_to_context=add_datetime_to_context,
        )

    async def acreate_team(
        self,
        name: str,
        instructions: str,
        member_ids: List[str],
        model_id: Optional[str] = None,
        db_id: Optional[str] = None,
        description: Optional[str] = None,
        add_history_to_context: bool = True,
        num_history_runs: Optional[int] = None,
        add_datetime_to_context: bool = True,
    ) -> str:
        """Async variant of create_team."""
        return await self._run_sync_tool(
            self.create_team,
            name,
            instructions,
            member_ids,
            model_id=model_id,
            db_id=db_id,
            description=description,
            add_history_to_context=add_history_to_context,
            num_history_runs=num_history_runs,
            add_datetime_to_context=add_datetime_to_context,
        )

    async def acreate_workflow(
        self,
        name: str,
        description: str,
        step_specs: List[Dict[str, Any]],
        db_id: Optional[str] = None,
    ) -> str:
        """Async variant of create_workflow."""
        return await self._run_sync_tool(
            self.create_workflow,
            name,
            description,
            step_specs,
            db_id=db_id,
        )

    async def aedit_agent(
        self,
        agent_id: str,
        instructions: Optional[str] = None,
        model_id: Optional[str] = None,
        tool_names: Optional[List[str]] = None,
        description: Optional[str] = None,
        add_history_to_context: Optional[bool] = None,
        num_history_runs: Optional[int] = None,
        add_datetime_to_context: Optional[bool] = None,
    ) -> str:
        """Async variant of edit_agent."""
        return await self._run_sync_tool(
            self.edit_agent,
            agent_id,
            instructions=instructions,
            model_id=model_id,
            tool_names=tool_names,
            description=description,
            add_history_to_context=add_history_to_context,
            num_history_runs=num_history_runs,
            add_datetime_to_context=add_datetime_to_context,
        )

    async def aedit_team(
        self,
        team_id: str,
        instructions: Optional[str] = None,
        model_id: Optional[str] = None,
        member_ids: Optional[List[str]] = None,
        description: Optional[str] = None,
        add_history_to_context: Optional[bool] = None,
        num_history_runs: Optional[int] = None,
        add_datetime_to_context: Optional[bool] = None,
    ) -> str:
        """Async variant of edit_team."""
        return await self._run_sync_tool(
            self.edit_team,
            team_id,
            instructions=instructions,
            model_id=model_id,
            member_ids=member_ids,
            description=description,
            add_history_to_context=add_history_to_context,
            num_history_runs=num_history_runs,
            add_datetime_to_context=add_datetime_to_context,
        )

    async def aedit_workflow(
        self,
        workflow_id: str,
        description: Optional[str] = None,
        step_specs: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Async variant of edit_workflow."""
        return await self._run_sync_tool(
            self.edit_workflow,
            workflow_id,
            description=description,
            step_specs=step_specs,
        )

    async def alist_versions(self, component_id: str) -> str:
        """Async variant of list_versions."""
        return await self._run_sync_tool(self.list_versions, component_id)

    async def aget_version(self, component_id: str, version: Optional[int] = None) -> str:
        """Async variant of get_version."""
        return await self._run_sync_tool(self.get_version, component_id, version=version)

    async def apublish_component(self, component_id: str, version: Optional[int] = None) -> str:
        """Async variant of publish_component."""
        return await self._run_sync_tool(self.publish_component, component_id, version=version)

    async def aset_current_version(self, component_id: str, version: int) -> str:
        """Async variant of set_current_version."""
        return await self._run_sync_tool(self.set_current_version, component_id, version)

    async def adelete_version(self, component_id: str, version: int) -> str:
        """Async variant of delete_version."""
        return await self._run_sync_tool(self.delete_version, component_id, version)

    async def adelete_agent(self, agent_id: str) -> str:
        """Async variant of delete_agent."""
        return await self._run_sync_tool(self.delete_agent, agent_id)

    async def adelete_team(self, team_id: str) -> str:
        """Async variant of delete_team."""
        return await self._run_sync_tool(self.delete_team, team_id)

    async def adelete_workflow(self, workflow_id: str) -> str:
        """Async variant of delete_workflow."""
        return await self._run_sync_tool(self.delete_workflow, workflow_id)

    async def acreate_schedule(
        self,
        name: str,
        cron: str,
        target_type: str,
        target_id: str,
        message: str,
        timezone: str = "UTC",
        description: Optional[str] = None,
    ) -> str:
        """Async variant of create_schedule."""
        return await self._run_sync_tool(
            self.create_schedule,
            name,
            cron,
            target_type,
            target_id,
            message,
            timezone=timezone,
            description=description,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_sync_tool(self, function: Callable[..., str], *args: Any, **kwargs: Any) -> str:
        import asyncio

        return await asyncio.to_thread(function, *args, **kwargs)

    def _unique_component_id(self, name: str, db: "BaseDb") -> str:
        """Return a unique id in the DB component namespace.

        Components use ``component_id`` as the primary key, so agents, teams,
        and workflows intentionally share one id namespace.
        """
        base = _slugify(name)
        candidate = base
        suffix = 2
        while self._component_id_exists(candidate, db):
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def _get_schedule_manager(self) -> "ScheduleManager":
        """The shared SchedulerTools instance's manager."""
        if self.db is None:
            raise ValueError("StudioTools has no db configured; cannot manage schedules.")
        if self._scheduler_tools is None:
            raise ValueError("StudioTools was built with schedules=False; cannot manage schedules.")
        return self._scheduler_tools.manager

    def _resolve_schedule_target(self, target_type: str, target_id: str) -> tuple[Optional[str], Optional[str]]:
        """Resolve a schedule target to a real component id.

        Returns ``(component_id, error)``: exactly one side is set. Targets
        resolve through the Studio lookup path (code-defined lists, then DB;
        matched by id or name), so schedules always point at a component's
        real id even when the caller passed its display name.
        """
        if target_type not in _SCHEDULE_TARGET_TYPES:
            return None, f"Invalid target_type: {target_type}. Must be one of {list(_SCHEDULE_TARGET_TYPES)}."
        finders: Dict[str, Callable[[str], Optional[Any]]] = {
            "agent": self._find_agent,
            "team": self._find_team,
            "workflow": self._find_workflow,
        }
        component = finders[target_type](target_id)
        if component is None:
            return None, f"{target_type.capitalize()} not found: {target_id}"
        component_id = getattr(component, "id", None)
        if component_id is None:
            return None, f"{target_type.capitalize()} has no id: {target_id}"
        return component_id, None

    def _component_id_exists(self, component_id: str, db: "BaseDb") -> bool:
        for component in [*self._iter_agents(), *self._iter_teams(), *self._iter_workflows()]:
            component_name = getattr(component, "name", None)
            if (
                getattr(component, "id", None) == component_id
                or component_name == component_id
                or (component_name is not None and _slugify(component_name) == component_id)
            ):
                return True
        return db.get_component(component_id) is not None

    def _resolve_members(self, member_ids: List[str]) -> tuple[List[TeamMember], List[str]]:
        """Resolve member identifiers to agents or teams.

        Exact ids resolve across BOTH types before any name matching, so an
        agent merely named like a team's id can never steal that member slot.
        An identifier naming a stored component that fails to load counts as
        missing rather than falling through to name matching.
        """
        runner = self._runner_tools
        members: List[TeamMember] = []
        missing: List[str] = []
        for mid in member_ids:
            agent_match = runner._find_agent_by_exact_id(mid)
            team_match = runner._find_team_by_exact_id(mid)
            if agent_match is not None and team_match is not None:
                # Ids are only unique per type, so an agent and a team may
                # legally share one; member_ids cannot disambiguate.
                raise ValueError(
                    f"Ambiguous member id: '{mid}' matches both an agent and a team. "
                    "Give the components distinct ids to reference them as members."
                )
            member: Optional[TeamMember] = agent_match or team_match
            if member is None and not (
                runner._db_component_exists("agent", mid) or runner._db_component_exists("team", mid)
            ):
                agent_named = runner._find_agent_by_name(mid)
                team_named = runner._find_team_by_name(mid)
                if agent_named is not None and team_named is not None:
                    raise ValueError(
                        f"Ambiguous member name: '{mid}' matches both an agent and a team. Use an exact id."
                    )
                member = agent_named or team_named
            if member is None:
                missing.append(mid)
            else:
                if not getattr(member, "id", None):
                    # Persisting the reference would store a null id; on reload the
                    # registry lookup by id=None binds whichever id-less component
                    # it sees first -- silently the wrong one. Falsy, not None:
                    # the load-side guard refuses an empty-string id the same way.
                    raise ValueError(
                        f"Member '{mid}' is code-defined with no id, so a stored reference "
                        "cannot name it. Set an explicit id on the component."
                    )
                members.append(member)
        return members, missing

    def _build_steps(self, step_specs: List[Dict[str, Any]]) -> tuple[List[Any], Optional[str]]:
        from agno.workflow.step import Step

        if not step_specs:
            return [], "step_specs must contain at least one step"

        steps: List[Step] = []
        for i, spec in enumerate(step_specs):
            step_name = spec.get("name") or f"step_{i + 1}"
            step_desc = spec.get("description")
            if "agent_id" in spec:
                agent = self._find_agent(spec["agent_id"])
                if agent is None:
                    return [], f"Agent not found for step '{step_name}': {spec['agent_id']}"
                if not getattr(agent, "id", None):
                    # A null (or empty) id in the stored step config makes the
                    # workflow unreconstructable: created and listed, never loadable.
                    return [], (
                        f"Agent for step '{step_name}' ('{spec['agent_id']}') is code-defined with no id, "
                        "so a stored step cannot name it. Set an explicit id on the agent."
                    )
                steps.append(Step(name=step_name, agent=agent, description=step_desc))
            elif "team_id" in spec:
                team = self._find_team(spec["team_id"])
                if team is None:
                    return [], f"Team not found for step '{step_name}': {spec['team_id']}"
                if not getattr(team, "id", None):
                    return [], (
                        f"Team for step '{step_name}' ('{spec['team_id']}') is code-defined with no id, "
                        "so a stored step cannot name it. Set an explicit id on the team."
                    )
                steps.append(Step(name=step_name, team=team, description=step_desc))
            elif "function_name" in spec:
                func = self.registry.get_function(spec["function_name"])
                if func is None:
                    return [], f"Function not found for step '{step_name}': {spec['function_name']}"
                steps.append(Step(name=step_name, executor=func, description=step_desc))
            else:
                return [], f"Step '{step_name}' must specify agent_id, team_id, or function_name"
        return steps, None

    def _save_edit(self, component: Component) -> Dict[str, Any]:
        """Persist an edited component.

        With versioning enabled the edit is saved as a draft awaiting
        publish_component; otherwise it is published immediately as the new
        current version.
        """
        carry = self._unreconstructed_declarations(getattr(component, "id", None))
        if self.enable_versions:
            version = self._upsert_draft(component, carry)
            return {"draft_version": version, "stage": "draft"}
        version = _persist_only(component, self.db, carry=carry)
        return {"version": version, "stage": "published"}

    def _unreconstructed_declarations(self, component_id: Optional[str]) -> Dict[str, Any]:
        """What the stored config declares that a rebuild cannot carry back.

        An edit works on a rebuilt component, so anything from_dict does not
        restore is already absent by the time the edit runs. Resaving would
        delete it -- and silently lift the dispatch refusal it causes -- for an
        edit that never mentioned it."""
        if component_id is None or self.db is None:
            return {}
        # Deliberately unguarded. A read that fails is not evidence that there
        # was nothing to carry, and treating it as such publishes an edit that
        # deletes a declaration -- and lifts the dispatch refusal it causes.
        # The caller's handler turns this into a structured error.
        stored = self._runner_tools._load_config_from_db(component_id, version=self._edit_base_version(component_id))
        if stored is None:
            raise ValueError(
                f"Cannot edit '{component_id}': its stored config could not be read, so an edit would drop "
                "whatever the rebuild does not carry back."
            )
        return {key: stored[key] for key in _UNRECONSTRUCTED_KEYS if stored.get(key) is not None}

    def _upsert_draft(self, component: Component, carry: Optional[Dict[str, Any]] = None) -> Optional[int]:
        """Save a component as a draft. Updates the latest draft in place, else creates one.

        The component row's name/description/metadata are NOT updated here --
        draft-only changes must not leak into listings until the draft is
        published (publish_component syncs the row).
        """
        if self.db is None:
            raise ValueError("db is required for draft persistence")

        component_id = getattr(component, "id", None)
        if component_id is None:
            raise ValueError("Component has no id")

        if self.db.get_component(component_id) is None:
            self.db.upsert_component(
                component_id=component_id,
                component_type=_component_type(component),
                name=getattr(component, "name", component_id),
                description=getattr(component, "description", None),
                metadata=getattr(component, "metadata", None),
            )

        # Reuse an existing draft if there is one; otherwise create a new draft version.
        result = self.db.upsert_config(
            component_id=component_id,
            version=self._latest_draft_version(component_id),
            config=_component_to_dict(component, carry),
            stage="draft",
        )
        return result.get("version")

    def _sync_component_row(self, component_id: str, version: Optional[int]) -> None:
        """Bring the component row's name/description/metadata in line with a
        newly published config version."""
        if self.db is None:
            return
        from agno.db.base import ComponentType

        component = self.db.get_component(component_id)
        row = self.db.get_config(component_id=component_id, version=version)
        config = row.get("config") if isinstance(row, dict) else None
        if component is None or not isinstance(config, dict):
            return
        self.db.upsert_component(
            component_id=component_id,
            component_type=ComponentType(component["component_type"]),
            name=config.get("name") or component.get("name"),
            description=config.get("description"),
            metadata=config.get("metadata"),
        )


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def _summarize_tools(tools: Any) -> List[str]:
    if not tools or callable(tools):
        return []
    names: List[str] = []
    for t in tools:
        if isinstance(t, Toolkit):
            names.append(t.name)
        elif isinstance(t, Function):
            names.append(t.name)
        elif callable(t):
            names.append(getattr(t, "__name__", repr(t)))
    return names


def _persist_only(
    component: Component,
    db: Optional["BaseDb"],
    stage: str = "published",
    carry: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """Save a component WITHOUT cascading to members or step agents.

    Agno's built-in ``component.save()`` recursively persists every member of
    a team and every agent/team referenced by a workflow step. That pulls
    code-defined agents (ones you passed via ``agents_list`` or the registry)
    into the DB as components, which is not what studio should do.

    This helper saves only the top-level component row and its config. Member
    / step references travel in the config dict by id; rehydration resolves
    them via ``get_agent_by_id`` / ``get_team_by_id``, which check the DB.
    Code-defined members won't be found on a cold reload -- that's the
    trade-off for keeping them out of DB.
    """
    if db is None:
        raise ValueError("db is required for persistence")
    component_id = getattr(component, "id", None)
    if component_id is None:
        raise ValueError("Component has no id")
    db.upsert_component(
        component_id=component_id,
        component_type=_component_type(component),
        name=getattr(component, "name", component_id),
        description=getattr(component, "description", None),
        metadata=getattr(component, "metadata", None),
    )
    result = db.upsert_config(
        component_id=component_id,
        config=_component_to_dict(component, carry),
        stage=stage,
    )
    return result.get("version")


def _resolve_flags(
    agents: Optional[bool],
    teams: Optional[bool],
    workflows: Optional[bool],
    has_agents_list: bool,
    has_teams_list: bool,
) -> tuple[bool, bool, bool]:
    """Resolve the enable flags for the three capability groups.

    * Agents are enabled by default unless ``agents=False`` is explicit.
    * Teams and workflows are disabled by default unless explicitly enabled
      or auto-enabled by live component lists.
    * Passing ``agents=False`` without enabling another component type leaves
      only discovery tools registered.
    * Passing ``agents_list`` auto-enables teams and workflows (you can build
      them from those agents). Passing ``teams_list`` auto-enables workflows.
      Explicit flags take precedence over these auto-enables.
    """
    a = bool(agents) if agents is not None else True
    t = bool(teams) if teams is not None else False
    w = bool(workflows) if workflows is not None else False

    if has_agents_list and teams is None:
        t = True
    if has_agents_list and workflows is None:
        w = True
    if has_teams_list and workflows is None:
        w = True

    return a, t, w


def _component_type(component: Component) -> Any:
    from agno.agent.agent import Agent
    from agno.db.base import ComponentType
    from agno.team.team import Team
    from agno.workflow.workflow import Workflow

    if isinstance(component, Agent):
        return ComponentType.AGENT
    if isinstance(component, Team):
        return ComponentType.TEAM
    if isinstance(component, Workflow):
        return ComponentType.WORKFLOW
    raise TypeError(f"Unsupported component type: {type(component).__name__}")


# Serialized by to_dict and never read back by from_dict (#9452), so a rebuild
# drops them. An edit that resaves a rebuild would therefore delete a
# declaration it never touched -- and quietly lift the dispatch refusal that
# declaration causes -- so edits carry them forward verbatim.
_UNRECONSTRUCTED_KEYS = ("reasoning_model", "parser_model", "output_model")


def _component_to_dict(component: Component, carry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from agno.agent.agent import Agent
    from agno.team.team import Team
    from agno.workflow.workflow import Workflow

    if isinstance(component, Agent):
        from agno.agent._storage import to_dict as agent_to_dict

        config = agent_to_dict(component)
    elif isinstance(component, Team):
        from agno.team._storage import to_dict as team_to_dict

        config = team_to_dict(component)
    elif isinstance(component, Workflow):
        config = component.to_dict()
    else:
        raise TypeError(f"Unsupported component type: {type(component).__name__}")
    for key, value in (carry or {}).items():
        # Only what the rebuild lost: a value the component still carries is
        # the edited one and wins.
        config.setdefault(key, value)
    return config


# Backward-compatible alias. The toolkit was originally released as ``StudioTool``
# (singular); ``StudioTools`` is the canonical name. Both refer to the same class.
StudioTool = StudioTools
