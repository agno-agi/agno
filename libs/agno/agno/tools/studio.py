"""StudioTool -- give agents the ability to compose agents, teams, and workflows.

Uses the AgentOS Registry (tools, models, dbs, functions) and the core
component APIs (Agent, Team, Workflow, Step) to dynamically create, edit,
version, and execute components described in natural language.

Typical use:
    from agno.tools.studio import StudioTool

    studio_agent = Agent(
        model=Claude(id="claude-sonnet-4-5"),
        tools=[StudioTool(registry=registry, db=db)],
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
      - with versions=False (default) the edit is published immediately as the
        new current version.

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

Persistence:
    * Studio saves ONLY the component it creates/edits. It does NOT cascade to
      member agents or step agents -- those are assumed to be code-defined
      (registry / passed-in lists) or separately persisted by a prior create_*.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union

from agno.tools.function import Function
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, logger

if TYPE_CHECKING:
    from agno.agent.agent import Agent
    from agno.db.base import BaseDb
    from agno.models.base import Model
    from agno.registry.registry import Registry
    from agno.team.team import Team
    from agno.workflow.workflow import Workflow

Component = Union["Agent", "Team", "Workflow"]
TeamMember = Union["Agent", "Team"]


class StudioTool(Toolkit):
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
        agents: Expose agent operations. Defaults to True.
        teams: Expose team operations. Defaults to False (see module docstring
            for auto-enable rules).
        workflows: Expose workflow operations. Defaults to False.
        versions: Expose versioning tools (list_versions, get_version,
            publish_component, set_current_version, delete_version). Defaults
            to False; without versioning, edits publish immediately instead of
            producing drafts.
    """

    def __init__(
        self,
        registry: "Registry",
        db: Optional["BaseDb"] = None,
        agents_list: Optional[List["Agent"]] = None,
        teams_list: Optional[List["Team"]] = None,
        workflows_list: Optional[List["Workflow"]] = None,
        default_model_id: Optional[str] = None,
        agents: Optional[bool] = None,
        teams: Optional[bool] = None,
        workflows: Optional[bool] = None,
        versions: bool = False,
        **kwargs: Any,
    ):
        self.registry = registry
        self.db: Optional["BaseDb"] = db if db is not None else (registry.dbs[0] if registry.dbs else None)
        self.agents_list = agents_list
        self.teams_list = teams_list
        self.workflows_list = workflows_list
        self.default_model_id = default_model_id

        self.enable_agents, self.enable_teams, self.enable_workflows = _resolve_flags(
            agents=agents,
            teams=teams,
            workflows=workflows,
            has_agents_list=agents_list is not None,
            has_teams_list=teams_list is not None,
        )
        self.enable_versions: bool = versions

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

        instruction_lines = [
            "Compose agents, teams, and workflows from registry primitives.",
            "Discovery: call list_tools/list_functions/list_models/list_dbs first. Tool and function names "
            "are exact and case-sensitive -- do NOT guess.",
            "Create: create_agent/create_team/create_workflow. When the user mentions specific "
            "tools, you MUST include ALL of those names in tool_names; do not silently drop any.",
            "Edit: ALWAYS call get_agent/get_team/get_workflow first to read the current state, "
            "then call edit_agent/edit_team/edit_workflow with only the fields that change.",
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
        """Match by Toolkit.name, Function.name, callable __name__, or toolkit function key."""
        for tool in self.registry.tools:
            if isinstance(tool, Toolkit) and tool.name == name:
                return tool
            if isinstance(tool, Function) and tool.name == name:
                return tool
            if callable(tool) and getattr(tool, "__name__", None) == name:
                return tool
            if isinstance(tool, Toolkit) and name in tool.functions:
                return tool.functions[name]
        return None

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
        return resolved

    # ------------------------------------------------------------------
    # Component lookup: union of live lists, registry, and studio cache.
    # Studio cache is checked first so freshly created/edited components
    # are always current in-process.
    # ------------------------------------------------------------------

    def _iter_agents(self) -> List["Agent"]:
        """Code-defined agents: passed-in list, else registry.agents."""
        if self.agents_list is not None:
            return list(self.agents_list)
        return list(self.registry.agents)

    def _iter_teams(self) -> List["Team"]:
        """Code-defined teams: passed-in list, else registry.teams."""
        if self.teams_list is not None:
            return list(self.teams_list)
        return list(self.registry.teams)

    def _iter_workflows(self) -> List["Workflow"]:
        """Code-defined workflows."""
        return list(self.workflows_list) if self.workflows_list is not None else []

    def _find_agent(self, agent_id: str) -> Optional["Agent"]:
        """Lookup order: code-defined list, then DB. Studio-created components live in DB."""
        for a in self._iter_agents():
            if getattr(a, "id", None) == agent_id or getattr(a, "name", None) == agent_id:
                return a
        return self._load_agent_from_db(agent_id)

    def _find_team(self, team_id: str) -> Optional["Team"]:
        for t in self._iter_teams():
            if getattr(t, "id", None) == team_id or getattr(t, "name", None) == team_id:
                return t
        return self._load_team_from_db(team_id)

    def _find_workflow(self, workflow_id: str) -> Optional["Workflow"]:
        for w in self._iter_workflows():
            if getattr(w, "id", None) == workflow_id or getattr(w, "name", None) == workflow_id:
                return w
        return self._load_workflow_from_db(workflow_id)

    # Edit-base lookups: like _find_*, but DB components load from the latest
    # draft when versioning is enabled, so successive partial edits accumulate
    # instead of each resetting to the published config.

    def _find_agent_for_edit(self, agent_id: str) -> Optional["Agent"]:
        for a in self._iter_agents():
            if getattr(a, "id", None) == agent_id or getattr(a, "name", None) == agent_id:
                return a
        return self._load_agent_from_db(agent_id, version=self._edit_base_version(agent_id))

    def _find_team_for_edit(self, team_id: str) -> Optional["Team"]:
        for t in self._iter_teams():
            if getattr(t, "id", None) == team_id or getattr(t, "name", None) == team_id:
                return t
        return self._load_team_from_db(team_id, version=self._edit_base_version(team_id))

    def _find_workflow_for_edit(self, workflow_id: str) -> Optional["Workflow"]:
        for w in self._iter_workflows():
            if getattr(w, "id", None) == workflow_id or getattr(w, "name", None) == workflow_id:
                return w
        return self._load_workflow_from_db(workflow_id, version=self._edit_base_version(workflow_id))

    def _edit_base_version(self, component_id: str) -> Optional[int]:
        """Version to base an edit on: the latest draft when versioning is
        enabled, else None (the current published version)."""
        if not self.enable_versions:
            return None
        return self._latest_draft_version(component_id)

    def _latest_draft_version(self, component_id: str) -> Optional[int]:
        if self.db is None:
            return None
        try:
            configs = self.db.list_configs(component_id, include_config=False)
        except Exception:
            logger.debug(f"StudioTool: list_configs failed for {component_id}", exc_info=True)
            return None
        drafts: List[int] = [
            c["version"] for c in configs if c.get("stage") == "draft" and isinstance(c.get("version"), int)
        ]
        return max(drafts) if drafts else None

    def _load_agent_from_db(self, agent_id: str, version: Optional[int] = None) -> Optional["Agent"]:
        """Load an agent from DB via config + from_dict. Bypasses Agent.load() to
        avoid Agno's load_component_graph signature mismatch."""
        config = self._load_config_from_db(agent_id, version=version)
        if config is None:
            return None
        from agno.agent.agent import Agent

        try:
            agent = Agent.from_dict(config, registry=self.registry)
            agent.id = agent_id
            agent.db = self.db
            return agent
        except Exception:
            logger.warning("StudioTool: Agent.from_dict failed for %s", agent_id, exc_info=True)
            return None

    def _load_team_from_db(self, team_id: str, version: Optional[int] = None) -> Optional["Team"]:
        config = self._load_config_from_db(team_id, version=version)
        if config is None:
            return None
        from agno.team.team import Team

        try:
            team = Team.from_dict(config, db=self.db, registry=self.registry)
            team.id = team_id
            team.db = self.db
            return team
        except Exception:
            logger.warning("StudioTool: Team.from_dict failed for %s", team_id, exc_info=True)
            return None

    def _load_workflow_from_db(self, workflow_id: str, version: Optional[int] = None) -> Optional["Workflow"]:
        config = self._load_config_from_db(workflow_id, version=version)
        if config is None:
            return None
        from agno.workflow.workflow import Workflow

        try:
            wf = Workflow.from_dict(config, db=self.db, registry=self.registry)
            wf.id = workflow_id
            wf.db = self.db
            return wf
        except Exception:
            logger.warning("StudioTool: Workflow.from_dict failed for %s", workflow_id, exc_info=True)
            return None

    def _load_config_from_db(self, component_id: str, version: Optional[int] = None) -> Optional[Dict[str, Any]]:
        if self.db is None:
            return None
        try:
            row = self.db.get_config(component_id=component_id, version=version)
        except Exception:
            logger.warning("StudioTool: db.get_config failed for %s", component_id, exc_info=True)
            return None
        if row is None:
            return None
        config = row.get("config") if isinstance(row, dict) else None
        return config if isinstance(config, dict) else None

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
            return json.dumps({"error": str(e)})

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
            return json.dumps({"error": str(e)})

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
            return json.dumps({"error": str(e)})

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
            return json.dumps({"error": str(e)})

    def list_agents(self) -> str:
        """List all known agents: code-defined (registry / agents_list) plus DB components.

        Returns:
            str: JSON object with 'agents' (each {id, name, model_id, tools, source}) and 'count'.
                'source' is 'code' for registry/list-defined agents, 'db' for DB components.
        """
        try:
            result: List[Dict[str, Any]] = []
            seen: set[str] = set()
            for a in self._iter_agents():
                aid = getattr(a, "id", None)
                name = getattr(a, "name", None)
                if aid is not None:
                    seen.add(aid)
                if name is not None:
                    seen.add(name)
                result.append(
                    {
                        "id": aid,
                        "name": name,
                        "model_id": getattr(getattr(a, "model", None), "id", None),
                        "tools": _summarize_tools(getattr(a, "tools", None)),
                        "source": "code",
                    }
                )
            for row in self._list_db_components("agent"):
                if row["id"] in seen or row["name"] in seen:
                    continue
                result.append({**row, "source": "db"})
            return json.dumps({"agents": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to list agents")
            return json.dumps({"error": str(e)})

    def list_teams(self) -> str:
        """List all known teams: code-defined plus DB components.

        Returns:
            str: JSON object with 'teams' (each {id, name, model_id, member_ids?, source}) and 'count'.
        """
        try:
            result: List[Dict[str, Any]] = []
            seen: set[str] = set()
            for team in self._iter_teams():
                tid = getattr(team, "id", None)
                name = getattr(team, "name", None)
                if tid is not None:
                    seen.add(tid)
                if name is not None:
                    seen.add(name)
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
            for row in self._list_db_components("team"):
                if row["id"] in seen or row["name"] in seen:
                    continue
                result.append({**row, "source": "db"})
            return json.dumps({"teams": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to list teams")
            return json.dumps({"error": str(e)})

    def list_workflows(self) -> str:
        """List all known workflows: code-defined plus DB components.

        Returns:
            str: JSON object with 'workflows' (each {id, name, description, steps?, source}) and 'count'.
        """
        try:
            result: List[Dict[str, Any]] = []
            seen: set[str] = set()
            for wf in self._iter_workflows():
                wid = getattr(wf, "id", None)
                name = getattr(wf, "name", None)
                if wid is not None:
                    seen.add(wid)
                if name is not None:
                    seen.add(name)
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
            for row in self._list_db_components("workflow"):
                if row["id"] in seen or row["name"] in seen:
                    continue
                result.append({**row, "source": "db"})
            return json.dumps({"workflows": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to list workflows")
            return json.dumps({"error": str(e)})

    def _list_db_components(self, component_type: str) -> List[Dict[str, Any]]:
        """Return a thin summary of DB components of a given type: [{id, name, description}]."""
        if self.db is None:
            return []
        try:
            from agno.db.base import ComponentType

            rows, _ = self.db.list_components(component_type=ComponentType(component_type))
            return [
                {
                    "id": r.get("component_id"),
                    "name": r.get("name"),
                    "description": r.get("description"),
                }
                for r in rows
            ]
        except Exception:
            logger.debug("StudioTool: list_components failed", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Read one
    # ------------------------------------------------------------------

    def get_agent(self, agent_id: str) -> str:
        """Read an agent's current published config. Call this before edit_agent.

        Args:
            agent_id (str): The id or name of the agent.
        """
        agent = self._find_agent(agent_id)
        if agent is None:
            return json.dumps({"error": f"Agent not found: {agent_id}"})
        return json.dumps(
            {
                "id": getattr(agent, "id", None),
                "name": getattr(agent, "name", None),
                "model_id": getattr(getattr(agent, "model", None), "id", None),
                "instructions": getattr(agent, "instructions", None),
                "description": getattr(agent, "description", None),
                "tools": _summarize_tools(getattr(agent, "tools", None)),
            },
            default=str,
        )

    def get_team(self, team_id: str) -> str:
        """Read a team's current published config. Call this before edit_team.

        Args:
            team_id (str): The id or name of the team.
        """
        team = self._find_team(team_id)
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
            },
            default=str,
        )

    def get_workflow(self, workflow_id: str) -> str:
        """Read a workflow's current published config. Call this before edit_workflow.

        Args:
            workflow_id (str): The id or name of the workflow.
        """
        wf = self._find_workflow(workflow_id)
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

        Returns:
            str: JSON with {status, id, name, model_id, tools, db_version}.
        """
        from agno.agent.agent import Agent

        try:
            model = self._find_model(model_id)
            if model is None:
                return json.dumps({"error": f"Model not found: {model_id or 'default'}"})
            tools = self._resolve_tools(tool_names)
            db = self._find_db(db_id)
            if db is None:
                message = f"Db not found: {db_id}" if db_id is not None else "StudioTool has no db configured."
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
            )

            version = _persist_only(agent, db)
            log_debug(f"StudioTool created agent id={agent_id} version={version}")
            return json.dumps(
                {
                    "status": "created",
                    "id": agent_id,
                    "name": name,
                    "model_id": getattr(model, "id", None),
                    "tools": _summarize_tools(tools),
                    "db_version": version,
                }
            )
        except Exception as e:
            logger.exception("Failed to create agent")
            return json.dumps({"error": str(e)})

    def create_team(
        self,
        name: str,
        instructions: str,
        member_ids: List[str],
        model_id: Optional[str] = None,
        db_id: Optional[str] = None,
        description: Optional[str] = None,
    ) -> str:
        """Create a new team and persist it as a published component.

        Args:
            name (str): Display name; also used as the id.
            instructions (str): Instructions that steer the team leader.
            member_ids (List[str]): Ids of existing agents or teams (see list_agents/list_teams).
            model_id (Optional[str]): Model id for the team leader.
            db_id (Optional[str]): Database id from the registry.
            description (Optional[str]): Optional description.

        Returns:
            str: JSON with {status, id, name, model_id, member_ids, db_version}.
        """
        from agno.team.team import Team

        try:
            model = self._find_model(model_id)
            if model is None:
                return json.dumps({"error": f"Model not found: {model_id or 'default'}"})

            members, missing = self._resolve_members(member_ids)
            if missing:
                return json.dumps({"error": f"Members not found: {missing}"})
            if not members:
                return json.dumps({"error": "A team must have at least one member"})

            db = self._find_db(db_id)
            if db is None:
                message = f"Db not found: {db_id}" if db_id is not None else "StudioTool has no db configured."
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
            )

            version = _persist_only(team, db)
            log_debug(f"StudioTool created team id={team_id} members={member_ids} version={version}")
            return json.dumps(
                {
                    "status": "created",
                    "id": team_id,
                    "name": name,
                    "model_id": getattr(model, "id", None),
                    "member_ids": [getattr(m, "id", None) for m in members],
                    "db_version": version,
                }
            )
        except Exception as e:
            logger.exception("Failed to create team")
            return json.dumps({"error": str(e)})

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
                message = f"Db not found: {db_id}" if db_id is not None else "StudioTool has no db configured."
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
            log_debug(f"StudioTool created workflow id={workflow_id} steps={len(steps)} version={version}")
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
            return json.dumps({"error": str(e)})

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
    ) -> str:
        """Edit an agent.

        Always call get_agent(agent_id) first to read the current state, then
        pass only the fields that should change. With versioning enabled the
        edit is saved as a draft (use publish_component to promote it);
        otherwise it is published immediately as the new current version.

        Args:
            agent_id (str): The id of the agent to edit.
            instructions (Optional[str]): New instructions. Omit to keep.
            model_id (Optional[str]): New model id from the registry. Omit to keep.
            tool_names (Optional[List[str]]): New tool list (replaces existing). Omit to keep.
            description (Optional[str]): New description. Omit to keep.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTool has no db configured; cannot edit components."})
        agent = self._find_agent_for_edit(agent_id)
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

            result = self._save_edit(agent)
            log_debug(f"StudioTool edited agent id={agent_id} result={result}")
            return json.dumps({"status": "edited", "id": agent_id, **result})
        except Exception as e:
            logger.exception("Failed to edit agent")
            return json.dumps({"error": str(e)})

    def edit_team(
        self,
        team_id: str,
        instructions: Optional[str] = None,
        model_id: Optional[str] = None,
        member_ids: Optional[List[str]] = None,
        description: Optional[str] = None,
    ) -> str:
        """Edit a team.

        Always call get_team(team_id) first to read the current state, then
        pass only the fields that should change. With versioning enabled the
        edit is saved as a draft (use publish_component to promote it);
        otherwise it is published immediately as the new current version.

        Args:
            team_id (str): The id of the team to edit.
            instructions (Optional[str]): New instructions. Omit to keep.
            model_id (Optional[str]): New model id. Omit to keep.
            member_ids (Optional[List[str]]): New member ids (replaces existing). Omit to keep.
            description (Optional[str]): New description. Omit to keep.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTool has no db configured; cannot edit components."})
        team = self._find_team_for_edit(team_id)
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
                members, missing = self._resolve_members(member_ids)
                if missing:
                    return json.dumps({"error": f"Members not found: {missing}"})
                if not members:
                    return json.dumps({"error": "A team must have at least one member"})
                team.members = members

            result = self._save_edit(team)
            log_debug(f"StudioTool edited team id={team_id} result={result}")
            return json.dumps({"status": "edited", "id": team_id, **result})
        except Exception as e:
            logger.exception("Failed to edit team")
            return json.dumps({"error": str(e)})

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
            workflow_id (str): The id of the workflow to edit.
            description (Optional[str]): New description. Omit to keep.
            step_specs (Optional[List[dict]]): New ordered steps (replaces existing). Omit to keep.
                Same shape as create_workflow.step_specs.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTool has no db configured; cannot edit components."})
        wf = self._find_workflow_for_edit(workflow_id)
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
            log_debug(f"StudioTool edited workflow id={workflow_id} result={result}")
            return json.dumps({"status": "edited", "id": workflow_id, **result})
        except Exception as e:
            logger.exception("Failed to edit workflow")
            return json.dumps({"error": str(e)})

    # ------------------------------------------------------------------
    # Versioning / configs
    # ------------------------------------------------------------------

    def list_versions(self, component_id: str) -> str:
        """List all config versions for a component.

        Args:
            component_id (str): The component id.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTool has no db configured."})
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
            return json.dumps({"error": str(e)})

    def get_version(self, component_id: str, version: Optional[int] = None) -> str:
        """Get a specific config version. If version is omitted, returns the current version.

        Args:
            component_id (str): The component id.
            version (Optional[int]): Version number, or omit for the current version.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTool has no db configured."})
        try:
            config = self.db.get_config(component_id=component_id, version=version)
            if config is None:
                return json.dumps({"error": f"Version not found: component_id={component_id} version={version}"})
            return json.dumps(config, default=str)
        except Exception as e:
            logger.exception("Failed to get version")
            return json.dumps({"error": str(e)})

    def publish_component(self, component_id: str, version: Optional[int] = None) -> str:
        """Promote a draft to published (and make it the current version).

        Args:
            component_id (str): The component id.
            version (Optional[int]): The draft version to publish. If omitted, publishes the
                latest draft.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTool has no db configured."})
        try:
            target = version
            if target is None:
                configs = self.db.list_configs(component_id, include_config=False)
                drafts = [c for c in configs if c.get("stage") == "draft"]
                if not drafts:
                    return json.dumps({"error": "No draft version to publish."})
                target = max(d.get("version", 0) for d in drafts)

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
            return json.dumps({"error": str(e)})

    def set_current_version(self, component_id: str, version: int) -> str:
        """Roll back to a previously published version (make it current).

        Args:
            component_id (str): The component id.
            version (int): A published version to set as current.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTool has no db configured."})
        try:
            ok = self.db.set_current_version(component_id, version=version)
            if not ok:
                return json.dumps({"error": f"Component or version not found: {component_id} v{version}"})
            return json.dumps({"status": "set_current", "id": component_id, "version": version})
        except Exception as e:
            logger.exception("Failed to set current version")
            return json.dumps({"error": str(e)})

    def delete_version(self, component_id: str, version: int) -> str:
        """Delete a draft config version. Published and current versions cannot be deleted.

        Args:
            component_id (str): The component id.
            version (int): The draft version to delete.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTool has no db configured."})
        try:
            deleted = self.db.delete_config(component_id, version=version)
            if not deleted:
                return json.dumps({"error": f"Version not found: {component_id} v{version}"})
            return json.dumps({"status": "deleted", "id": component_id, "version": version})
        except Exception as e:
            logger.exception("Failed to delete version")
            return json.dumps({"error": str(e)})

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_agent(self, agent_id: str) -> str:
        """Hard-delete an agent DB component.

        Args:
            agent_id (str): The id of the agent to delete.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTool has no db configured; cannot delete components."})
        try:
            from agno.db.base import ComponentType

            component = self.db.get_component(agent_id, component_type=ComponentType.AGENT)
            if component is None:
                return json.dumps({"error": f"Agent not found: {agent_id}"})
            deleted = self.db.delete_component(agent_id, hard_delete=True)
            if not deleted:
                return json.dumps({"error": f"Agent not found: {agent_id}"})
            return json.dumps({"status": "deleted", "id": agent_id})
        except Exception as e:
            logger.exception("Failed to delete agent")
            return json.dumps({"error": str(e)})

    def delete_team(self, team_id: str) -> str:
        """Hard-delete a team component.

        Args:
            team_id (str): The id of the team to delete.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTool has no db configured; cannot delete components."})
        try:
            from agno.db.base import ComponentType

            component = self.db.get_component(team_id, component_type=ComponentType.TEAM)
            if component is None:
                return json.dumps({"error": f"Team not found: {team_id}"})
            deleted = self.db.delete_component(team_id, hard_delete=True)
            if not deleted:
                return json.dumps({"error": f"Team not found: {team_id}"})
            return json.dumps({"status": "deleted", "id": team_id})
        except Exception as e:
            logger.exception("Failed to delete team")
            return json.dumps({"error": str(e)})

    def delete_workflow(self, workflow_id: str) -> str:
        """Hard-delete a workflow component.

        Args:
            workflow_id (str): The id of the workflow to delete.
        """
        if self.db is None:
            return json.dumps({"error": "StudioTool has no db configured; cannot delete components."})
        try:
            from agno.db.base import ComponentType

            component = self.db.get_component(workflow_id, component_type=ComponentType.WORKFLOW)
            if component is None:
                return json.dumps({"error": f"Workflow not found: {workflow_id}"})
            deleted = self.db.delete_component(workflow_id, hard_delete=True)
            if not deleted:
                return json.dumps({"error": f"Workflow not found: {workflow_id}"})
            return json.dumps({"status": "deleted", "id": workflow_id})
        except Exception as e:
            logger.exception("Failed to delete workflow")
            return json.dumps({"error": str(e)})

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def run_agent(self, agent_id: str, message: str) -> str:
        """Run an agent and return its response content.

        Args:
            agent_id (str): The id of the agent to run.
            message (str): The message to send.
        """
        agent = self._find_agent(agent_id)
        if agent is None:
            return json.dumps({"error": f"Agent not found: {agent_id}"})
        try:
            response = agent.run(message)
            return json.dumps({"id": agent_id, "content": getattr(response, "content", None)}, default=str)
        except Exception as e:
            logger.exception("Failed to run agent")
            return json.dumps({"error": str(e)})

    def run_team(self, team_id: str, message: str) -> str:
        """Run a team and return its response content.

        Args:
            team_id (str): The id of the team to run.
            message (str): The message to send.
        """
        team = self._find_team(team_id)
        if team is None:
            return json.dumps({"error": f"Team not found: {team_id}"})
        try:
            response = team.run(message)
            return json.dumps({"id": team_id, "content": getattr(response, "content", None)}, default=str)
        except Exception as e:
            logger.exception("Failed to run team")
            return json.dumps({"error": str(e)})

    def run_workflow(self, workflow_id: str, message: str) -> str:
        """Run a workflow and return its final content.

        Args:
            workflow_id (str): The id of the workflow to run.
            message (str): Input to pass to the first step.
        """
        wf = self._find_workflow(workflow_id)
        if wf is None:
            return json.dumps({"error": f"Workflow not found: {workflow_id}"})
        try:
            response = wf.run(input=message)
            return json.dumps({"id": workflow_id, "content": getattr(response, "content", None)}, default=str)
        except Exception as e:
            logger.exception("Failed to run workflow")
            return json.dumps({"error": str(e)})

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
        )

    async def acreate_team(
        self,
        name: str,
        instructions: str,
        member_ids: List[str],
        model_id: Optional[str] = None,
        db_id: Optional[str] = None,
        description: Optional[str] = None,
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
    ) -> str:
        """Async variant of edit_agent."""
        return await self._run_sync_tool(
            self.edit_agent,
            agent_id,
            instructions=instructions,
            model_id=model_id,
            tool_names=tool_names,
            description=description,
        )

    async def aedit_team(
        self,
        team_id: str,
        instructions: Optional[str] = None,
        model_id: Optional[str] = None,
        member_ids: Optional[List[str]] = None,
        description: Optional[str] = None,
    ) -> str:
        """Async variant of edit_team."""
        return await self._run_sync_tool(
            self.edit_team,
            team_id,
            instructions=instructions,
            model_id=model_id,
            member_ids=member_ids,
            description=description,
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

    async def arun_agent(self, agent_id: str, message: str) -> str:
        """Async variant of run_agent.

        Args:
            agent_id (str): The id of the agent to run.
            message (str): The message to send.
        """
        agent = self._find_agent(agent_id)
        if agent is None:
            return json.dumps({"error": f"Agent not found: {agent_id}"})
        try:
            response = await agent.arun(message)
            return json.dumps({"id": agent_id, "content": getattr(response, "content", None)}, default=str)
        except Exception as e:
            logger.exception("Failed to run agent")
            return json.dumps({"error": str(e)})

    async def arun_team(self, team_id: str, message: str) -> str:
        """Async variant of run_team.

        Args:
            team_id (str): The id of the team to run.
            message (str): The message to send.
        """
        team = self._find_team(team_id)
        if team is None:
            return json.dumps({"error": f"Team not found: {team_id}"})
        try:
            response = await team.arun(message)
            return json.dumps({"id": team_id, "content": getattr(response, "content", None)}, default=str)
        except Exception as e:
            logger.exception("Failed to run team")
            return json.dumps({"error": str(e)})

    async def arun_workflow(self, workflow_id: str, message: str) -> str:
        """Async variant of run_workflow.

        Args:
            workflow_id (str): The id of the workflow to run.
            message (str): Input to pass to the first step.
        """
        wf = self._find_workflow(workflow_id)
        if wf is None:
            return json.dumps({"error": f"Workflow not found: {workflow_id}"})
        try:
            response = await wf.arun(input=message)
            return json.dumps({"id": workflow_id, "content": getattr(response, "content", None)}, default=str)
        except Exception as e:
            logger.exception("Failed to run workflow")
            return json.dumps({"error": str(e)})

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
        members: List[TeamMember] = []
        missing: List[str] = []
        for mid in member_ids:
            member = self._find_agent(mid) or self._find_team(mid)
            if member is None:
                missing.append(mid)
            else:
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
                steps.append(Step(name=step_name, agent=agent, description=step_desc))
            elif "team_id" in spec:
                team = self._find_team(spec["team_id"])
                if team is None:
                    return [], f"Team not found for step '{step_name}': {spec['team_id']}"
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
        if self.enable_versions:
            version = self._upsert_draft(component)
            return {"draft_version": version, "stage": "draft"}
        version = _persist_only(component, self.db)
        return {"version": version, "stage": "published"}

    def _upsert_draft(self, component: Component) -> Optional[int]:
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
            config=_component_to_dict(component),
            stage="draft",
        )
        return result.get("version")

    def _sync_component_row(self, component_id: str, version: Optional[int]) -> None:
        """Bring the component row's name/description/metadata in line with a
        newly published config version."""
        if self.db is None:
            return
        try:
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
        except Exception:
            logger.debug(f"StudioTool: failed to sync component row for {component_id}", exc_info=True)


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def _slugify(name: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "-" for c in name.strip())
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "component"


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


def _persist_only(component: Component, db: Optional["BaseDb"], stage: str = "published") -> Optional[int]:
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
        config=_component_to_dict(component),
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


def _component_to_dict(component: Component) -> Dict[str, Any]:
    from agno.agent.agent import Agent
    from agno.team.team import Team
    from agno.workflow.workflow import Workflow

    if isinstance(component, Agent):
        from agno.agent._storage import to_dict as agent_to_dict

        return agent_to_dict(component)
    if isinstance(component, Team):
        from agno.team._storage import to_dict as team_to_dict

        return team_to_dict(component)
    if isinstance(component, Workflow):
        return component.to_dict()
    raise TypeError(f"Unsupported component type: {type(component).__name__}")
