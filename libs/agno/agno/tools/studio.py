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
      - with versions=True the edit is saved as a new immutable draft. Use
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
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Union

from agno.run import RunContext
from agno.tools.function import Function
from agno.tools.studio_runner import AmbiguousComponentNameError, StudioRunnerError, StudioRunnerTools
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, logger
from agno.utils.string import generate_component_id_from_name

if TYPE_CHECKING:
    from agno.agent.agent import Agent
    from agno.db.base import BaseDb, ComponentProjection, ComponentVersionGuard
    from agno.models.base import Model
    from agno.registry.registry import Registry
    from agno.scheduler.manager import ScheduleManager
    from agno.team.team import Team
    from agno.tools.scheduler import SchedulerTools
    from agno.workflow.workflow import Workflow

Component = Union["Agent", "Team", "Workflow"]
TeamMember = Union["Agent", "Team"]

_SCHEDULE_TARGET_TYPES = ("agent", "team", "workflow")
_STUDIO_CONFIG_KEY = "_agno_studio"
_STUDIO_CONFIG_MANIFEST = {"schema_version": 2, "request": {}}


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
        # Rehydration resolves code-defined references through the registry
        # only; a component reachable solely via these live lists could be
        # referenced at create time but never reload. Make the lists visible.
        pending_mirrors: List[tuple] = []
        for source, bucket, source_name in (
            (agents_list, registry.agents, "agents_list"),
            (teams_list, registry.teams, "teams_list"),
        ):
            for component in source or []:
                component_id = getattr(component, "id", None)
                if not component_id:
                    continue
                existing = next((entry for entry in bucket if getattr(entry, "id", None) == component_id), None)
                if existing is None:
                    pending_mirrors.append((bucket, component))
                elif existing is not component:
                    # Studio lookup prefers the explicit list; rehydration
                    # resolves through the registry. Two distinct objects under
                    # one id would build with one and reload as the other.
                    raise ValueError(
                        f"{source_name} and the registry define distinct components with id "
                        f"'{component_id}'; pass the same object to both, or remove one."
                    )
        for bucket, component in pending_mirrors:
            bucket.append(component)
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

        if self.enable_agents or self.enable_teams or self.enable_workflows:
            tools.append(self.restore_component)

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
        if self.enable_agents or self.enable_teams or self.enable_workflows:
            async_tools.append((self.arestore_component, "restore_component"))
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

    def _edit_version_snapshot(self, component_id: str) -> tuple[Optional[int], Optional["ComponentVersionGuard"]]:
        """Capture the exact config loaded by an edit and its catalog-v2 CAS state."""
        if self.db is None:
            return None, None
        if getattr(self.db, "component_catalog_api_version", 1) < 2:
            base_version = self._edit_base_version(component_id)
            return base_version, None

        from agno.db.base import ComponentVersionGuard

        component = self.db.get_component(component_id)
        if component is None:
            return None, None
        configs = self.db.list_configs(component_id, include_config=False)
        versions = [row["version"] for row in configs if isinstance(row.get("version"), int)]
        drafts = [
            row["version"] for row in configs if row.get("stage") == "draft" and isinstance(row.get("version"), int)
        ]
        current_version = component.get("current_version")
        base_version = max(drafts) if self.enable_versions and drafts else current_version
        if base_version is None:
            base_version = max(versions) if versions else None
        return base_version, ComponentVersionGuard(
            latest_version=max(versions) if versions else None,
            current_version=current_version,
        )

    def _require_studio_owned(
        self,
        component_id: str,
        *,
        version: Optional[int] = None,
        include_deleted: bool = False,
    ) -> Dict[str, Any]:
        """Return a config only when it was written by this typed control plane."""
        if self.db is None:
            raise ValueError("StudioTools has no db configured")
        if getattr(self.db, "component_catalog_api_version", 1) >= 2:
            row = self.db.get_config(
                component_id=component_id,
                version=version,
                include_deleted=include_deleted,
            )
        else:
            if include_deleted:
                raise ValueError("Explicit restore requires component catalog API v2")
            row = self.db.get_config(component_id=component_id, version=version)
        candidates = [row]
        if getattr(self.db, "component_catalog_api_version", 1) >= 2:
            candidates.extend(
                self.db.list_configs(
                    component_id,
                    include_config=True,
                    include_deleted=include_deleted,
                )
            )
        else:
            candidates.extend(self.db.list_configs(component_id, include_config=True))
        owned = any(
            isinstance(candidate, dict)
            and isinstance(candidate.get("config"), dict)
            and _STUDIO_CONFIG_KEY in candidate["config"]
            for candidate in candidates
        )
        if not isinstance(row, dict) or not isinstance(row.get("config"), dict) or not owned:
            raise ValueError(
                f"Cannot mutate component '{component_id}': only Studio-created components are editable by StudioTools"
            )
        return row

    def _component_guard(
        self,
        component_id: str,
        *,
        include_deleted: bool = False,
    ) -> tuple[Dict[str, Any], "ComponentVersionGuard"]:
        """Capture component state for one guarded Studio mutation."""
        if self.db is None:
            raise ValueError("StudioTools has no db configured")
        from agno.db.base import ComponentVersionGuard

        component = self.db.get_component(component_id, include_deleted=include_deleted)
        if component is None:
            raise ValueError(f"Component not found: {component_id}")
        latest = self.db.get_latest_config(component_id, include_deleted=include_deleted)
        latest_version = latest.get("version") if isinstance(latest, dict) else None
        return component, ComponentVersionGuard(
            latest_version=latest_version if isinstance(latest_version, int) else None,
            current_version=component.get("current_version"),
        )

    def _find_agent_for_edit(
        self, agent_id: str
    ) -> tuple[Optional["Agent"], Optional[int], Optional["ComponentVersionGuard"]]:
        for a in self._iter_agents():
            if getattr(a, "id", None) == agent_id:
                return a, None, None
        if self._runner_tools._db_component_exists("agent", agent_id):
            base_version, guard = self._edit_version_snapshot(agent_id)
            return self._load_agent_from_db(agent_id, version=base_version), base_version, guard
        resolved = self._runner_tools._resolve_db_id_by_name_or_slug("agent", agent_id)
        if resolved is None:
            return None, None, None
        base_version, guard = self._edit_version_snapshot(resolved)
        return self._load_agent_from_db(resolved, version=base_version), base_version, guard

    def _find_team_for_edit(
        self, team_id: str
    ) -> tuple[Optional["Team"], Optional[int], Optional["ComponentVersionGuard"]]:
        for t in self._iter_teams():
            if getattr(t, "id", None) == team_id:
                return t, None, None
        if self._runner_tools._db_component_exists("team", team_id):
            base_version, guard = self._edit_version_snapshot(team_id)
            return self._load_team_from_db(team_id, version=base_version), base_version, guard
        resolved = self._runner_tools._resolve_db_id_by_name_or_slug("team", team_id)
        if resolved is None:
            return None, None, None
        base_version, guard = self._edit_version_snapshot(resolved)
        return self._load_team_from_db(resolved, version=base_version), base_version, guard

    def _find_workflow_for_edit(
        self, workflow_id: str
    ) -> tuple[Optional["Workflow"], Optional[int], Optional["ComponentVersionGuard"]]:
        for w in self._iter_workflows():
            if getattr(w, "id", None) == workflow_id:
                return w, None, None
        if self._runner_tools._db_component_exists("workflow", workflow_id):
            base_version, guard = self._edit_version_snapshot(workflow_id)
            return self._load_workflow_from_db(workflow_id, version=base_version), base_version, guard
        resolved = self._runner_tools._resolve_db_id_by_name_or_slug("workflow", workflow_id)
        if resolved is None:
            return None, None, None
        base_version, guard = self._edit_version_snapshot(resolved)
        return self._load_workflow_from_db(resolved, version=base_version), base_version, guard

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

            agent = Agent(
                id=generate_component_id_from_name(name),
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

            agent_id, version = self._create_component(agent, db)
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

            db = self._find_db(db_id)
            if db is None:
                message = f"Db not found: {db_id}" if db_id is not None else "StudioTools has no db configured."
                return json.dumps({"error": message})
            try:
                members, missing = self._resolve_members(member_ids, target_db=db)
            except ValueError as e:
                # Ambiguity and id-less refusals are validation of model input,
                # not system failures: no traceback in the operator log.
                return json.dumps({"error": str(e)})
            if missing:
                return json.dumps({"error": f"Members not found: {missing}"})
            if not members:
                return json.dumps({"error": "A team must have at least one member"})

            try:
                members, member_pins = self._bind_members_to_target_db(members, db)
            except ValueError as e:
                return json.dumps({"error": str(e)})
            team = Team(
                id=generate_component_id_from_name(name),
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

            team_id, version = self._create_component(
                team,
                db,
                links=self._links_for_component(team, db=db, pinned_versions=member_pins),
            )
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
            db = self._find_db(db_id)
            if db is None:
                message = f"Db not found: {db_id}" if db_id is not None else "StudioTools has no db configured."
                return json.dumps({"error": message})
            steps, err = self._build_steps(step_specs, fallback_db=db)
            if err is not None:
                return json.dumps({"error": err})

            try:
                step_pins = self._bind_steps_to_target_db(steps, db)
            except ValueError as e:
                return json.dumps({"error": str(e)})
            workflow = Workflow(
                id=generate_component_id_from_name(name),
                name=name,
                description=description,
                steps=steps,
                db=db,
            )

            workflow_id, version = self._create_component(
                workflow,
                db,
                links=self._links_for_component(workflow, db=db, pinned_versions=step_pins),
            )
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
            agent, edit_base_version, edit_guard = self._find_agent_for_edit(agent_id)
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

            replaced_keys = set()
            if tool_names is not None:
                replaced_keys.add("tools")
            if model_id is not None:
                replaced_keys.add("model")
            result = self._save_edit(
                agent,
                replaced_keys=replaced_keys,
                base_version=edit_base_version,
                guard=edit_guard,
            )
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
            team, edit_base_version, edit_guard = self._find_team_for_edit(team_id)
        except StudioRunnerError as e:
            return json.dumps({"error": str(e) or type(e).__name__})
        except Exception as e:
            logger.exception("Failed to resolve team")
            return json.dumps({"error": f"Failed to resolve team '{team_id}': {str(e) or type(e).__name__}"})
        if team is None:
            return json.dumps({"error": f"Team not found: {team_id}"})

        try:
            replaced_pins: Optional[Dict[str, int]] = None
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
                    if self.db is not None:
                        members, replaced_pins = self._bind_members_to_target_db(
                            members, self.db, require_published=not self.enable_versions
                        )
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
                row = self.db.get_config(component_id=resolved_id, version=edit_base_version)
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

            replaced_keys = set()
            if member_ids is not None:
                replaced_keys.add("members")
            if model_id is not None:
                replaced_keys.add("model")
            result = self._save_edit(
                team,
                replaced_keys=replaced_keys,
                pinned_children=replaced_pins,
                base_version=edit_base_version,
                guard=edit_guard,
            )
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
            wf, edit_base_version, edit_guard = self._find_workflow_for_edit(workflow_id)
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
            replaced_pins: Optional[Dict[str, int]] = None
            if step_specs is not None:
                steps, err = self._build_steps(step_specs)
                if err is not None:
                    return json.dumps({"error": err})
                if self.db is not None:
                    try:
                        replaced_pins = self._bind_steps_to_target_db(
                            steps, self.db, require_published=not self.enable_versions
                        )
                    except ValueError as e:
                        return json.dumps({"error": str(e)})
                wf.steps = steps

            result = self._save_edit(
                wf,
                replaced_keys={"steps"} if step_specs is not None else None,
                pinned_children=replaced_pins,
                base_version=edit_base_version,
                guard=edit_guard,
            )
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
            from agno.db.base import ComponentVersionGuard

            component = self.db.get_component(component_id)
            if component is None:
                return json.dumps({"error": f"Component not found: {component_id}"})
            catalog_v2 = getattr(self.db, "component_catalog_api_version", 1) >= 2
            configs = self.db.list_configs(component_id, include_config=False)
            latest_version = max(
                (c["version"] for c in configs if isinstance(c.get("version"), int)),
                default=None,
            )
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
                    self._require_studio_owned(component_id, version=target)
                    if not catalog_v2:
                        self._sync_component_row(component_id, target)
                    return json.dumps({"status": "already_published", "id": component_id, "version": target})

            self._require_studio_owned(component_id, version=target)

            if catalog_v2:
                result = self.db.upsert_config(
                    component_id=component_id,
                    version=target,
                    stage="published",
                    guard=ComponentVersionGuard(
                        latest_version=latest_version,
                        current_version=component.get("current_version"),
                    ),
                )
            else:
                result = self.db.upsert_config(component_id=component_id, version=target, stage="published")
            published_version = result.get("version", target)
            if not catalog_v2:
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
            catalog_v2 = getattr(self.db, "component_catalog_api_version", 1) >= 2
            self._require_studio_owned(component_id, version=version)
            if catalog_v2:
                from agno.db.base import ComponentVersionGuard

                component = self.db.get_component(component_id)
                if component is None:
                    return json.dumps({"error": f"Component not found: {component_id}"})
                configs = self.db.list_configs(component_id, include_config=False)
                latest_version = max(
                    (config["version"] for config in configs if isinstance(config.get("version"), int)),
                    default=None,
                )
                ok = self.db.set_current_version(
                    component_id,
                    version=version,
                    guard=ComponentVersionGuard(
                        latest_version=latest_version,
                        current_version=component.get("current_version"),
                    ),
                )
            else:
                # Catalog-v1 adapters predate keyword-only guards. Preserve
                # their exact call shape instead of probing and catching TypeError.
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
            self._require_studio_owned(component_id, version=version)
            if getattr(self.db, "component_catalog_api_version", 1) >= 2:
                _, guard = self._component_guard(component_id)
                deleted = self.db.delete_config(component_id, version=version, guard=guard)
            else:
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

    def _archive_studio_component(self, component_id: str, component_type: Any, noun: str) -> str:
        """Archive a typed Studio component with the state observed here."""
        if self.db is None:
            return json.dumps({"error": "StudioTools has no db configured; cannot delete components."})

        component = self.db.get_component(component_id, component_type=component_type)
        if component is None:
            resolved = self._runner_tools._resolve_db_id_by_name_or_slug(component_type.value, component_id)
            if resolved is not None:
                return json.dumps(
                    {"error": f"Delete requires the exact id: '{component_id}' resolves to '{resolved}'."}
                )
            return json.dumps({"error": f"{noun} not found: {component_id}"})

        catalog_v2 = getattr(self.db, "component_catalog_api_version", 1) >= 2
        if catalog_v2:
            component, guard = self._component_guard(component_id)
            target_version = component.get("current_version") or guard.latest_version
            self._require_studio_owned(component_id, version=target_version)
            deleted = self.db.delete_component(
                component_id,
                hard_delete=False,
                guard=guard,
                expected_component_type=component_type,
            )
            status = "archived"
        else:
            self._require_studio_owned(component_id)
            deleted = self.db.delete_component(component_id, hard_delete=True)
            status = "deleted"
        if not deleted:
            return json.dumps({"error": f"{noun} not found: {component_id}"})
        return json.dumps({"status": status, "id": component_id})

    def delete_agent(self, agent_id: str) -> str:
        """Archive a Studio-created agent DB component.

        Args:
            agent_id (str): The exact id of the agent to delete. Display names
                do not resolve for destructive operations.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTools has no db configured; cannot delete components."})
        try:
            from agno.db.base import ComponentType

            return self._archive_studio_component(agent_id, ComponentType.AGENT, "Agent")
        except Exception as e:
            logger.exception("Failed to delete agent")
            return json.dumps({"error": str(e) or type(e).__name__})

    def delete_team(self, team_id: str) -> str:
        """Archive a Studio-created team component.

        Args:
            team_id (str): The exact id of the team to delete. Display names
                do not resolve for destructive operations.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTools has no db configured; cannot delete components."})
        try:
            from agno.db.base import ComponentType

            return self._archive_studio_component(team_id, ComponentType.TEAM, "Team")
        except Exception as e:
            logger.exception("Failed to delete team")
            return json.dumps({"error": str(e) or type(e).__name__})

    def delete_workflow(self, workflow_id: str) -> str:
        """Archive a Studio-created workflow component.

        Args:
            workflow_id (str): The exact id of the workflow to delete. Display
                names do not resolve for destructive operations.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTools has no db configured; cannot delete components."})
        try:
            from agno.db.base import ComponentType

            return self._archive_studio_component(workflow_id, ComponentType.WORKFLOW, "Workflow")
        except Exception as e:
            logger.exception("Failed to delete workflow")
            return json.dumps({"error": str(e) or type(e).__name__})

    def restore_component(self, component_id: str) -> str:
        """Restore an archived Studio-created component by exact id.

        Args:
            component_id (str): Exact archived component id. Display names do not resolve.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTools has no db configured; cannot restore components."})
        if getattr(self.db, "component_catalog_api_version", 1) < 2:
            return json.dumps({"error": "Explicit restore requires component catalog API v2"})
        try:
            component, guard = self._component_guard(component_id, include_deleted=True)
            if component.get("deleted_at") is None:
                return json.dumps({"status": "already_active", "id": component_id})

            enabled = {
                "agent": self.enable_agents,
                "team": self.enable_teams,
                "workflow": self.enable_workflows,
            }
            component_type = component.get("component_type")
            if not isinstance(component_type, str) or not enabled.get(component_type, False):
                return json.dumps({"error": f"{component_type or 'unknown'} operations are not enabled"})

            projection_version = component.get("current_version") or guard.latest_version
            config_row = self._require_studio_owned(
                component_id,
                version=projection_version,
                include_deleted=True,
            )
            config = config_row["config"]
            projection: "ComponentProjection" = {
                "name": config.get("name") or component.get("name") or component_id,
                "description": config.get("description"),
                "metadata": deepcopy(config.get("metadata")),
            }
            restored = self.db.restore_component(component_id, guard=guard, projection=projection)
            if not restored:
                return json.dumps({"error": f"Component is not archived: {component_id}"})
            return json.dumps({"status": "restored", "id": component_id})
        except Exception as e:
            logger.exception("Failed to restore component")
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

    async def arestore_component(self, component_id: str) -> str:
        """Async variant of restore_component."""
        return await self._run_sync_tool(self.restore_component, component_id)

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

    def _create_component(
        self,
        component: Component,
        db: "BaseDb",
        links: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[str, Optional[int]]:
        """Create one top-level Studio component without a split transaction.

        Catalog-v2 creation reserves the ID and writes version one atomically.
        If a concurrent creator wins the candidate ID, retry with the next
        suffix instead of appending a second version to the winner's component.
        Catalog-v1 adapters retain their historical non-atomic call shapes.
        """
        from agno.db.base import ComponentAlreadyExistsError

        name = getattr(component, "name", None)
        if not isinstance(name, str) or not name:
            raise ValueError("Component has no name")

        base = generate_component_id_from_name(name)
        suffix = 1
        while True:
            component_id = base if suffix == 1 else f"{base}-{suffix}"
            suffix += 1
            if self._component_id_exists(component_id, db):
                continue
            component.id = component_id

            if getattr(db, "component_catalog_api_version", 1) < 2:
                return component_id, _persist_only(component, db, links=links)

            try:
                _, config_row = db.create_component_with_config(
                    component_id=component_id,
                    component_type=_component_type(component),
                    name=name,
                    description=getattr(component, "description", None),
                    metadata=getattr(component, "metadata", None),
                    config=_canonical_component_config(component),
                    stage="published",
                    links=links,
                )
                return component_id, config_row.get("version")
            except ComponentAlreadyExistsError:
                # The candidate was free at the read above but was reserved by
                # another creator before our atomic insert. Try the next ID.
                continue

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
                or (component_name is not None and generate_component_id_from_name(component_name) == component_id)
            ):
                return True
        if getattr(db, "component_catalog_api_version", 1) >= 2:
            return db.get_component(component_id, include_deleted=True) is not None
        return db.get_component(component_id) is not None

    def _bind_child_to_target_db(
        self, child: Any, target_db: "BaseDb", noun: str, require_published: bool = True
    ) -> tuple[Any, Optional[int]]:
        """The object a stored reference will actually reload from ``target_db``,
        with the version to pin it at.

        Reload resolution is db-first in the target db, then registry, so a
        child resolved from the catalog must match that outcome: an id claimed
        by both a code-defined component and a target-db row is a coin flip
        and refuses; a db-backed child absent from the target db (or stored
        there as a different component type) can never reload as itself and
        refuses; a db-backed child present there is strictly re-resolved from
        that exact db AND version, so the reference, the pin, and the reload
        name one row - and a row too degraded to rebuild refuses at create
        instead of persisting a parent guaranteed not to dispatch. A published
        parent additionally refuses a draft child, whose config can change in
        place under the pin.

        The db offers no transactions, so the typed-metadata and config reads
        are re-verified once; a pair that still disagrees (a concurrent
        replace or delete) refuses rather than persisting a torn snapshot.
        """
        from agno.agent.agent import get_agent_by_id
        from agno.db.base import ComponentType
        from agno.exceptions import ComponentRehydrationError
        from agno.team.team import Team, get_team_by_id

        child_id = getattr(child, "id", None)
        if not isinstance(child_id, str):
            raise ValueError(f"{noun} has no id and cannot be stored as a reference.")
        is_team = isinstance(child, Team)
        expected_type = ComponentType.TEAM if is_team else ComponentType.AGENT
        candidates = self._iter_teams() if is_team else self._iter_agents()
        code_defined = any(getattr(candidate, "id", None) == child_id for candidate in candidates)
        db_label = getattr(target_db, "id", None) or type(target_db).__name__

        def read_snapshot() -> tuple:
            try:
                typed_row = target_db.get_component(child_id, component_type=expected_type)
                untyped = target_db.get_component(child_id) if typed_row is None else typed_row
                config_row = target_db.get_config(component_id=child_id) if typed_row is not None else None
            except NotImplementedError:
                return None, None, None
            return typed_row, untyped, config_row

        component_row, untyped_row, row = read_snapshot()
        verify_component_row, verify_untyped_row, verify_row = read_snapshot()
        torn = (
            (component_row is None) != (verify_component_row is None)
            or (row is None) != (verify_row is None)
            or (
                isinstance(row, dict)
                and isinstance(verify_row, dict)
                and row.get("version") != verify_row.get("version")
            )
        )
        if torn:
            raise ValueError(
                f"{noun} '{child_id}' in db '{db_label}' changed while it was being referenced; retry the operation."
            )
        untyped_row = verify_untyped_row if untyped_row is None else untyped_row

        if code_defined and row is not None:
            raise ValueError(
                f"{noun} id '{child_id}' is claimed by both a code-defined component and a stored "
                f"row in db '{db_label}'; reloading would bind whichever wins that db's precedence. "
                "Give them distinct ids."
            )
        if code_defined:
            # Reconcile the live lists with the registry at selection time:
            # rehydration resolves the registry, so the object being written
            # about must be the object the registry will answer with.
            bucket = self.registry.teams if is_team else self.registry.agents
            registered = next((entry for entry in bucket if getattr(entry, "id", None) == child_id), None)
            if registered is None:
                bucket.append(child)
            elif registered is not child:
                raise ValueError(
                    f"{noun} '{child_id}' from the live list is not the registry's object for that "
                    "id; a reload would bind the registry's. Align the list and the registry."
                )
            return child, None
        if component_row is None and untyped_row is not None:
            raise ValueError(
                f"{noun} '{child_id}' is stored in db '{db_label}' as a "
                f"{untyped_row.get('component_type')}, not the referenced type. Give the "
                "components distinct ids."
            )
        if row is None:
            raise ValueError(
                f"{noun} '{child_id}' is not stored in db '{db_label}'. Create it there first, or "
                "reference a code-defined component."
            )
        if require_published and row.get("stage") != "published":
            raise ValueError(
                f"{noun} '{child_id}' in db '{db_label}' has only a {row.get('stage')} config, "
                "which can change in place under a published parent's pin. Publish the child first."
            )
        resolved_version = row.get("version") if isinstance(row, dict) else None
        loader = get_team_by_id if is_team else get_agent_by_id
        try:
            rebound = loader(db=target_db, id=child_id, version=resolved_version, registry=self.registry, strict=True)
        except ComponentRehydrationError as e:
            raise ValueError(f"{noun} '{child_id}' in db '{db_label}' cannot be rebuilt: {e}") from e
        if rebound is None:
            raise ValueError(f"{noun} '{child_id}' could not be loaded from db '{db_label}'.")
        return rebound, (resolved_version if isinstance(resolved_version, int) else None)

    def _bind_members_to_target_db(
        self, members: List[Any], target_db: "BaseDb", require_published: bool = True
    ) -> tuple[List[Any], Dict[str, int]]:
        bound: List[Any] = []
        pins: Dict[str, int] = {}
        for member in members:
            rebound, version = self._bind_child_to_target_db(
                member, target_db, "Member", require_published=require_published
            )
            bound.append(rebound)
            if version is not None and getattr(rebound, "id", None):
                pins[rebound.id] = version
        return bound, pins

    def _bind_steps_to_target_db(
        self, steps: List[Any], target_db: "BaseDb", require_published: bool = True
    ) -> Dict[str, int]:
        pins: Dict[str, int] = {}
        for step in steps:
            for attr, noun in (("agent", "Step agent"), ("team", "Step team")):
                child = getattr(step, attr, None)
                if child is None:
                    continue
                rebound, version = self._bind_child_to_target_db(
                    child, target_db, noun, require_published=require_published
                )
                setattr(step, attr, rebound)
                if version is not None and getattr(rebound, "id", None):
                    pins[rebound.id] = version
        return pins

    def _target_db_exact(self, identifier: str, target_db: "BaseDb") -> Optional[Any]:
        """The component ``identifier`` names by exact id in the target db.

        Checked across both types; a target db claiming the id as both an
        agent and a team is undecidable from the identifier alone.
        """
        from agno.agent.agent import get_agent_by_id
        from agno.db.base import ComponentType
        from agno.exceptions import ComponentRehydrationError
        from agno.team.team import get_team_by_id

        try:
            agent_row = target_db.get_component(identifier, component_type=ComponentType.AGENT)
            team_row = target_db.get_component(identifier, component_type=ComponentType.TEAM)
        except NotImplementedError:
            return None
        if agent_row is not None and team_row is not None:
            raise ValueError(
                f"Ambiguous member id: '{identifier}' is stored in the target db as both an agent "
                "and a team. Give the components distinct ids."
            )
        if agent_row is None and team_row is None:
            return None
        loader = get_agent_by_id if agent_row is not None else get_team_by_id
        try:
            return loader(db=target_db, id=identifier, registry=self.registry, strict=True)
        except ComponentRehydrationError as e:
            raise ValueError(f"Member '{identifier}' in the target db cannot be rebuilt: {e}") from e

    def _resolve_members(
        self, member_ids: List[str], target_db: Optional["BaseDb"] = None
    ) -> tuple[List[TeamMember], List[str]]:
        """Resolve member identifiers to agents or teams, in request order.

        Exact ids resolve before any name matching - across code-defined
        components, the catalog db, AND the selected target db - so a live
        component merely named like a stored id can never steal that member
        slot. An identifier naming a stored component that fails to load
        counts as missing rather than falling through to name matching.
        """
        runner = self._runner_tools
        members: List[TeamMember] = []
        missing: List[str] = []
        for mid in member_ids:
            agent_match = runner._find_agent_by_exact_id(mid)
            team_match = runner._find_team_by_exact_id(mid)
            if agent_match is None and team_match is None and target_db is not None and target_db is not self.db:
                # Exact ids in the selected target db outrank every name tier.
                target_match = self._target_db_exact(mid, target_db)
                if target_match is not None:
                    members.append(target_match)
                    continue
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

    def _build_steps(
        self, step_specs: List[Dict[str, Any]], fallback_db: Optional["BaseDb"] = None
    ) -> tuple[List[Any], Optional[str]]:
        from agno.workflow.step import Step

        if not step_specs:
            return [], "step_specs must contain at least one step"

        def find_agent(identifier: str) -> Optional[Any]:
            found = self._runner_tools._find_agent_by_exact_id(identifier)
            if found is None and fallback_db is not None and fallback_db is not self.db:
                from agno.agent.agent import get_agent_by_id

                # Exact ids in the selected target db outrank catalog name tiers.
                found = get_agent_by_id(db=fallback_db, id=identifier, registry=self.registry)
            return found if found is not None else self._find_agent(identifier)

        def find_team(identifier: str) -> Optional[Any]:
            found = self._runner_tools._find_team_by_exact_id(identifier)
            if found is None and fallback_db is not None and fallback_db is not self.db:
                from agno.team.team import get_team_by_id

                found = get_team_by_id(db=fallback_db, id=identifier, registry=self.registry)
            return found if found is not None else self._find_team(identifier)

        steps: List[Step] = []
        for i, spec in enumerate(step_specs):
            step_name = spec.get("name") or f"step_{i + 1}"
            step_desc = spec.get("description")
            if "agent_id" in spec:
                agent = find_agent(spec["agent_id"])
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
                team = find_team(spec["team_id"])
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

    # Reference keys a lenient load drops when they cannot resolve (the three
    # model keys are serialized but not yet consumed by from_dict); an edit
    # that did not replace them must not persist the loss.
    _LENIENT_DROPPABLE_KEYS = (
        "tools",
        "input_schema",
        "output_schema",
        "knowledge",
        "reasoning_model",
        "parser_model",
        "output_model",
    )

    def _save_edit(
        self,
        component: Component,
        replaced_keys: Optional[Set[str]] = None,
        pinned_children: Optional[Dict[str, int]] = None,
        base_version: Optional[int] = None,
        guard: Optional["ComponentVersionGuard"] = None,
    ) -> Dict[str, Any]:
        """Persist an edited component.

        With versioning enabled the edit is saved as a draft awaiting
        publish_component; otherwise it is published immediately as the new
        current version.

        The edit round-trips through a leniently loaded object, so the config
        written here keeps the stored value for any unresolvable reference the
        load dropped (unless this edit replaced that key), and re-emits the
        member/step links so the new version stays pinned.
        """
        config = _studio_component_config(_component_to_dict(component))
        replaced = replaced_keys or set()
        component_id = getattr(component, "id", None)
        self._preserve_unresolved_keys(component_id, config, replaced, base_version)
        if replaced & {"members", "steps"}:
            # The edit replaced the composition: pin the new children at the
            # exact versions the binder rebuilt them from.
            links = self._links_for_component(component, pinned_versions=pinned_children)
        else:
            # Untouched composition keeps the base version's pins verbatim,
            # including link kinds this walk does not reconstruct.
            links = self._base_links(component_id, base_version)
        if self.enable_versions:
            version = self._upsert_draft(component, config=config, links=links, guard=guard)
            return {"draft_version": version, "stage": "draft"}
        version = _persist_only(component, self.db, config=config, links=links, guard=guard)
        return {"version": version, "stage": "published"}

    def _preserve_unresolved_keys(
        self,
        component_id: Optional[str],
        config: Dict[str, Any],
        replaced_keys: Set[str],
        base_version: Optional[int],
    ) -> None:
        """Copy stored reference keys the lenient load dropped back into ``config``."""
        if self.db is None or component_id is None:
            return
        base = self._runner_tools._load_config_from_db(component_id, version=base_version)
        if not isinstance(base, dict):
            raise ValueError(
                f"Cannot edit '{component_id}': its stored config could not be read, so an edit would drop "
                "whatever the rebuild does not carry back."
            )
        # The db reference and untouched composition subtrees are
        # base-authoritative: no edit surface changes them, the runtime object
        # cannot improve on them, and re-serializing them churns identity
        # (fresh step_ids would orphan every carried-forward pin).
        for key in ("db", "model", "steps", "members"):
            if key in replaced_keys:
                continue
            config.pop(key, None)
            if key in base:
                config[key] = base[key]
        for key in self._LENIENT_DROPPABLE_KEYS:
            if key in replaced_keys:
                continue
            if key in base and base.get(key) is not None and config.get(key) is None:
                config[key] = base[key]
                log_debug(f"StudioTools: preserving stored '{key}' the lenient load could not resolve.")

    def _base_links(self, component_id: Optional[str], base_version: Optional[int]) -> Optional[List[Dict[str, Any]]]:
        """The base version's links, carried forward verbatim on an edit that
        did not replace the component's composition."""
        if self.db is None or component_id is None:
            return None
        return self._runner_tools._load_links_from_db(component_id, version=base_version)

    def _links_for_component(
        self,
        component: Component,
        db: Optional["BaseDb"] = None,
        pinned_versions: Optional[Dict[str, int]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Member/step links for a component snapshot, pinned at each child's
        current stored version in the SAME db the snapshot is written to.

        The persist paths do not cascade-save, so children are not re-saved. A
        child gets no link when it has no stored version in that db, or when a
        code-defined component claims its exact id: resolution prefers the live
        object there, and pinning the same-id db row would bind an unrelated
        shadow.
        """
        from agno.team.team import Team
        from agno.workflow.condition import Condition
        from agno.workflow.loop import Loop
        from agno.workflow.parallel import Parallel
        from agno.workflow.router import Router
        from agno.workflow.step import Step
        from agno.workflow.steps import Steps
        from agno.workflow.workflow import Workflow

        target_db = db if db is not None else self.db
        if target_db is None:
            return None

        def code_defined(child_id: Optional[str], candidates: List[Any]) -> bool:
            return any(getattr(candidate, "id", None) == child_id for candidate in candidates)

        def current_version(child_id: Optional[str], expected_type: Optional[str] = None) -> Optional[int]:
            if not child_id:
                return None
            if pinned_versions is not None and child_id in pinned_versions:
                # The binder already selected this exact version; a fresh read
                # could see a publish that happened since.
                return pinned_versions[child_id]
            if expected_type is not None:
                from agno.db.base import ComponentType

                try:
                    if target_db.get_component(child_id, component_type=ComponentType(expected_type)) is None:
                        # A same-id row of a different type is not this child.
                        return None
                except NotImplementedError:
                    return None
            try:
                row = target_db.get_config(component_id=child_id)
            except NotImplementedError:
                return None
            version = row.get("version") if isinstance(row, dict) else None
            return version if isinstance(version, int) else None

        links: List[Dict[str, Any]] = []
        if isinstance(component, Team):
            from agno.agent.agent import Agent

            code_agents = list(self._iter_agents())
            code_teams = list(self._iter_teams())
            members = component.members if isinstance(component.members, list) else []
            for position, member in enumerate(members):
                member_id = getattr(member, "id", None)
                is_member_team = isinstance(member, Team)
                candidates = code_teams if is_member_team else code_agents
                if code_defined(member_id, candidates):
                    continue
                child_version = current_version(member_id, "team" if is_member_team else "agent")
                if child_version is None:
                    continue
                links.append(
                    {
                        "link_kind": "member",
                        "link_key": f"member_{position}",
                        "child_component_id": member.id,
                        "child_version": child_version,
                        "position": position,
                        "meta": {"type": "agent" if isinstance(member, Agent) else "team"},
                    }
                )
        elif isinstance(component, Workflow):
            code_agents = list(self._iter_agents())
            code_teams = list(self._iter_teams())

            def walk(step: Any, position: int, key_suffix: str = "") -> None:
                if isinstance(step, Step):
                    for link in step.get_links(position=position):
                        child_id = link.get("child_component_id")
                        link_kind = link.get("link_kind")
                        candidates: List[Any]
                        if link_kind == "step_team":
                            candidates = code_teams
                            child_type = "team"
                        elif link_kind == "step_workflow":
                            candidates = list(self._iter_workflows())
                            child_type = "workflow"
                        else:
                            candidates = code_agents
                            child_type = "agent"
                        if code_defined(child_id, candidates):
                            continue
                        child_version = current_version(child_id, child_type)
                        if child_version is None:
                            continue
                        link["child_version"] = child_version
                        if key_suffix:
                            link["link_key"] = f"{link.get('link_key')}{key_suffix}"
                        links.append(link)
                elif isinstance(step, (Parallel, Loop, Steps, Condition)):
                    for nested_position, nested in enumerate(getattr(step, "steps", None) or []):
                        walk(nested, nested_position, key_suffix)
                    for nested_position, nested in enumerate(getattr(step, "else_steps", None) or []):
                        walk(nested, nested_position, key_suffix + "#else")
                elif isinstance(step, Router):
                    for nested_position, nested in enumerate(getattr(step, "choices", None) or []):
                        walk(nested, nested_position, key_suffix)

            steps = component.steps if isinstance(component.steps, list) else []
            for position, step in enumerate(steps):
                walk(step, position)
            seen_links: Dict[tuple, Dict[str, Any]] = {}
            deduped: List[Dict[str, Any]] = []
            for link in links:
                dedupe_key = (link.get("link_kind"), link.get("link_key"))
                existing = seen_links.get(dedupe_key)
                if existing is not None:
                    if existing.get("child_component_id") == link.get("child_component_id"):
                        continue
                    raise ValueError(
                        f"Workflow '{getattr(component, 'id', None)}' produces two different links "
                        f"for key '{link.get('link_key')}' ('{existing.get('child_component_id')}' "
                        f"and '{link.get('child_component_id')}'); give steps distinct names so "
                        "every pin is kept."
                    )
                seen_links[dedupe_key] = link
                deduped.append(link)
            links = deduped
        else:
            return None
        return links

    def _upsert_draft(
        self,
        component: Component,
        config: Optional[Dict[str, Any]] = None,
        links: Optional[List[Dict[str, Any]]] = None,
        guard: Optional["ComponentVersionGuard"] = None,
    ) -> Optional[int]:
        """Append an immutable draft using the component version observed by this edit.

        The component row's name/description/metadata are NOT updated here --
        draft-only changes must not leak into listings until the draft is
        published.
        """
        if self.db is None:
            raise ValueError("db is required for draft persistence")

        component_id = getattr(component, "id", None)
        if component_id is None:
            raise ValueError("Component has no id")

        catalog_v2 = getattr(self.db, "component_catalog_api_version", 1) >= 2
        component_row = self.db.get_component(component_id)
        if component_row is None:
            if catalog_v2:
                raise ValueError(f"Component not found: {component_id}")
            self.db.upsert_component(
                component_id=component_id,
                component_type=_component_type(component),
                name=getattr(component, "name", component_id),
                description=getattr(component, "description", None),
                metadata=getattr(component, "metadata", None),
            )

        draft_config = _studio_component_config(config if config is not None else _component_to_dict(component))

        if not catalog_v2:
            result = self.db.upsert_config(
                component_id=component_id,
                version=self._latest_draft_version(component_id),
                config=draft_config,
                stage="draft",
                links=links,
            )
            return result.get("version")

        if guard is None:
            raise ValueError("A catalog-v2 draft append requires a component version guard")

        result = self.db.upsert_config(
            component_id=component_id,
            config=draft_config,
            stage="draft",
            links=links,
            guard=guard,
        )
        return result.get("version")

    def _sync_component_row(self, component_id: str, version: Optional[int]) -> None:
        """Sync legacy catalog-v1 projections after a publication."""
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
    config: Optional[Dict[str, Any]] = None,
    links: Optional[List[Dict[str, Any]]] = None,
    guard: Optional["ComponentVersionGuard"] = None,
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
    from agno.db.utils import save_component_config

    result = save_component_config(
        db,
        component_id=component_id,
        component_type=_component_type(component),
        name=getattr(component, "name", component_id),
        description=getattr(component, "description", None),
        metadata=getattr(component, "metadata", None),
        config=_studio_component_config(config if config is not None else _component_to_dict(component)),
        stage=stage,
        links=links,
        guard=guard,
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


def _canonical_component_config(component: Component) -> Dict[str, Any]:
    """Embed the complete catalog projection in an immutable Studio config."""
    config = _component_to_dict(component)
    config.update(
        {
            "name": getattr(component, "name", None) or getattr(component, "id", None),
            "description": getattr(component, "description", None),
            "metadata": deepcopy(getattr(component, "metadata", None)),
        }
    )
    return _studio_component_config(config)


def _studio_component_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Stamp immutable ownership metadata on every Studio-written version."""
    marked = deepcopy(config)
    marked[_STUDIO_CONFIG_KEY] = deepcopy(_STUDIO_CONFIG_MANIFEST)
    return marked


# Backward-compatible alias. The toolkit was originally released as ``StudioTool``
# (singular); ``StudioTools`` is the canonical name. Both refer to the same class.
StudioTool = StudioTools
