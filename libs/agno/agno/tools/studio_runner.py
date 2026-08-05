"""StudioRunnerTools -- discovery and execution over Studio-built components.

The runner is the dispatch half of the Studio: list the agents, teams, and
workflows that exist in the platform database, and run one by id. It carries no
create/edit/delete surface, so it is safe to mount on any component that should
hand work to built components -- a team lead, a router -- without granting the
Studio's mutation tools.

Typical use:
    from agno.tools.studio_runner import StudioRunnerTools

    lead = Team(
        model=...,
        members=[...],
        tools=[StudioRunnerTools(registry=registry, db=db)],
    )

Semantics:
    * Runs execute as the current user: the wielding component's run_context is
      injected and its user_id passed through, so per-user state (memory,
      learning) lands on the human who asked, never on a service default.
    * Each target keeps one session per calling conversation
      ("<caller_session_id>--<component_type>--<component_id>"), so repeat
      runs continue their context instead of starting cold.
    * Code-defined components are dispatched on a fresh deep copy per run
      (mirroring AgentOS's create_fresh resolution), so per-run mutation of a
      shared instance never bleeds across callers. DB-loaded components are
      reconstructed per call already.
    * A PAUSED result carries the unresolved requirements plus the
      run_id/session_id a continue call must address (the same shape the
      AgentOS MCP plane returns) -- human-in-the-loop pauses are relayed, not
      swallowed.
    * Runs are dispatched with stream=False pinned: run-option resolution is
      call-site > component.stream > False, so a component saved with
      stream=True would otherwise hand back an unconsumed event iterator
      instead of its final run output.
    * run_* resolve in a fixed order: code-defined exact id, DB exact id,
      code-defined display name, DB display name, then the identifier's slug
      as an id (covers renamed components, whose ids keep the original
      name's slug). Exact ids always win over display names. A display name
      matching several components of the type returns an error listing the
      matching ids instead of silently picking one.
    * list_* read the database only (id, name, description, newest first):
      code-defined components are the wielding platform's own and are not
      re-listed. 'total' reports the full DB count, so a capped list is
      visible as capped.

StudioTools embeds this toolkit for its own run_* tools and delegates its
component lookups here, so a builder's smoke-test runs and a dispatcher's
production runs share one implementation.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from agno.run import RunContext
from agno.tools.toolkit import Toolkit
from agno.utils.log import logger

if TYPE_CHECKING:
    from agno.agent.agent import Agent
    from agno.db.base import BaseDb, ComponentType
    from agno.registry.registry import Registry
    from agno.team.team import Team
    from agno.workflow.workflow import Workflow

# Page size for the display-name fallback lookup, which scans the components
# table when an identifier is not an exact id.
_NAME_LOOKUP_PAGE = 100


def _slugify(name: str) -> str:
    """Component ids are slugified names (shared with StudioTools' create path)."""
    slug = "".join(c.lower() if c.isalnum() else "-" for c in name.strip())
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "component"


class AmbiguousComponentNameError(ValueError):
    """A display name matched more than one component of the requested type.

    Raised instead of silently resolving to one of them; the message lists the
    matching ids so the caller (model or code) can retry with an exact id.
    """

    def __init__(self, component_type: str, name: str, matches: List[str]):
        self.matches = sorted(matches)
        super().__init__(
            f"Ambiguous {component_type} name: '{name}' matches ids {', '.join(self.matches)}. Use the exact id."
        )


# The two helpers below mirror agno/os/mcp_results.py so toolkit results and MCP
# results speak one vocabulary for run status and paused requirements.
# (mcp_results imports mcp.types, a server extra, so it cannot be imported here.)


def _run_status(run_output: Any) -> str:
    status = getattr(run_output, "status", None)
    value = getattr(status, "value", status)
    return str(value) if value is not None else "COMPLETED"


def _paused_requirements(run_output: Any) -> Optional[List[Dict[str, Any]]]:
    """Serialized unresolved requirements when the run is paused, else None."""
    if not getattr(run_output, "is_paused", False):
        return None
    # Agents/teams expose active_requirements; workflows expose active_step_requirements.
    requirements = (
        getattr(run_output, "active_requirements", None) or getattr(run_output, "active_step_requirements", None) or []
    )
    serialized: List[Dict[str, Any]] = []
    for requirement in requirements:
        if hasattr(requirement, "to_dict"):
            serialized.append(requirement.to_dict())
        elif isinstance(requirement, dict):
            serialized.append(requirement)
    return serialized or None


class StudioRunnerTools(Toolkit):
    def __init__(
        self,
        registry: Optional["Registry"] = None,
        db: Optional["BaseDb"] = None,
        agents_list: Optional[List["Agent"]] = None,
        teams_list: Optional[List["Team"]] = None,
        workflows_list: Optional[List["Workflow"]] = None,
        agents: bool = True,
        teams: bool = True,
        workflows: bool = True,
        list_limit: int = 100,
        name: str = "studio_runners",
        **kwargs: Any,
    ):
        self.registry = registry
        self.db: Optional["BaseDb"] = (
            db if db is not None else (registry.dbs[0] if registry is not None and registry.dbs else None)
        )
        self.agents_list = agents_list
        self.teams_list = teams_list
        self.workflows_list = workflows_list
        self.enable_agents = agents
        self.enable_teams = teams
        self.enable_workflows = workflows
        self.list_limit = list_limit

        tools: List[Callable] = []
        async_tools: List[tuple[Callable[..., Any], str]] = []
        if agents:
            tools.extend([self.list_agents, self.run_agent])
            async_tools.extend([(self.alist_agents, "list_agents"), (self.arun_agent, "run_agent")])
        if teams:
            tools.extend([self.list_teams, self.run_team])
            async_tools.extend([(self.alist_teams, "list_teams"), (self.arun_team, "run_team")])
        if workflows:
            tools.extend([self.list_workflows, self.run_workflow])
            async_tools.extend([(self.alist_workflows, "list_workflows"), (self.arun_workflow, "run_workflow")])

        enabled = [label for flag, label in ((agents, "agents"), (teams, "teams"), (workflows, "workflows")) if flag]
        instruction_lines: List[str] = []
        if enabled:
            list_names = "/".join(f"list_{label}" for label in enabled)
            run_names = "/".join(f"run_{label[:-1]}" for label in enabled)
            instruction_lines = [
                "Run components built in the Studio: discover what exists, then run by id.",
                f"{list_names}: id, name, and description of what exists in the platform database, newest first.",
                f"{run_names}: send one message; the result carries run_id, session_id, status, and content. "
                "Use the exact id from a list tool; a display name or its slug also resolves. An ambiguous "
                "display name returns an error listing the matching ids -- retry with the exact id.",
                "A PAUSED status means the run awaits human approval: relay the requirements to the user and "
                "include the run_id and session_id -- the run is resumed through the platform, never by "
                "running it again.",
                "Runs execute as the current user and keep one session per component per conversation, so "
                "repeat runs continue where they left off. Call a given component sequentially within a "
                "turn: parallel calls to the same component share one session and can overwrite each other.",
            ]

        # Toolkit instructions are only injected into the system message when
        # add_instructions is set, so default it on.
        kwargs.setdefault("add_instructions", True)
        super().__init__(
            name=name,
            tools=tools,
            async_tools=async_tools,
            instructions="\n".join(instruction_lines),
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Component resolution -- StudioTools delegates its lookups here so the
    # builder and the runner resolve components one way.
    # ------------------------------------------------------------------

    def _iter_agents(self) -> List["Agent"]:
        """Code-defined agents: passed-in list, else registry."""
        if self.agents_list is not None:
            return list(self.agents_list)
        return list(self.registry.agents) if self.registry is not None else []

    def _iter_teams(self) -> List["Team"]:
        """Code-defined teams: passed-in list, else registry."""
        if self.teams_list is not None:
            return list(self.teams_list)
        return list(self.registry.teams) if self.registry is not None else []

    def _iter_workflows(self) -> List["Workflow"]:
        """Code-defined workflows."""
        return list(self.workflows_list) if self.workflows_list is not None else []

    def _find_agent(self, agent_id: str) -> Optional["Agent"]:
        """Lookup order: code-defined exact id, DB exact id, code-defined display
        name, DB display name (ambiguous -> AmbiguousComponentNameError), then
        the identifier's slug as an id. Exact ids always win over names.

        Split into an exact tier and a name tier so cross-type callers
        (StudioTools._resolve_members) can try exact ids across both types
        before any name matching."""
        agent = self._find_agent_by_exact_id(agent_id)
        if agent is not None:
            return agent
        if self._db_component_exists("agent", agent_id):
            # The id names a stored component whose config is missing or broken;
            # never reinterpret an exact id as a display name.
            return None
        return self._find_agent_by_name(agent_id)

    def _find_agent_by_exact_id(self, agent_id: str) -> Optional["Agent"]:
        for a in self._iter_agents():
            if getattr(a, "id", None) == agent_id:
                return a
        return self._load_agent_from_db(agent_id)

    def _find_agent_by_name(self, agent_id: str) -> Optional["Agent"]:
        named_agents = [a for a in self._iter_agents() if getattr(a, "name", None) == agent_id]
        if len(named_agents) > 1:
            raise AmbiguousComponentNameError("agent", agent_id, [str(getattr(a, "id", "")) for a in named_agents])
        if named_agents:
            return named_agents[0]
        resolved = self._resolve_db_id_by_name_or_slug("agent", agent_id)
        return self._load_agent_from_db(resolved) if resolved is not None else None

    def _find_team(self, team_id: str) -> Optional["Team"]:
        team = self._find_team_by_exact_id(team_id)
        if team is not None:
            return team
        if self._db_component_exists("team", team_id):
            return None
        return self._find_team_by_name(team_id)

    def _find_team_by_exact_id(self, team_id: str) -> Optional["Team"]:
        for t in self._iter_teams():
            if getattr(t, "id", None) == team_id:
                return t
        return self._load_team_from_db(team_id)

    def _find_team_by_name(self, team_id: str) -> Optional["Team"]:
        named_teams = [t for t in self._iter_teams() if getattr(t, "name", None) == team_id]
        if len(named_teams) > 1:
            raise AmbiguousComponentNameError("team", team_id, [str(getattr(t, "id", "")) for t in named_teams])
        if named_teams:
            return named_teams[0]
        resolved = self._resolve_db_id_by_name_or_slug("team", team_id)
        return self._load_team_from_db(resolved) if resolved is not None else None

    def _find_workflow(self, workflow_id: str) -> Optional["Workflow"]:
        wf = self._find_workflow_by_exact_id(workflow_id)
        if wf is not None:
            return wf
        if self._db_component_exists("workflow", workflow_id):
            return None
        return self._find_workflow_by_name(workflow_id)

    def _find_workflow_by_exact_id(self, workflow_id: str) -> Optional["Workflow"]:
        for w in self._iter_workflows():
            if getattr(w, "id", None) == workflow_id:
                return w
        return self._load_workflow_from_db(workflow_id)

    def _find_workflow_by_name(self, workflow_id: str) -> Optional["Workflow"]:
        named_workflows = [w for w in self._iter_workflows() if getattr(w, "name", None) == workflow_id]
        if len(named_workflows) > 1:
            raise AmbiguousComponentNameError(
                "workflow", workflow_id, [str(getattr(w, "id", "")) for w in named_workflows]
            )
        if named_workflows:
            return named_workflows[0]
        resolved = self._resolve_db_id_by_name_or_slug("workflow", workflow_id)
        return self._load_workflow_from_db(resolved) if resolved is not None else None

    # run_* execute code-defined components on a fresh copy, so per-run
    # mutation never bleeds across callers (mirrors AgentOS's create_fresh
    # resolution). DB-loaded components are already reconstructed per call.

    def _agent_for_run(self, agent_id: str) -> Optional["Agent"]:
        agent = self._find_agent(agent_id)
        if agent is not None and any(a is agent for a in self._iter_agents()):
            copier = getattr(agent, "deep_copy", None)
            if callable(copier):
                agent = copier()
        return agent

    def _team_for_run(self, team_id: str) -> Optional["Team"]:
        team = self._find_team(team_id)
        if team is not None and any(t is team for t in self._iter_teams()):
            copier = getattr(team, "deep_copy", None)
            if callable(copier):
                team = copier()
        return team

    def _workflow_for_run(self, workflow_id: str) -> Optional["Workflow"]:
        wf = self._find_workflow(workflow_id)
        if wf is not None and any(w is wf for w in self._iter_workflows()):
            copier = getattr(wf, "deep_copy", None)
            if callable(copier):
                wf = copier()
        return wf

    def _db_component_exists(self, component_type: str, component_id: str) -> bool:
        if self.db is None:
            return False
        from agno.db.base import ComponentType

        try:
            return self.db.get_component(component_id, component_type=ComponentType(component_type)) is not None
        except NotImplementedError:
            return False

    def _resolve_db_id_by_name(self, component_type: str, name: str) -> Optional[str]:
        """Id of the DB component of this type whose display name matches exactly.

        Pages through the full components table so a match beyond the first page
        is never silently missed; only runs after the exact-id lookup missed.
        Raises AmbiguousComponentNameError when several components share the name.
        """
        if self.db is None:
            return None
        from agno.db.base import ComponentType

        matches: List[str] = []
        offset = 0
        component_type_enum = ComponentType(component_type)
        while True:
            try:
                rows, total = self.db.list_components(
                    component_type=component_type_enum, limit=_NAME_LOOKUP_PAGE, offset=offset
                )
            except NotImplementedError:
                # Not every db adapter implements component storage; degrade to
                # "no name match" so code-defined resolution still works.
                return None
            if not rows:
                break
            matches.extend(str(r["component_id"]) for r in rows if r.get("name") == name and r.get("component_id"))
            offset += len(rows)
            if offset >= total:
                break
        if len(matches) > 1:
            raise AmbiguousComponentNameError(component_type, name, matches)
        return matches[0] if matches else None

    def _resolve_db_id_by_name_or_slug(self, component_type: str, identifier: str) -> Optional[str]:
        """DB id for a non-id identifier: display name first, then its slug."""
        resolved = self._resolve_db_id_by_name(component_type, identifier)
        if resolved is not None:
            return resolved
        slug = _slugify(identifier)
        if slug != identifier and self._db_component_exists(component_type, slug):
            return slug
        return None

    def _load_agent_from_db(self, agent_id: str, version: Optional[int] = None) -> Optional["Agent"]:
        """Load an agent from DB via config + from_dict. Bypasses Agent.load() to
        avoid Agno's load_component_graph signature mismatch."""
        from agno.db.base import ComponentType

        config = self._load_config_from_db(agent_id, version=version, component_type=ComponentType.AGENT)
        if config is None:
            return None
        from agno.agent.agent import Agent

        try:
            agent = Agent.from_dict(config, registry=self.registry)
            agent.id = agent_id
            # The catalog db is a fallback only: a config-declared db (resolved
            # by from_dict, possibly with table overrides) must keep winning.
            if getattr(agent, "db", None) is None:
                agent.db = self.db
            return agent
        except Exception:
            logger.warning("StudioRunnerTools: Agent.from_dict failed for %s", agent_id, exc_info=True)
            return None

    def _load_team_from_db(self, team_id: str, version: Optional[int] = None) -> Optional["Team"]:
        from agno.db.base import ComponentType

        config = self._load_config_from_db(team_id, version=version, component_type=ComponentType.TEAM)
        if config is None:
            return None
        from agno.team.team import Team

        try:
            team = Team.from_dict(config, db=self.db, registry=self.registry)
            team.id = team_id
            # The catalog db is a fallback only; a config-declared db wins.
            if getattr(team, "db", None) is None:
                team.db = self.db
            return team
        except Exception:
            logger.warning("StudioRunnerTools: Team.from_dict failed for %s", team_id, exc_info=True)
            return None

    def _load_workflow_from_db(self, workflow_id: str, version: Optional[int] = None) -> Optional["Workflow"]:
        from agno.db.base import ComponentType

        config = self._load_config_from_db(workflow_id, version=version, component_type=ComponentType.WORKFLOW)
        if config is None:
            return None
        from agno.workflow.workflow import Workflow

        try:
            wf = Workflow.from_dict(config, db=self.db, registry=self.registry)
            wf.id = workflow_id
            # The catalog db is a fallback only; a config-declared db wins.
            if getattr(wf, "db", None) is None:
                wf.db = self.db
            return wf
        except Exception:
            logger.warning("StudioRunnerTools: Workflow.from_dict failed for %s", workflow_id, exc_info=True)
            return None

    def _load_config_from_db(
        self,
        component_id: str,
        version: Optional[int] = None,
        component_type: Optional["ComponentType"] = None,
    ) -> Optional[Dict[str, Any]]:
        """Load a component's config by id.

        When ``component_type`` is given, the stored component must be of that
        type; a mismatch returns None so that, e.g., a team id never loads as an
        Agent (mirrors the typed ``get_component`` guard used by delete_agent).
        """
        if self.db is None:
            return None
        try:
            if (
                component_type is not None
                and self.db.get_component(component_id, component_type=component_type) is None
            ):
                return None
            row = self.db.get_config(component_id=component_id, version=version)
        except NotImplementedError:
            # Not every db adapter implements component storage; treat the
            # component as absent so code-defined resolution still works.
            return None
        if row is None:
            return None
        config = row.get("config") if isinstance(row, dict) else None
        return config if isinstance(config, dict) else None

    def _list_db_component_rows(
        self, component_type: str, limit: Optional[int] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Thin DB component summaries ({id, name, description}) plus the total count."""
        if self.db is None:
            return [], 0
        from agno.db.base import ComponentType

        rows, total = self.db.list_components(
            component_type=ComponentType(component_type),
            limit=limit if limit is not None else self.list_limit,
        )
        return (
            [{"id": r.get("component_id"), "name": r.get("name"), "description": r.get("description")} for r in rows],
            total,
        )

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_agents(self) -> str:
        """List agents built in the Studio (stored in the platform database), newest first.

        Returns:
            str: JSON object with 'agents' (each {id, name, description}), 'count'
                (returned) and 'total' (in the database; total > count means the
                list is capped -- components beyond the cap still run by exact id).
        """
        return self._list_payload("agent", "agents")

    def list_teams(self) -> str:
        """List teams built in the Studio (stored in the platform database), newest first.

        Returns:
            str: JSON object with 'teams' (each {id, name, description}), 'count'
                (returned) and 'total' (in the database; total > count means the
                list is capped -- components beyond the cap still run by exact id).
        """
        return self._list_payload("team", "teams")

    def list_workflows(self) -> str:
        """List workflows built in the Studio (stored in the platform database), newest first.

        Returns:
            str: JSON object with 'workflows' (each {id, name, description}), 'count'
                (returned) and 'total' (in the database; total > count means the
                list is capped -- components beyond the cap still run by exact id).
        """
        return self._list_payload("workflow", "workflows")

    def _list_payload(self, component_type: str, key: str) -> str:
        if self.db is None:
            return json.dumps({"error": "StudioRunnerTools has no db configured; cannot list components."})
        try:
            items, total = self._list_db_component_rows(component_type)
            return json.dumps({key: items, "count": len(items), "total": total})
        except Exception as e:
            logger.exception("Failed to list %s", key)
            return json.dumps({"error": str(e)})

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run_agent(self, agent_id: str, message: str, _agno_run_context: Optional[RunContext] = None) -> str:
        """Run an agent and return its result.

        The run executes as the current user and continues that user's
        per-conversation session with this agent. A PAUSED status means the run
        awaits human approval: the result carries the unresolved requirements
        plus the run_id and session_id a continue call must address.

        Args:
            agent_id (str): Id of the agent to run (a display name or its slug also resolves).
            message (str): The message to send.

        Returns:
            str: JSON object with 'agent_id', 'run_id', 'session_id', 'status',
                'content' and, when paused, 'requirements'.
        """
        try:
            agent = self._agent_for_run(agent_id)
        except AmbiguousComponentNameError as e:
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("Failed to resolve agent")
            return json.dumps({"error": f"Failed to resolve agent '{agent_id}': {str(e) or type(e).__name__}"})
        if agent is None:
            return json.dumps({"error": f"Agent not found: {agent_id}"})
        component_id = getattr(agent, "id", None) or agent_id
        try:
            response = agent.run(
                message,
                stream=False,
                user_id=_agno_run_context.user_id if _agno_run_context is not None else None,
                session_id=self._sub_session_id(_agno_run_context, "agent", component_id),
            )
            return self._run_payload("agent_id", component_id, response)
        except Exception as e:
            logger.exception("Failed to run agent")
            return json.dumps({"error": str(e)})

    def run_team(self, team_id: str, message: str, _agno_run_context: Optional[RunContext] = None) -> str:
        """Run a team and return its result.

        The run executes as the current user and continues that user's
        per-conversation session with this team. A PAUSED status means the run
        awaits human approval: the result carries the unresolved requirements
        plus the run_id and session_id a continue call must address.

        Args:
            team_id (str): Id of the team to run (a display name or its slug also resolves).
            message (str): The message to send.

        Returns:
            str: JSON object with 'team_id', 'run_id', 'session_id', 'status',
                'content' and, when paused, 'requirements'.
        """
        try:
            team = self._team_for_run(team_id)
        except AmbiguousComponentNameError as e:
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("Failed to resolve team")
            return json.dumps({"error": f"Failed to resolve team '{team_id}': {str(e) or type(e).__name__}"})
        if team is None:
            return json.dumps({"error": f"Team not found: {team_id}"})
        component_id = getattr(team, "id", None) or team_id
        try:
            response = team.run(
                message,
                stream=False,
                user_id=_agno_run_context.user_id if _agno_run_context is not None else None,
                session_id=self._sub_session_id(_agno_run_context, "team", component_id),
            )
            return self._run_payload("team_id", component_id, response)
        except Exception as e:
            logger.exception("Failed to run team")
            return json.dumps({"error": str(e)})

    def run_workflow(self, workflow_id: str, message: str, _agno_run_context: Optional[RunContext] = None) -> str:
        """Run a workflow and return its final result.

        The run executes as the current user and continues that user's
        per-conversation session with this workflow. A PAUSED status means the
        run awaits human approval: the result carries the unresolved
        requirements plus the run_id and session_id a continue call must address.

        Args:
            workflow_id (str): Id of the workflow to run (a display name or its slug also resolves).
            message (str): Input to pass to the first step.

        Returns:
            str: JSON object with 'workflow_id', 'run_id', 'session_id', 'status',
                'content' and, when paused, 'requirements'.
        """
        try:
            wf = self._workflow_for_run(workflow_id)
        except AmbiguousComponentNameError as e:
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("Failed to resolve workflow")
            return json.dumps({"error": f"Failed to resolve workflow '{workflow_id}': {str(e) or type(e).__name__}"})
        if wf is None:
            return json.dumps({"error": f"Workflow not found: {workflow_id}"})
        component_id = getattr(wf, "id", None) or workflow_id
        try:
            response = wf.run(
                input=message,
                stream=False,
                user_id=_agno_run_context.user_id if _agno_run_context is not None else None,
                session_id=self._sub_session_id(_agno_run_context, "workflow", component_id),
            )
            return self._run_payload("workflow_id", component_id, response)
        except Exception as e:
            logger.exception("Failed to run workflow")
            return json.dumps({"error": str(e)})

    async def arun_agent(self, agent_id: str, message: str, _agno_run_context: Optional[RunContext] = None) -> str:
        """Async variant of run_agent.

        Args:
            agent_id (str): Id of the agent to run (a display name or its slug also resolves).
            message (str): The message to send.
        """
        # Resolution hits the DB synchronously; keep it off the event loop.
        try:
            agent = await asyncio.to_thread(self._agent_for_run, agent_id)
        except AmbiguousComponentNameError as e:
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("Failed to resolve agent")
            return json.dumps({"error": f"Failed to resolve agent '{agent_id}': {str(e) or type(e).__name__}"})
        if agent is None:
            return json.dumps({"error": f"Agent not found: {agent_id}"})
        component_id = getattr(agent, "id", None) or agent_id
        try:
            response = await agent.arun(
                message,
                stream=False,
                user_id=_agno_run_context.user_id if _agno_run_context is not None else None,
                session_id=self._sub_session_id(_agno_run_context, "agent", component_id),
            )
            return self._run_payload("agent_id", component_id, response)
        except Exception as e:
            logger.exception("Failed to run agent")
            return json.dumps({"error": str(e)})

    async def arun_team(self, team_id: str, message: str, _agno_run_context: Optional[RunContext] = None) -> str:
        """Async variant of run_team.

        Args:
            team_id (str): Id of the team to run (a display name or its slug also resolves).
            message (str): The message to send.
        """
        try:
            team = await asyncio.to_thread(self._team_for_run, team_id)
        except AmbiguousComponentNameError as e:
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("Failed to resolve team")
            return json.dumps({"error": f"Failed to resolve team '{team_id}': {str(e) or type(e).__name__}"})
        if team is None:
            return json.dumps({"error": f"Team not found: {team_id}"})
        component_id = getattr(team, "id", None) or team_id
        try:
            response = await team.arun(
                message,
                stream=False,
                user_id=_agno_run_context.user_id if _agno_run_context is not None else None,
                session_id=self._sub_session_id(_agno_run_context, "team", component_id),
            )
            return self._run_payload("team_id", component_id, response)
        except Exception as e:
            logger.exception("Failed to run team")
            return json.dumps({"error": str(e)})

    async def arun_workflow(
        self, workflow_id: str, message: str, _agno_run_context: Optional[RunContext] = None
    ) -> str:
        """Async variant of run_workflow.

        Args:
            workflow_id (str): Id of the workflow to run (a display name or its slug also resolves).
            message (str): Input to pass to the first step.
        """
        try:
            wf = await asyncio.to_thread(self._workflow_for_run, workflow_id)
        except AmbiguousComponentNameError as e:
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("Failed to resolve workflow")
            return json.dumps({"error": f"Failed to resolve workflow '{workflow_id}': {str(e) or type(e).__name__}"})
        if wf is None:
            return json.dumps({"error": f"Workflow not found: {workflow_id}"})
        component_id = getattr(wf, "id", None) or workflow_id
        try:
            response = await wf.arun(
                input=message,
                stream=False,
                user_id=_agno_run_context.user_id if _agno_run_context is not None else None,
                session_id=self._sub_session_id(_agno_run_context, "workflow", component_id),
            )
            return self._run_payload("workflow_id", component_id, response)
        except Exception as e:
            logger.exception("Failed to run workflow")
            return json.dumps({"error": str(e)})

    async def alist_agents(self) -> str:
        """Async variant of list_agents."""
        return await asyncio.to_thread(self.list_agents)

    async def alist_teams(self) -> str:
        """Async variant of list_teams."""
        return await asyncio.to_thread(self.list_teams)

    async def alist_workflows(self) -> str:
        """Async variant of list_workflows."""
        return await asyncio.to_thread(self.list_workflows)

    # ------------------------------------------------------------------
    # Result shaping
    # ------------------------------------------------------------------

    @staticmethod
    def _sub_session_id(run_context: Optional[RunContext], component_type: str, component_id: str) -> Optional[str]:
        """One session per component per calling conversation: repeat runs from the
        same caller session continue, different conversations stay separate.

        The component type is part of the key: session ids are globally unique
        while ids are only unique per type, so an agent and a team sharing an id
        must not share a session row."""
        if run_context is None or not getattr(run_context, "session_id", None):
            return None
        return f"{run_context.session_id}--{component_type}--{component_id}"

    @staticmethod
    def _run_payload(id_key: str, component_id: str, run_output: Any) -> str:
        content = getattr(run_output, "content", None)
        # Structured (output_schema) content must reach the caller as JSON, not
        # a pydantic repr; get_content_as_string is the same shaping the MCP
        # plane uses. A serialization failure falls back to the raw content so
        # a completed run never turns into an error result.
        if content is not None and not isinstance(content, str) and hasattr(run_output, "get_content_as_string"):
            try:
                content = run_output.get_content_as_string()
            except Exception:
                logger.warning("StudioRunnerTools: get_content_as_string failed; returning raw content", exc_info=True)
        payload: Dict[str, Any] = {
            id_key: component_id,
            "run_id": getattr(run_output, "run_id", None),
            "session_id": getattr(run_output, "session_id", None),
            "status": _run_status(run_output),
            "content": content,
        }
        requirements = _paused_requirements(run_output)
        if requirements is not None:
            payload["requirements"] = requirements
        # Media artifacts cannot travel in a JSON tool result; count them so the
        # caller knows they exist (retrievable from the run via the platform).
        media = {
            kind: len(artifacts)
            for kind in ("images", "videos", "audio")
            if (artifacts := getattr(run_output, kind, None))
        }
        if media:
            payload["media"] = media
        return json.dumps(payload, default=str)
