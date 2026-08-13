"""StudioRunnerTools -- discovery and execution over Studio-built components.

The runner is the dispatch half of the Studio: list the agents, teams, and
workflows this runner can run -- those in the platform database, plus any
code-defined components it admits -- and run one by id. It carries no
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

Mount it INSTEAD of StudioTools, not beside it. StudioTools embeds this same
toolkit and already exposes list_agents/list_teams/list_workflows/run_agent,
plus run_team and run_workflow once teams or workflows are enabled (an explicit
agents_list enables both), and agno's tool namespace is flat: co-mounting
collapses the overlapping names to
whichever toolkit the tools list holds first, and a warning names the skipped
one. Two runners scoped to different component lists collapse the same way, so
the loser's allowlist becomes unreachable. ``name=`` names the toolkit, not its
functions, so it does not disambiguate them.

Semantics:
    * Everything runnable is discoverable: list_* report the components in the
      platform database plus the code-defined ones this runner admits, and a
      display name never reaches a stored component whose id a code-defined
      one holds -- one id means one component, however it was spelled.
    * Runs execute as the current user: the wielding component's run_context is
      injected and its user_id passed through, so per-user state (memory,
      learning) lands on the human who asked, never on a service default.
    * Each target keeps one session per calling conversation: the session id
      is a digest keyed on the caller's session id, the component type and
      the component id (see _sub_session_id), so repeat runs continue their
      context instead of starting cold. A caller with no session of its own
      (a direct Python call) passes no session id -- and because dispatch
      runs on a per-call copy or rebuild, each such run starts a session of
      its own. Construct the component with an explicit session_id to keep
      continuity across sessionless calls.
    * Code-defined components are dispatched on a fresh deep copy per run, so
      per-run mutation of a shared instance never bleeds across callers.
      DB-loaded components are reconstructed per call already. Two things sit
      outside that copy, both by the framework's own rules:
        - what a callable members/tools/steps factory returns, since it is
          built per run and cached while cache_callables is on. Dispatch warns
          when it meets one.
        - a tool whose ``__deepcopy__`` returns self or raises. An ordinary
          toolkit is deep-copied like any other object and is NOT shared; it is
          only these two that the field-level fallback keeps by reference, so a
          toolkit holding per-call state that way is shared between callers.
          Returning self is a deliberate choice; raising is not, and that half
          is a swallowed failure (#9445).
    * A PAUSED result carries the unresolved requirements plus the
      run_id/session_id a continue call must address (the same shape the
      AgentOS MCP plane returns) -- human-in-the-loop pauses are relayed.
    * Runs are dispatched with stream=False pinned: run-option resolution is
      call-site > component.stream > False, so a component saved with
      stream=True still hands back its final run output, never an unconsumed
      event iterator.
    * run_* resolve in a fixed order: code-defined exact id, DB exact id,
      code-defined display name, DB display name, then the identifier's slug
      as an id (covers renamed components, whose ids keep the original
      name's slug). Exact ids always win over display names. A display name
      matching several components of the type returns an error listing the
      matching ids.
    * Persisted components rebuild from their stored config. Registry-backed
      references (tools, knowledge, function steps, schemas, code-defined
      members) require the registry: without it the runner refuses to run a
      silently degraded component. A registry that is present but does not
      hold a referenced piece is refused the same way -- the rebuilt component
      is checked against its own config before dispatch, so an unresolved tool
      or a dropped schema stops the run rather than quietly changing what it
      does. Reads and edits load it either way, so it stays repairable.
      Member references resolve at their current
      published version. Model connection settings, credentials and a
      declared db are not fully persisted, so a rebuild can fall back to
      provider defaults and to the catalog db; the runner logs a warning for
      the dispatched agent's or team's own model and for a dropped db.
    * list_* read the database only (id, name, description, newest first), and
      run_* dispatch that same set: a component you cannot list is a component
      you cannot run. Code-defined components arrive through the registry,
      which is passed so persisted components can rehydrate rather than to
      grant the runner the run of the application, so dispatching them is
      opt-in via include_all_components. An explicit agents_list/teams_list/
      workflows_list is itself the allowlist and always runs. 'total' reports
      the full DB count, so a capped list is visible as capped.

StudioTools embeds this toolkit for its own run_* tools and delegates its
component lookups here, so a builder's smoke-test runs and a dispatcher's
production runs share one implementation.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from agno.exceptions import ComponentPinError, ComponentRehydrationError
from agno.run import RunContext
from agno.run.utils import run_status_string, serialized_paused_requirements
from agno.tools.toolkit import Toolkit
from agno.utils.log import logger
from agno.utils.string import generate_component_id_from_name

if TYPE_CHECKING:
    from agno.agent.agent import Agent
    from agno.db.base import BaseDb, ComponentType
    from agno.registry.registry import Registry
    from agno.team.team import Team
    from agno.workflow.workflow import Workflow

# Page size for the display-name fallback lookup, which scans the components
# table when an identifier is not an exact id.
_NAME_LOOKUP_PAGE = 100


# How deep the dispatch checks walk a component graph. A graph deeper than this
# is refused rather than half-inspected, so a cap can never read as a pass.
_GRAPH_DEPTH_CAP = 32


def _slugify(name: str) -> str:
    """Component ids are slugified names (shared with StudioTools' create path)."""
    return generate_component_id_from_name(name)


class StudioRunnerError(Exception):
    """Base class for the runner's deliberate refusals.

    Each carries an actionable message meant for the caller (model or code)
    rather than the log, so the tools catch this one name."""


class AmbiguousComponentNameError(StudioRunnerError, ValueError):
    """A display name matched more than one component of the requested type.

    The message lists the matching ids so the caller (model or code) can retry
    with an exact id.
    """

    def __init__(self, component_type: str, name: str, matches: List[str]):
        self.matches = sorted(matches)
        super().__init__(
            f"Ambiguous {component_type} name: '{name}' matches ids {', '.join(self.matches)}. Use the exact id."
        )


class ComponentNeedsRegistryError(StudioRunnerError, RuntimeError):
    """The stored config references registry-backed pieces that cannot be
    reconstructed without the registry.

    The runner refuses to dispatch the degraded rebuild (tools dropped,
    knowledge and function steps missing, code-defined members lost)."""


class ComponentNotDispatchableError(StudioRunnerError, RuntimeError):
    """The identifier names a component this runner may read but not run.

    Code-defined components reach the runner through the registry, which is
    passed so persisted components can rehydrate. Running them is opt-in
    (``include_all_components``)."""


class DispatchCopyError(StudioRunnerError, RuntimeError):
    """A component could not be copied faithfully for dispatch.

    The runner refuses a copy that fails its fidelity checks (see
    StudioRunnerTools._fresh_copy for what is checked) rather than dispatch a
    component that differs from the one asked for. Give the component class a
    deep_copy that rebuilds it, or store the component in the database."""


def _reference_configs(component_type: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The dicts in a stored config that can name another component.

    A team names its members; a workflow names each step's executor, and a
    compound step holds its branches in lists of its own. Everything else a
    step carries is the caller's own data -- a human-review input schema, say
    -- so a walk that descended into every value would read a field named
    ``agent_id`` there as a reference to a component that does not exist."""
    found: List[Dict[str, Any]] = []
    if component_type == "team":
        found.extend(member for member in config.get("members") or [] if isinstance(member, dict))
        return found
    if component_type != "workflow":
        return found

    def walk(steps: Any) -> None:
        if not isinstance(steps, list):
            return
        for step in steps:
            if not isinstance(step, dict):
                continue
            found.append(step)
            for branch in ("steps", "else_steps", "choices"):
                walk(step.get(branch))

    walk(config.get("steps"))
    return found


def _references_executors(component_type: str, config: Dict[str, Any]) -> bool:
    """True when a stored workflow config references a registry function step."""
    return any(step.get("executor_ref") for step in _reference_configs(component_type, config))


def _references_idless_components(component_type: str, config: Dict[str, Any]) -> bool:
    """True when a stored config carries an agent/team reference whose id is
    null. Serialization writes the referenced component's id even when it is
    None, and a code-defined component that never ran has no id, so a null id
    marks a component only the registry can supply."""
    return any(
        ("agent_id" in ref and not ref["agent_id"]) or ("team_id" in ref and not ref["team_id"])
        for ref in _reference_configs(component_type, config)
    )


def _component_references(component_type: str, config: Dict[str, Any]) -> List[tuple]:
    """(type, id) pairs for the components a stored config references by id."""
    refs: List[tuple] = []
    for ref in _reference_configs(component_type, config):
        if ref.get("team_id"):
            refs.append(("team", str(ref["team_id"])))
        elif ref.get("agent_id"):
            refs.append(("agent", str(ref["agent_id"])))
    return refs


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
        include_all_components: bool = False,
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
        self.include_all_components = include_all_components
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
                f"{list_names}: id, name, and description of every component this toolkit can run, newest first.",
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

    def _iter_agents(self, for_dispatch: bool = False) -> List["Agent"]:
        """Code-defined agents: passed-in list, else registry.

        The registry half is opt-in for dispatch (``include_all_components``).
        A registry is passed so persisted components can rehydrate their tools
        and members, which is not the same as consenting to run every agent the
        application happens to define. An explicit ``agents_list`` is itself the
        allowlist and always runs. ``list_*`` report exactly this admitted set
        alongside the database, so what can be run can be found.
        Lookups that are not dispatch (get, edit, members, steps) see the full
        set either way."""
        if self.agents_list is not None:
            return list(self.agents_list)
        if for_dispatch and not self.include_all_components:
            return []
        return list(self.registry.agents) if self.registry is not None else []

    def _iter_teams(self, for_dispatch: bool = False) -> List["Team"]:
        """Code-defined teams: passed-in list, else registry (see _iter_agents)."""
        if self.teams_list is not None:
            return list(self.teams_list)
        if for_dispatch and not self.include_all_components:
            return []
        return list(self.registry.teams) if self.registry is not None else []

    def _iter_workflows(self, for_dispatch: bool = False) -> List["Workflow"]:
        """Code-defined workflows. Always an explicit list, so never gated."""
        return list(self.workflows_list) if self.workflows_list is not None else []

    def _find_agent(self, agent_id: str, for_dispatch: bool = False) -> Optional["Agent"]:
        """Lookup order: code-defined exact id, DB exact id, code-defined display
        name, DB display name (ambiguous -> AmbiguousComponentNameError), then
        the identifier's slug as an id. Exact ids always win over names.

        Split into an exact tier and a name tier so cross-type callers
        (StudioTools._resolve_members) can try exact ids across both types
        before any name matching."""
        agent = self._find_agent_by_exact_id(agent_id, for_dispatch=for_dispatch)
        if agent is not None:
            return agent
        if self._db_component_exists("agent", agent_id):
            # The id names a stored component whose config is missing or broken;
            # never reinterpret an exact id as a display name.
            return None
        return self._find_agent_by_name(agent_id, for_dispatch=for_dispatch)

    def _find_agent_by_exact_id(self, agent_id: str, for_dispatch: bool = False) -> Optional["Agent"]:
        for a in self._iter_agents(for_dispatch=for_dispatch):
            if getattr(a, "id", None) == agent_id:
                return a
        return self._load_agent_from_db(agent_id, for_dispatch=for_dispatch)

    def _find_agent_by_name(self, agent_id: str, for_dispatch: bool = False) -> Optional["Agent"]:
        named_agents = [a for a in self._iter_agents(for_dispatch=for_dispatch) if getattr(a, "name", None) == agent_id]
        if len(named_agents) > 1:
            raise AmbiguousComponentNameError("agent", agent_id, [str(getattr(a, "id", "")) for a in named_agents])
        if named_agents:
            return named_agents[0]
        resolved = self._resolve_db_id_by_name_or_slug("agent", agent_id)
        if resolved is None:
            return None
        if for_dispatch:
            self._refuse_if_shadowed("agent", resolved, agent_id)
        return self._load_agent_from_db(resolved, for_dispatch=for_dispatch)

    def _find_team(self, team_id: str, for_dispatch: bool = False) -> Optional["Team"]:
        team = self._find_team_by_exact_id(team_id, for_dispatch=for_dispatch)
        if team is not None:
            return team
        if self._db_component_exists("team", team_id):
            return None
        return self._find_team_by_name(team_id, for_dispatch=for_dispatch)

    def _find_team_by_exact_id(self, team_id: str, for_dispatch: bool = False) -> Optional["Team"]:
        for t in self._iter_teams(for_dispatch=for_dispatch):
            if getattr(t, "id", None) == team_id:
                return t
        return self._load_team_from_db(team_id, for_dispatch=for_dispatch)

    def _find_team_by_name(self, team_id: str, for_dispatch: bool = False) -> Optional["Team"]:
        named_teams = [t for t in self._iter_teams(for_dispatch=for_dispatch) if getattr(t, "name", None) == team_id]
        if len(named_teams) > 1:
            raise AmbiguousComponentNameError("team", team_id, [str(getattr(t, "id", "")) for t in named_teams])
        if named_teams:
            return named_teams[0]
        resolved = self._resolve_db_id_by_name_or_slug("team", team_id)
        if resolved is None:
            return None
        if for_dispatch:
            self._refuse_if_shadowed("team", resolved, team_id)
        return self._load_team_from_db(resolved, for_dispatch=for_dispatch)

    def _find_workflow(self, workflow_id: str, for_dispatch: bool = False) -> Optional["Workflow"]:
        wf = self._find_workflow_by_exact_id(workflow_id, for_dispatch=for_dispatch)
        if wf is not None:
            return wf
        if self._db_component_exists("workflow", workflow_id):
            return None
        return self._find_workflow_by_name(workflow_id, for_dispatch=for_dispatch)

    def _find_workflow_by_exact_id(self, workflow_id: str, for_dispatch: bool = False) -> Optional["Workflow"]:
        for w in self._iter_workflows(for_dispatch=for_dispatch):
            if getattr(w, "id", None) == workflow_id:
                return w
        return self._load_workflow_from_db(workflow_id, for_dispatch=for_dispatch)

    def _find_workflow_by_name(self, workflow_id: str, for_dispatch: bool = False) -> Optional["Workflow"]:
        named_workflows = [
            w for w in self._iter_workflows(for_dispatch=for_dispatch) if getattr(w, "name", None) == workflow_id
        ]
        if len(named_workflows) > 1:
            raise AmbiguousComponentNameError(
                "workflow", workflow_id, [str(getattr(w, "id", "")) for w in named_workflows]
            )
        if named_workflows:
            return named_workflows[0]
        resolved = self._resolve_db_id_by_name_or_slug("workflow", workflow_id)
        if resolved is None:
            return None
        if for_dispatch:
            self._refuse_if_shadowed("workflow", resolved, workflow_id)
        return self._load_workflow_from_db(resolved, for_dispatch=for_dispatch)

    # run_* execute code-defined components on a fresh copy, so per-run
    # mutation never bleeds across callers. DB-loaded components are
    # reconstructed per call already.

    @staticmethod
    def _fresh_copy(component: Any) -> Any:
        """A checked deep copy for dispatch. Raises DispatchCopyError on a
        copy that is unavailable, raised, or fails a fidelity check.

        deep_copy rebuilds via the component class's __init__ signature, so a
        subclass with a ``(custom, **kwargs)`` initializer can come back blank
        or fail to rebuild entirely, and the field-level copier keeps the
        original value for a field whose own copy raised. The copy is
        dispatched when it is a distinct instance of the same class that kept
        its id, name, model and instructions, and whose copyable members were
        themselves copied (see _shared_member)."""
        label = getattr(component, "id", None) or getattr(component, "name", None) or component.__class__.__name__
        copier = getattr(component, "deep_copy", None)
        if not callable(copier):
            raise DispatchCopyError(
                f"'{label}' has no deep_copy; the runner does not dispatch a shared instance. "
                "Give the class a deep_copy method, or store the component in the database."
            )
        try:
            fresh = copier()
        except Exception as e:
            raise DispatchCopyError(
                f"deep_copy failed for '{label}': {str(e) or type(e).__name__}. "
                "Give the class a deep_copy that rebuilds it, or store the component in the database."
            ) from e
        if fresh is component:
            raise DispatchCopyError(
                f"deep_copy of '{label}' returned the shared instance; the runner does not dispatch it. "
                "Give the class a deep_copy that rebuilds a new instance, or store the component in the database."
            )
        if StudioRunnerTools._copy_lost_identity(component, fresh):
            raise DispatchCopyError(
                f"deep_copy of '{label}' lost its identity. "
                "Give the class a deep_copy that rebuilds it, or store the component in the database."
            )
        step_divergence = StudioRunnerTools._executor_divergence(component, fresh)
        if step_divergence is not None:
            raise DispatchCopyError(
                f"deep_copy of '{label}' did not isolate its steps: {step_divergence}. "
                "Give that executor's class a deep_copy that rebuilds it, or store the component in the database."
            )
        shared = StudioRunnerTools._shared_member(component, fresh)
        if shared is not None:
            shared_label = getattr(shared, "id", None) or getattr(shared, "name", None) or type(shared).__name__
            raise DispatchCopyError(
                f"deep_copy of '{label}' still shares member '{shared_label}' with the original. "
                "Give that member's class a deep_copy that rebuilds it, or store the component in the database."
            )
        divergence = StudioRunnerTools._member_divergence(component, fresh)
        if divergence is not None:
            raise DispatchCopyError(
                f"deep_copy of '{label}' did not reproduce its members: {divergence}. "
                "Give the class a deep_copy that rebuilds it, or store the component in the database."
            )
        return fresh

    @staticmethod
    def _child_nodes(node: Any) -> List[Any]:
        """Everything directly below a component or a step that can hold tools.

        A step reached through a compound step's branch list is a step, not an
        executor, so a walk that only unwraps executors one level below a
        component never reaches it. Taking the executor off whatever node the
        walk is standing on makes every depth alike. members=, steps= and
        tools= also accept callable factories, and only a materialized list can
        be walked."""
        children: List[Any] = []
        members = getattr(node, "members", None)
        if isinstance(members, list):
            children.extend(members)
        for attribute in ("agent", "team", "workflow"):
            executor = getattr(node, attribute, None)
            if executor is not None:
                children.append(executor)
        for attribute in ("steps", "else_steps", "choices"):
            children.extend(StudioRunnerTools._branch_items(getattr(node, attribute, None)))
        return children

    @staticmethod
    def _component_kind(node: Any) -> str:
        """Which of the three component types this object is.

        Ids are unique per type only, so every map from an id to a component
        has to carry the type alongside it."""
        from agno.team.team import Team
        from agno.workflow.workflow import Workflow

        if isinstance(node, Team):
            return "team"
        return "workflow" if isinstance(node, Workflow) else "agent"

    @staticmethod
    def _tool_names(component: Any) -> set:
        """The tool names a component can reach, however its tools are held.

        The same tools serialize as a toolkit in one place and as its expanded
        functions in another, so comparing the objects would call a healthy
        copy degraded. Comparing what it can call does not."""
        names: set = set()
        tools = getattr(component, "tools", None)
        for tool in tools if isinstance(tools, list) else []:
            functions = getattr(tool, "functions", None)
            if isinstance(functions, dict) and functions:
                names.update(str(name) for name in functions)
                continue
            name = tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", None)
            if isinstance(name, str):
                names.add(name)
        return names

    @staticmethod
    def _copy_lost_identity(original: Any, fresh: Any) -> bool:
        """Whether a copy failed to carry over what identifies the original.

        Identity is the class, the id and the name -- and the behaviour the
        caller asked for: which model answers, under which instructions, with
        which tools in reach. A copy that swapped any of those runs as a
        different component under the right name, which is the failure the
        caller cannot see."""
        if type(fresh) is not type(original):
            return True
        for attribute in ("id", "name"):
            if getattr(original, attribute, None) != getattr(fresh, attribute, None):
                return True
        for attribute in ("model", "instructions"):
            was = getattr(original, attribute, None)
            if was is not None and getattr(fresh, attribute, None) is None:
                return True
        was_model, now_model = getattr(original, "model", None), getattr(fresh, "model", None)
        if was_model is not None and now_model is not None:
            # A copier legitimately rebuilds the model object, so compare which
            # model it is rather than which instance -- but the class as well as
            # the id, since two providers share an id readily and answering from
            # the other one is a different pipeline under the same name.
            # Connection settings are deliberately NOT compared here: they are
            # never serialized, so a rebuild always lacks them, and refusing on
            # that would refuse every DB-loaded component (tracked in #9420).
            if type(was_model) is not type(now_model):
                return True
            if getattr(was_model, "id", None) != getattr(now_model, "id", None):
                return True
        was_instructions = getattr(original, "instructions", None)
        if was_instructions is not None and was_instructions != getattr(fresh, "instructions", None):
            return True
        return bool(StudioRunnerTools._tool_names(original) - StudioRunnerTools._tool_names(fresh))

    @staticmethod
    def _executor_divergence(original: Any, fresh: Any, depth: int = 0) -> Optional[str]:
        """How the copy's step executors differ from the original's, else None.

        _shared_member and _member_divergence walk ``members``, and a workflow
        holds ``steps``, so neither reaches a step executor. An executor the
        copy still shares is the original instance, and per-run mutation of it
        crosses callers; one that came back blank runs as a different
        component. Compound steps hold their branches in lists of their own,
        so the walk descends through them too."""
        return StudioRunnerTools._step_list_divergence(
            getattr(original, "steps", None), getattr(fresh, "steps", None), depth
        )

    @staticmethod
    def _branch_items(value: Any) -> List[Any]:
        """A step container's children, whether it holds a list or a single step.

        ``steps=`` takes a list, one compound step (``Steps(...)``), or a
        callable factory. A factory is not materialized here, so it contributes
        nothing, the way every other walk in this file treats one."""
        if isinstance(value, list):
            return value
        if value is None or callable(value):
            return []
        return [value]

    @staticmethod
    def _is_executor(node: Any) -> bool:
        """Whether this object runs work itself rather than wrapping one that does."""
        from agno.agent.agent import Agent
        from agno.team.team import Team
        from agno.workflow.workflow import Workflow

        return isinstance(node, (Agent, Team, Workflow))

    @staticmethod
    def _executor_problem(was: Any, now: Any, where: str, depth: int) -> Optional[str]:
        """How a copied executor fails to stand in for the original, else None."""
        if now is was:
            # An executor without deep_copy is shared by design, the rule
            # _shared_member applies to a member.
            return f"{where} is still shared" if callable(getattr(was, "deep_copy", None)) else None
        if StudioRunnerTools._copy_lost_identity(was, now):
            return f"{where} lost its identity"
        shared = StudioRunnerTools._shared_member(was, now)
        if shared is not None:
            shared_label = getattr(shared, "id", None) or getattr(shared, "name", None) or "?"
            return f"{where} still shares member '{shared_label}'"
        divergence = StudioRunnerTools._member_divergence(was, now, depth + 1)
        if divergence is not None:
            return f"{where}: {divergence}"
        nested = StudioRunnerTools._executor_divergence(was, now, depth + 1)
        return f"{where}: {nested}" if nested is not None else None

    @staticmethod
    def _step_list_divergence(original_steps: Any, fresh_steps: Any, depth: int = 0) -> Optional[str]:
        if depth > _GRAPH_DEPTH_CAP:
            # _require_inspectable_depth refuses before a real graph gets here,
            # so this is only the cycle guard.
            return None
        original_items = StudioRunnerTools._branch_items(original_steps)
        if not original_items:
            # Nothing declared, so nothing to lose. An empty branch list is a
            # normal shape (Condition(else_steps=[])), not a dropped one.
            return None
        fresh_items = StudioRunnerTools._branch_items(fresh_steps)
        if len(fresh_items) != len(original_items):
            return f"step count changed ({len(original_items)} -> {len(fresh_items)})"
        for original_step, fresh_step in zip(original_items, fresh_items):
            label = getattr(original_step, "name", None) or getattr(original_step, "id", None) or "?"
            # A workflow takes a bare agent, team or workflow as a step, so the
            # item itself can be the executor rather than a wrapper holding one.
            if StudioRunnerTools._is_executor(original_step):
                problem = StudioRunnerTools._executor_problem(original_step, fresh_step, f"step '{label}'", depth)
                if problem is not None:
                    return problem
            for attribute in ("agent", "team", "workflow"):
                was = getattr(original_step, attribute, None)
                if was is None:
                    continue
                problem = StudioRunnerTools._executor_problem(
                    was, getattr(fresh_step, attribute, None), f"step '{label}' {attribute}", depth
                )
                if problem is not None:
                    return problem
            for child_attribute in ("steps", "else_steps", "choices"):
                nested = StudioRunnerTools._step_list_divergence(
                    getattr(original_step, child_attribute, None),
                    getattr(fresh_step, child_attribute, None),
                    depth + 1,
                )
                if nested is not None:
                    return nested
        return None

    @staticmethod
    def _member_divergence(original: Any, fresh: Any, depth: int = 0) -> Optional[str]:
        """How the copy's member list differs in shape from the original's, else None.

        Whether a member is aliased is _shared_member's question; this one is
        whether the copy holds the same members at all. A copier that drops a
        member or rebuilds it as a different component has not produced the
        component that was asked for, and neither shows up as sharing."""
        if depth > _GRAPH_DEPTH_CAP:
            # _require_inspectable_depth refuses before a real graph gets
            # here, so this is only the cycle guard.
            return None
        original_members = getattr(original, "members", None)
        if not isinstance(original_members, list):
            return None
        fresh_members = getattr(fresh, "members", None)
        if not isinstance(fresh_members, list) or len(fresh_members) != len(original_members):
            found = len(fresh_members) if isinstance(fresh_members, list) else "none"
            return f"member count changed ({len(original_members)} -> {found})"
        for original_member, fresh_member in zip(original_members, fresh_members):
            if fresh_member is original_member:
                # Shared by design, or already reported by _shared_member.
                continue
            member_label = getattr(original_member, "id", None) or getattr(original_member, "name", None) or "?"
            if type(fresh_member) is not type(original_member):
                return f"member '{member_label}' came back as {type(fresh_member).__name__}"
            # The same rule a step executor is held to: a member that came back
            # answering from another model, under other instructions, or without
            # the tools it had is a different member under the right name.
            if StudioRunnerTools._copy_lost_identity(original_member, fresh_member):
                return f"member '{member_label}' lost its identity"
            nested = StudioRunnerTools._member_divergence(original_member, fresh_member, depth + 1)
            if nested is not None:
                return nested
        return None

    @staticmethod
    def _shared_member(original: Any, fresh: Any) -> Optional[Any]:
        """The first copyable member the copy still shares with the original,
        searched through nested member lists, else None.

        A member without deep_copy is shared by design: a remote proxy holds no
        per-run state to isolate. A member that could have been copied and was
        not is a failed copy, and dispatching it would let per-run mutation
        cross callers."""
        original_members = getattr(original, "members", None)
        fresh_members = getattr(fresh, "members", None)
        if not isinstance(original_members, list) or not isinstance(fresh_members, list):
            return None
        if len(original_members) != len(fresh_members):
            return None
        for original_member, fresh_member in zip(original_members, fresh_members):
            if fresh_member is original_member and callable(getattr(original_member, "deep_copy", None)):
                return fresh_member
            nested = StudioRunnerTools._shared_member(original_member, fresh_member)
            if nested is not None:
                return nested
        return None

    def _refuse_if_shadowed(self, component_type: str, resolved_id: str, requested: str) -> None:
        """Refuse a name that resolves to a stored component a code one shadows.

        An exact id resolves to the code-defined component, and the listing
        shows only that one, so letting the display name reach the stored
        component behind it makes the same id mean two things depending on how
        it was spelled -- and runs something that was never discoverable.
        Refusing says which id is taken; substituting would answer a different
        question than the caller asked.

        Dispatch only, so a name that is not itself taken still reads and edits
        the stored component -- which is how the id gets changed. When the code
        component took the display name as well, the stored one is not
        reachable through this toolkit at all and the collision has to be
        resolved where the id was set."""
        shadowing = {row["id"] for row in self._admitted_code_components(component_type)}
        if resolved_id not in shadowing:
            return
        raise ComponentNotDispatchableError(
            f"'{requested}' names the stored {component_type} '{resolved_id}', but a code-defined "
            f"{component_type} holds that id and is what '{resolved_id}' runs. Give one of them a distinct id, "
            "or run the code-defined one by its id."
        )

    def _refuse_if_only_reachable_with_include_all(self, component_type: str, identifier: str) -> None:
        """Turn "not found" into the real reason when the identifier does name a
        component, but one this runner may not dispatch."""
        if self.include_all_components:
            return
        finder = {"agent": self._find_agent, "team": self._find_team, "workflow": self._find_workflow}[component_type]
        try:
            if finder(identifier) is None:
                return
        except AmbiguousComponentNameError:
            # The identifier is ambiguous, not undispatchable; let the caller say so.
            raise
        except Exception:
            return
        raise ComponentNotDispatchableError(
            f"{component_type.capitalize()} '{identifier}' is defined in code and provided through the registry, "
            "which this runner may read but not run. Pass include_all_components=True to dispatch it, or store "
            "the component in the database."
        )

    def _agent_for_run(self, agent_id: str) -> Optional["Agent"]:
        agent = self._find_agent(agent_id, for_dispatch=True)
        if agent is None:
            self._refuse_if_only_reachable_with_include_all("agent", agent_id)
            return None
        # Whatever applies however the component was resolved goes ABOVE the
        # branch. Below one of these returns it runs for half the callers, which
        # is how the step-isolation check came to be skipped for code-defined
        # workflows in the first place.
        self._require_inspectable_depth(agent, "agent", agent_id)
        self._warn_if_unverifiable_factory(agent, "agent", agent_id)
        if any(a is agent for a in self._iter_agents(for_dispatch=True)):
            return self._fresh_copy(agent)
        self._warn_if_model_rebuilt(agent, "agent", agent_id)
        return agent

    def _team_for_run(self, team_id: str) -> Optional["Team"]:
        team = self._find_team(team_id, for_dispatch=True)
        if team is None:
            self._refuse_if_only_reachable_with_include_all("team", team_id)
            return None
        self._require_inspectable_depth(team, "team", team_id)
        self._warn_if_unverifiable_factory(team, "team", team_id)
        if any(t is team for t in self._iter_teams(for_dispatch=True)):
            return self._fresh_copy(team)
        # Below the branch is for the rebuild only, and each has a counterpart
        # the copy path runs instead: _fresh_copy answers member sharing with
        # _shared_member, and a code-defined component holds its live model.
        self._require_isolated_members(team, team_id)
        self._warn_if_model_rebuilt(team, "team", team_id)
        return team

    def _workflow_for_run(self, workflow_id: str) -> Optional["Workflow"]:
        wf = self._find_workflow(workflow_id, for_dispatch=True)
        if wf is None:
            self._refuse_if_only_reachable_with_include_all("workflow", workflow_id)
            return None
        self._require_inspectable_depth(wf, "workflow", workflow_id)
        self._warn_if_unverifiable_factory(wf, "workflow", workflow_id)
        if any(w is wf for w in self._iter_workflows(for_dispatch=True)):
            return self._fresh_copy(wf)
        self._require_isolated_steps(wf, workflow_id)
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

    @staticmethod
    def _require_resolvable_member_ids(component_type: str, component_id: str, config: Dict[str, Any]) -> None:
        """Refuse a config that references a member or step executor by a null id.

        Serialization writes the referenced component's id even when it is
        None, and a lookup by None matches the first component that also has
        no id, which is rarely the one that was configured. No registry makes
        the reference resolvable, so the refusal does not depend on one.

        Dispatch only: reads and edits load the component so the reference can
        be seen and repaired, the same split _require_faithful_rebuild uses."""
        if component_type not in ("team", "workflow") or not _references_idless_components(component_type, config):
            return
        raise ComponentNeedsRegistryError(
            f"{component_type.capitalize()} '{component_id}' references a component that had no id when it was "
            "saved, so the reference cannot be resolved. Give that component an id and save it again."
        )

    def _require_registry_for(
        self,
        component_type: str,
        component_id: str,
        config: Dict[str, Any],
        _seen: Optional[set] = None,
        version: Optional[int] = None,
    ) -> None:
        """Refuse to rebuild a component whose config needs the absent registry.

        from_dict silently drops registry-backed references when no registry is
        given; this dispatch surface refuses to run the degraded result. The
        check is transitive: a team's members and a workflow's agent/team steps
        are checked too, so a nested component cannot degrade silently. Covers
        the Studio config shape (id references)."""
        if self.registry is not None:
            return
        if _seen is None:
            _seen = set()
        # Versions of one id are distinct nodes: two branches can pin the same
        # child at different versions, and each version's config is its own.
        key = f"{component_type}:{component_id}:{version}"
        if key in _seen:
            return
        _seen.add(key)
        needs: List[str] = []
        # Tools are deliberately NOT pre-guarded on "the config declares some".
        # Not every serialized tool needs the registry -- a provider-native tool
        # and an external_execution one carry themselves -- and refusing on the
        # declaration would refuse those for what their neighbours need.
        # _require_faithful_rebuild answers the real question afterwards, by
        # comparing what came back against what was declared, so a tool that
        # genuinely could not be rebuilt is still refused and named.
        if config.get("knowledge"):
            needs.append("knowledge")
        if isinstance(config.get("input_schema"), str) or isinstance(config.get("output_schema"), str):
            needs.append("schemas")
        if component_type == "workflow" and _references_executors(component_type, config):
            needs.append("function steps")
        if needs:
            raise ComponentNeedsRegistryError(
                f"{component_type.capitalize()} '{component_id}' references registry-backed resources "
                f"({', '.join(needs)}); construct StudioRunnerTools with the registry to run it."
            )
        from agno.db.base import ComponentType

        # Every pinned version of a child is checked, not one per id: two
        # branches can pin the same child id at different versions, and either
        # version's config may need the registry.
        pinned_versions: Dict[str, set] = {}
        for link in self._load_links_from_db(component_id, version=version):
            child_id = link.get("child_component_id")
            if child_id:
                pinned_versions.setdefault(child_id, set()).add(link.get("child_version"))
        for ref_type, ref_id in _component_references(component_type, config):
            versions = pinned_versions.get(ref_id) or {None}
            for ref_version in sorted(versions, key=lambda v: (v is None, v)):
                ref_loaded = self._load_config_row_from_db(
                    ref_id, version=ref_version, component_type=ComponentType(ref_type)
                )
                if ref_loaded is None:
                    raise ComponentNeedsRegistryError(
                        f"{component_type.capitalize()} '{component_id}' references {ref_type} '{ref_id}', "
                        "which is not stored in the database (a code-defined component); "
                        "construct StudioRunnerTools with the registry to run it."
                    )
                ref_config, ref_resolved_version = ref_loaded
                self._require_registry_for(ref_type, ref_id, ref_config, _seen, version=ref_resolved_version)

    def _dispatch_refusal(
        self,
        error: ComponentRehydrationError,
        config: Dict[str, Any],
        component_type: str,
        component_id: str,
        rebuild_leniently: Callable[[], Any],
        version: Optional[int] = None,
    ) -> Exception:
        """The refusal to raise when strict rehydration rejects a dispatch.

        The dispatch guards name both the component the caller asked for and
        the nested piece that failed, so they inspect a lenient rebuild first.
        A loss deeper than the guards see falls through to the rehydration
        error, which names the component that raised. A dangling pin (a pinned
        version that no longer exists, raised with no cause) already names the
        version and the remedy, which no guard improves on; a pin that failed
        to REBUILD wraps the real cause, and the guards describe that cause
        better.
        """
        if isinstance(error, ComponentPinError) and error.__cause__ is None:
            return ComponentNeedsRegistryError(str(error))
        try:
            self._require_dispatchable(rebuild_leniently(), config, component_type, component_id, version=version)
        except StudioRunnerError as refusal:
            return refusal
        except Exception:
            pass
        return ComponentNeedsRegistryError(str(error))

    def _require_dispatchable(
        self,
        component: Any,
        config: Dict[str, Any],
        component_type: str,
        component_id: str,
        version: Optional[int] = None,
    ) -> None:
        """Every dispatch guard for the component type, in refusal-priority order."""
        self._require_matching_db(config, component, component_type, component_id)
        self._require_declared_models(config, component_type, component_id)
        self._require_inspectable_depth(component, component_type, component_id)
        if component_type == "workflow":
            self._require_reconstructable_steps(config, component_id)
        self._require_faithful_rebuild(component, config, component_type, component_id)
        if component_type in ("team", "workflow"):
            self._require_faithful_registry_copies(component, component_type, component_id)
            self._require_faithful_references(component, config, component_type, component_id, version=version)

    def _require_faithful_rebuild(
        self, component: Any, config: Dict[str, Any], component_type: str, component_id: str
    ) -> None:
        """Refuse to dispatch a component whose config named registry-backed
        pieces this registry does not hold.

        _require_registry_for covers the registry being ABSENT. A registry that
        is present but incomplete degrades instead of failing: rehydrate_functions
        binds an unresolved tool to ``entrypoint=None``, and from_dict deletes a
        knowledge or schema reference it cannot resolve. Either way from_dict
        returns successfully and the component runs without the piece. Checking
        the rebuilt object against its own config catches every such shape
        without having to predict how each one resolves.

        Reads and edits skip this, so a component missing a tool stays loadable
        and repairable."""
        from agno.tools.function import Function

        missing: List[str] = []

        declared_tools = config.get("tools") or []
        if declared_tools:
            rebuilt_tools = getattr(component, "tools", None) or []
            unresolved = sorted(
                {
                    str(getattr(tool, "name", None) or "?")
                    for tool in rebuilt_tools
                    if isinstance(tool, Function) and tool.entrypoint is None and not tool.external_execution
                }
            )
            if unresolved:
                missing.append(f"tools ({', '.join(unresolved)})")
            elif len(rebuilt_tools) < len(declared_tools):
                missing.append(f"tools ({len(declared_tools) - len(rebuilt_tools)} of {len(declared_tools)} dropped)")
            substituted = self._tools_from_another_toolkit(rebuilt_tools)
            if substituted:
                missing.append(f"tools bound from another toolkit ({', '.join(substituted)})")

        declared_knowledge = config.get("knowledge")
        if isinstance(declared_knowledge, dict) and getattr(component, "knowledge", None) is None:
            missing.append(f"knowledge '{declared_knowledge.get('name') or '?'}'")

        for field in ("input_schema", "output_schema"):
            # Only the string form is a registry reference; an inline dict schema
            # carries itself.
            if isinstance(config.get(field), str) and getattr(component, field, None) is None:
                missing.append(f"{field} '{config[field]}'")

        declared_members = config.get("members") or []
        if declared_members:
            rebuilt_members = getattr(component, "members", None) or []
            if len(rebuilt_members) < len(declared_members):
                missing.append(f"members ({len(declared_members) - len(rebuilt_members)} of {len(declared_members)})")

        nested = self._unresolved_below(component)
        if nested is not None:
            missing.append(f"nested component {nested}")

        if missing:
            raise ComponentNeedsRegistryError(
                f"{component_type.capitalize()} '{component_id}' references registry-backed resources this "
                f"registry does not provide ({'; '.join(missing)}); register them before running it. Reads and "
                "edits still load the component."
            )

    def _require_inspectable_depth(self, component: Any, component_type: str, component_id: str) -> None:
        """Refuse a graph deeper than the dispatch checks walk.

        Every check here is depth-capped so a cycle cannot hang it, and a cap
        reached mid-walk returns "nothing wrong" -- a pass for a graph that was
        never fully inspected. Refusing past the cap stops a cap reading as an
        approval."""
        seen: set = set()
        frontier = [(component, 0)]
        while frontier:
            node, depth = frontier.pop()
            if node is None or id(node) in seen:
                continue
            seen.add(id(node))
            if depth > _GRAPH_DEPTH_CAP:
                raise ComponentNotDispatchableError(
                    f"{component_type.capitalize()} '{component_id}' nests deeper than "
                    f"{_GRAPH_DEPTH_CAP} levels, past what the runner inspects before dispatch; "
                    "flatten it, or dispatch the nested component directly."
                )
            frontier.extend((child, depth + 1) for child in self._child_nodes(node))

    def _require_faithful_registry_copies(self, component: Any, component_type: str, component_id: str) -> None:
        """Refuse a rebuild holding a degraded copy of a registered component.

        _require_isolated_members and _require_isolated_steps catch a copy that
        IS the singleton. A deep_copy returning a distinct but blank object, or
        an instance of a plainer class, passes both and then dispatches with no
        model and no instructions. The registry still holds the original, so the
        copy can be judged against it."""
        originals: Dict[tuple, Any] = {}
        for instance in self._registry_instances():
            instance_id = getattr(instance, "id", None)
            if isinstance(instance_id, str):
                originals.setdefault((self._component_kind(instance), instance_id), instance)
        if not originals:
            return
        for node in self._descendants(component):
            node_id = getattr(node, "id", None)
            original = originals.get((self._component_kind(node), node_id)) if isinstance(node_id, str) else None
            # Only a rebuild of that very component is comparable; the singleton
            # itself is _require_isolated_*'s question.
            if original is None or original is node:
                continue
            if self._copy_lost_identity(original, node):
                label = getattr(node, "id", None) or getattr(node, "name", None) or "?"
                raise DispatchCopyError(
                    f"{component_type.capitalize()} '{component_id}' rebuilt '{label}' as a degraded copy of the "
                    "registered component: its class, model or instructions did not survive. Give that class a "
                    "deep_copy that rebuilds it, or store the component in the database."
                )

    def _require_reference_type_matches(
        self, ref_type: str, ref_id: str, component_type: str, component_id: str
    ) -> None:
        """Refuse a reference whose id the database stores under another type.

        A code-defined reference is simply absent from the components table. An
        id that IS there under a different type is a contradiction, and the
        piece it resolved to cannot be checked against any stored config."""
        if self.db is None:
            return
        try:
            stored = self.db.get_component(ref_id)
        except NotImplementedError:
            return
        stored_type = stored.get("component_type") if isinstance(stored, dict) else None
        if stored_type is None or str(stored_type) == ref_type:
            return
        raise ComponentNotDispatchableError(
            f"{component_type.capitalize()} '{component_id}' references {ref_type} '{ref_id}', but the database "
            f"stores '{ref_id}' as a {stored_type}; the runner cannot verify what that reference resolved to. "
            "Point the reference at the right component, or give it an id of its own."
        )

    @staticmethod
    def _descendants(node: Any, depth: int = 0, seen: Optional[set] = None) -> List[Any]:
        """Every member and step executor below a component, once each."""
        seen = set() if seen is None else seen
        found: List[Any] = []
        if node is None or depth > _GRAPH_DEPTH_CAP:
            return found
        for child in StudioRunnerTools._child_nodes(node):
            if id(child) in seen:
                continue
            seen.add(id(child))
            found.append(child)
            found.extend(StudioRunnerTools._descendants(child, depth + 1, seen))
        return found

    def _tools_from_another_toolkit(self, rebuilt_tools: List[Any]) -> List[str]:
        """Tools whose recorded toolkit is not the one that supplied them.

        A serialized tool carries the toolkit that owned it. When the registry
        no longer provides that toolkit, rehydration falls back to the flat
        name and binds a same-named function from a DIFFERENT toolkit -- it
        warns, then keeps the recorded owning_toolkit on the rebuilt Function,
        so nothing downstream can see that other code is now behind the name.
        Same-named members are common (``search``, ``lookup``, ``run``), so
        this is how a component silently starts executing someone else's tool.

        Checked against the registry's own toolkits, which is the same question
        its qualified lookup asks."""
        from agno.tools.function import Function

        if self.registry is None:
            return []
        provided = {
            (getattr(toolkit, "name", None), function_name)
            for toolkit in (self.registry.tools or [])
            for function_name in (getattr(toolkit, "functions", None) or {})
        }
        substituted = []
        for tool in rebuilt_tools:
            owner = getattr(tool, "owning_toolkit", None)
            name = getattr(tool, "name", None)
            if not isinstance(tool, Function) or owner is None or name is None:
                continue
            if (owner, name) not in provided:
                substituted.append(f"{owner}.{name}")
        return sorted(set(substituted))

    def _require_faithful_references(
        self,
        component: Any,
        config: Dict[str, Any],
        component_type: str,
        component_id: str,
        version: Optional[int] = None,
    ) -> None:
        """Check each referenced member or step executor against its OWN config.

        _require_faithful_rebuild compares a component with the config it was
        built from, and a workflow's config carries none of the tools, knowledge
        or schemas its step executors declare: those live in the referenced
        components' own configs, so every branch of that check is silent for a
        workflow. Without this, an executor that lost its output_schema to an
        incomplete registry dispatches and answers in prose, while the same
        component dispatched directly is refused. ``version`` is the parent's
        resolved config version; its links pin the child versions the members
        were rebuilt from, so each child is judged against that config."""
        if self.db is None:
            return
        self._check_references(component, config, component_type, component_id, set(), {}, version=version)

    def _check_references(
        self,
        component: Any,
        config: Dict[str, Any],
        component_type: str,
        component_id: str,
        seen: set,
        configs: Dict[tuple, Tuple[Optional[Dict[str, Any]], Optional[int]]],
        depth: int = 0,
        version: Optional[int] = None,
    ) -> None:
        """Check this component's references, then theirs, down to the leaves.

        A reference's own config names references of its own, so stopping after
        one hop leaves an outer team dispatchable while its inner team's member
        lost the schema it declared. Each child is compared against the config
        version the parent's links pin, which is the version it was rebuilt
        from; an unpinned child was rebuilt at its current version. ``configs``
        caches each (type, id, version) config row so a shared reference is
        read once per dispatch, and the row's resolved version feeds the
        child's own links read.

        A workflow's checks are per OCCURRENCE, not per child id: two branches
        can pin the same child id at different versions, and each rebuilt
        branch object must be compared against the config version its own
        branch-qualified link pinned - collapsing by id would validate one
        (config, object) pairing and admit the other unexamined."""
        from agno.db.base import ComponentType

        key = (component_type, component_id, version)
        # `seen` is the cycle guard and nothing else: counting it bounded how
        # WIDE a graph could be rather than how deep, so a team with more
        # members than the cap stopped checking the rest of them. Versions of
        # one id are distinct nodes; the depth cap bounds any version chain.
        if key in seen or depth > _GRAPH_DEPTH_CAP:
            return
        seen.add(key)
        links = self._load_links_from_db(component_id, version=version)
        registered = {
            (self._component_kind(instance), instance_id)
            for instance, instance_id in (
                (instance, getattr(instance, "id", None)) for instance in self._registry_instances()
            )
            if isinstance(instance_id, str)
        }
        if component_type == "workflow":
            checks = []
            checked_occurrences = set()
            for link_kind, link_key, ref_type, ref_id, target in self._step_occurrences(component):
                if not isinstance(ref_id, str) or target is None:
                    continue
                ref_version = self._occurrence_pin(links, link_kind, link_key, ref_id)
                occurrence = (ref_type, ref_id, ref_version, id(target))
                if occurrence in checked_occurrences:
                    continue
                checked_occurrences.add(occurrence)
                checks.append((ref_type, ref_id, ref_version, target))
        else:
            pins: Dict[str, Optional[int]] = {}
            for link in links:
                child_id = link.get("child_component_id")
                if child_id:
                    pins[child_id] = link.get("child_version")
            rebuilt = self._components_by_id(component)
            checks = [
                (ref_type, ref_id, pins.get(ref_id), rebuilt.get((ref_type, ref_id)))
                for ref_type, ref_id in _component_references(component_type, config)
            ]
        for ref_type, ref_id, ref_version, target in checks:
            if target is None:
                continue
            if (ref_type, ref_id) in registered:
                # from_dict resolves a member or step executor from the registry
                # before the database, so this object was never built from the
                # stored config and does not have to match it: a live toolkit is
                # one object where the config lists its eight functions.
                # _require_faithful_registry_copies judges this one instead.
                continue
            try:
                stored_type = ComponentType(ref_type)
            except ValueError:
                # A reference type this runner does not model; the loaders'
                # type guards cover it.
                continue
            # A db read that fails is not evidence of fidelity, so it must not
            # pass as one: let it reach the caller's handler.
            cache_key = (ref_type, ref_id, ref_version)
            if cache_key in configs:
                ref_config, ref_resolved_version = configs[cache_key]
            else:
                ref_loaded = self._load_config_row_from_db(ref_id, version=ref_version, component_type=stored_type)
                ref_config, ref_resolved_version = ref_loaded if ref_loaded is not None else (None, None)
                configs[cache_key] = (ref_config, ref_resolved_version)
            if ref_config is None:
                # A code-defined reference has no stored config to compare
                # against, and _require_registry_for covers an absent registry.
                # An id stored under a DIFFERENT type is neither: the reference
                # names something the database contradicts, so nothing here can
                # be checked against it.
                self._require_reference_type_matches(ref_type, ref_id, component_type, component_id)
                continue
            self._require_faithful_rebuild(target, ref_config, ref_type, ref_id)
            # A member or step executor declares its own models, so the loss is
            # reported where it happened rather than only for the component the
            # caller named.
            self._require_declared_models(ref_config, ref_type, ref_id)
            self._require_matching_db(ref_config, target, ref_type, ref_id)
            self._check_references(
                target, ref_config, ref_type, ref_id, seen, configs, depth + 1, version=ref_resolved_version
            )

    @staticmethod
    def _step_occurrences(workflow: Any) -> List[tuple]:
        """Each step-family reference below a workflow, with the branch-qualified
        link key it was pinned under: (link_kind, link_key, ref_type, ref_id, object).

        Mirrors the save traversal and Step.from_dict's key rule: a step's key
        is its step_id (or name) plus one ``#else`` per enclosing else branch.
        The same child id can appear on several branches at different pinned
        versions, so each occurrence carries its own key instead of collapsing
        by id."""
        from agno.workflow.condition import Condition
        from agno.workflow.loop import Loop
        from agno.workflow.parallel import Parallel
        from agno.workflow.router import Router
        from agno.workflow.step import Step
        from agno.workflow.steps import Steps

        found: List[tuple] = []

        def walk(step: Any, suffix: str) -> None:
            if isinstance(step, Step):
                key_base = getattr(step, "step_id", None) or getattr(step, "name", None)
                qualified = f"{key_base}{suffix}" if key_base else None
                agent = getattr(step, "agent", None)
                if agent is not None:
                    found.append(("step_agent", qualified, "agent", getattr(agent, "id", None), agent))
                team = getattr(step, "team", None)
                if team is not None:
                    found.append(("step_team", qualified, "team", getattr(team, "id", None), team))
                nested_workflow = getattr(step, "workflow", None)
                if nested_workflow is not None:
                    found.append(
                        ("step_workflow", qualified, "workflow", getattr(nested_workflow, "id", None), nested_workflow)
                    )
                return
            if isinstance(step, (Parallel, Loop, Steps, Condition)):
                for nested in getattr(step, "steps", None) or []:
                    walk(nested, suffix)
                for nested in getattr(step, "else_steps", None) or []:
                    walk(nested, f"{suffix}#else")
                return
            if isinstance(step, Router):
                for nested in getattr(step, "choices", None) or []:
                    walk(nested, suffix)
                return
            # A bare component used directly as a step has no Step wrapper and
            # no link key; it still has to be checked, under the id-level rule.
            kind = StudioRunnerTools._component_kind(step)
            if kind in ("agent", "team", "workflow") and isinstance(getattr(step, "id", None), str):
                link_kind = {"agent": "step_agent", "team": "step_team", "workflow": "step_workflow"}[kind]
                found.append((link_kind, None, kind, step.id, step))

        steps = getattr(workflow, "steps", None)
        for step in steps if isinstance(steps, list) else []:
            walk(step, "")
        return found

    @staticmethod
    def _occurrence_pin(
        links: List[Dict[str, Any]], link_kind: str, link_key: Optional[str], child_id: str
    ) -> Optional[int]:
        """The version pinned for one step occurrence.

        The exact branch-qualified key wins; without an exact match the
        id-level pin applies only when every pin for the child agrees - the
        same resolution rule Step.from_dict rebuilds with, so the version
        checked is the version the object was built from."""
        child_links = [
            link for link in links if link.get("link_kind") == link_kind and link.get("child_component_id") == child_id
        ]
        if not child_links:
            return None
        for link in child_links:
            if link_key is not None and link.get("link_key") == link_key:
                return link.get("child_version")
        versions = {link.get("child_version") for link in child_links}
        if len(versions) == 1:
            return child_links[0].get("child_version")
        return None

    @staticmethod
    def _components_by_id(node: Any) -> Dict[tuple, Any]:
        """The rebuilt members and step executors below a component, by (type, id).

        Ids are unique per type only, so keying on the id alone would let a
        stored team's config be checked against an agent that shares it."""
        found: Dict[tuple, Any] = {}
        for child in StudioRunnerTools._descendants(node):
            child_id = getattr(child, "id", None)
            if not isinstance(child_id, str):
                continue
            found.setdefault((StudioRunnerTools._component_kind(child), child_id), child)
        return found

    @staticmethod
    def _unresolved_below(node: Any, depth: int = 0, seen: Optional[set] = None) -> Optional[str]:
        """The first nested member or step executor holding a tool with no
        entrypoint, or None when the graph below is intact.

        A member and a step executor rebuild from configs of their own, so the
        parent's config check says nothing about them: rehydrate_functions binds
        an unresolved tool to ``entrypoint=None`` at every depth alike, and an
        incomplete registry would otherwise run a nested member stripped of its
        tools. Depth- and cycle-capped, over objects already in memory."""
        from agno.tools.function import Function

        if node is None or depth > _GRAPH_DEPTH_CAP:
            return None
        seen = set() if seen is None else seen
        if id(node) in seen:
            return None
        seen.add(id(node))

        for child in StudioRunnerTools._child_nodes(node):
            child_tools = getattr(child, "tools", None)
            unresolved = sorted(
                {
                    str(getattr(tool, "name", None) or "?")
                    for tool in (child_tools if isinstance(child_tools, list) else [])
                    if isinstance(tool, Function) and tool.entrypoint is None and not tool.external_execution
                }
            )
            if unresolved:
                label = getattr(child, "id", None) or getattr(child, "name", None) or type(child).__name__
                return f"{label}: tools ({', '.join(unresolved)})"
            found = StudioRunnerTools._unresolved_below(child, depth + 1, seen)
            if found is not None:
                return found
        return None

    def _warn_if_unverifiable_factory(self, component: Any, component_type: str, component_id: str) -> None:
        """Log when a dispatched component builds part of itself at run time.

        ``members``, ``tools`` and ``steps`` all accept a callable factory, and
        the framework resolves it per run into the run context, reusing the
        result while ``cache_callables`` is on. Nothing exists to inspect at
        dispatch, so the isolation checks skip it and the per-run-copy promise
        does not reach what the factory returns: a factory that hands back a
        shared instance shares it across callers, here as anywhere else. The
        runner does not refuse it -- the shape is supported and the caching is
        deliberate -- but it says so rather than implying a guarantee it cannot
        make."""
        from agno.tools.function import Function
        from agno.tools.toolkit import Toolkit
        from agno.utils.callables import is_callable_factory

        for node in [component] + self._descendants(component):
            for attribute in ("members", "tools", "steps"):
                value = getattr(node, attribute, None)
                excluded = (Toolkit, Function) if attribute == "tools" else ()
                if not is_callable_factory(value, excluded_types=excluded):
                    continue
                label = getattr(node, "id", None) or getattr(node, "name", None) or component_id
                logger.warning(
                    "StudioRunnerTools: %s '%s' builds '%s' from a callable %s factory, which the runner "
                    "cannot inspect before dispatch; what it returns is outside the per-run copy, and is "
                    "shared across callers while cache_callables is on.",
                    component_type,
                    component_id,
                    label,
                    attribute,
                )

    @staticmethod
    def _require_declared_models(config: Dict[str, Any], component_type: str, component_id: str) -> None:
        """Refuse a component whose declared reasoning, parser or output model
        cannot be reconstructed.

        These are written by to_dict and never read back -- from_dict's
        reconstruction for them is commented out (#9452) -- so a component that
        declares one always rebuilds without it and answers through a
        materially different pipeline than it was configured for. The run
        succeeds, so a log line is invisible to whoever asked.

        Until #9452 lands, not dispatchable is the honest description of the
        capability: the alternative is a successful answer computed some other
        way, which is the failure this toolkit exists to prevent. Reads and
        edits still load the component, so it stays inspectable."""
        declared = [field for field in ("reasoning_model", "parser_model", "output_model") if config.get(field)]
        if not declared:
            return
        raise ComponentNotDispatchableError(
            f"{component_type.capitalize()} '{component_id}' declares {', '.join(declared)}, which the framework "
            "does not reconstruct (#9452), so the run would answer through a different pipeline than it was "
            "configured for. Remove the declaration, or run it as a code-defined component."
        )

    def _warn_if_model_rebuilt(self, component: Any, component_type: str, component_id: str) -> None:
        """Log when a dispatched agent's or team's model is a config rebuild.

        Model connection settings and credentials are never persisted, so a
        model rebuilt from config runs against the provider's default endpoint
        with ambient credentials. Only the live registry instance carries the
        configured connection. The check covers the dispatched component's own
        model; a workflow step's executor and a team member carry models
        rebuilt the same way."""
        model = getattr(component, "model", None)
        if model is None:
            return
        registry_models = list(self.registry.models or []) if self.registry is not None else []
        if any(model is registered for registered in registry_models):
            return
        logger.warning(
            "StudioRunnerTools: %s '%s' uses model '%s' rebuilt from its stored config; "
            "connection settings and credentials are not persisted, so provider defaults apply.",
            component_type,
            component_id,
            getattr(model, "id", None) or type(model).__name__,
        )

    def _require_matching_db(
        self, config: Dict[str, Any], component: Any, component_type: str, component_id: str
    ) -> None:
        """Refuse a component whose declared routing is not the routing it got.

        A stored db is reconstructed from its own config (postgres, sqlite and
        clickhouse carry a connection field), resolved from the registry by id,
        or -- when neither supplies it -- replaced by the catalog db. Only the
        first of those applies the table overrides the component declared: a
        registry instance is used as it was registered, and the catalog db is
        somebody else's store entirely. Either way the component's sessions and
        memory durably land somewhere other than configured, and nothing in the
        answer the caller gets back says so.

        The comparison is against the db the component ACTUALLY holds, not
        against the catalog, because a resolved db is exactly as able to be the
        wrong one. Comparing what it got is also what keeps this narrow enough
        to keep: when the routing matches, the component runs, which is what
        leaves the adapters whose connection cannot serialize (mysql, mongo,
        redis, json, dynamo) dispatchable. A blanket refusal was reverted
        before for taking those out."""
        from agno.utils.db_fallback import db_fallback_divergence

        db_config = config.get("db")
        if not isinstance(db_config, dict):
            return
        actual_db = getattr(component, "db", None)
        if actual_db is None:
            # Nothing resolved at all. Comparing against an empty mapping would
            # find no differing keys and admit it, which is the loudest
            # mismatch reading as a match. A referenced member or step executor
            # is the case that reaches here: the loaders give the dispatched
            # component the catalog db, but nothing backfills a nested one.
            declared_id = db_config.get("id") or db_config.get("type") or "unknown"
            raise ComponentNotDispatchableError(
                f"{component_type.capitalize()} '{component_id}' declares db '{declared_id}', and no db resolved "
                "for it at all; running it would write its sessions and memory nowhere it was configured to. "
                "Register that db, or remove the declaration."
            )
        differing = db_fallback_divergence(config, actual_db) or []
        if not differing:
            return
        declared = db_config.get("id") or db_config.get("type") or "unknown"
        raise ComponentNotDispatchableError(
            f"{component_type.capitalize()} '{component_id}' declares db '{declared}', and the db it resolved to "
            f"routes differently ({', '.join(differing)}); running it would write its sessions and memory "
            "somewhere other than configured. Register that db as it was declared, or run it against the db it "
            "declares."
        )

    @staticmethod
    def _require_reconstructable_steps(config: Dict[str, Any], workflow_id: str) -> None:
        """Refuse to dispatch a stored workflow whose step targets another workflow.

        A nested workflow serializes as ``workflow_id`` alone, and Step.from_dict
        cannot rebuild one: it installs a placeholder that returns an unsuccessful
        StepOutput. A failed step does not fail its workflow, so the parent run
        would report COMPLETED while the child never executed. Reads and edits
        load the same workflow without this check, so the step stays
        inspectable."""
        nested: List[str] = []

        def walk(value: Any) -> None:
            if isinstance(value, list):
                for child in value:
                    walk(child)
                return
            if not isinstance(value, dict):
                return
            if value.get("workflow_id"):
                nested.append(str(value["workflow_id"]))
            # Only a step's own key marks a nested workflow. A step also carries
            # free-form user JSON (a human_review input schema, say), so walking
            # every value would refuse on a field that merely shares the name.
            for branch in ("steps", "else_steps", "choices"):
                walk(value.get(branch))

        walk(config.get("steps"))
        if nested:
            raise ComponentNotDispatchableError(
                f"Workflow '{workflow_id}' has a step targeting workflow "
                f"'{', '.join(sorted(set(nested)))}', which the runner cannot reconstruct; it would report "
                "success without running that step. Inline the nested workflow's steps into this one, or "
                "dispatch it separately."
            )

    @staticmethod
    def _caller_user_id(run_context: Optional[RunContext], component: Any) -> Optional[str]:
        """The user a dispatched run belongs to, or a refusal.

        The runner's whole point is that per-user state lands on the human who
        asked. Passing None for a caller who HAS a context but no user is
        indistinguishable from passing no override at all, so the target falls
        back to its own configured user_id -- and an anonymous run is written
        into that user's memory and learning. That is the failure this toolkit
        exists to prevent, so it is refused rather than attributed.

        A caller with no context at all is a different case: a direct Python
        call is not claiming to be anyone, and the component's own
        configuration is the only identity there is."""
        if run_context is None:
            return None
        if run_context.user_id is not None:
            return run_context.user_id
        target_user = getattr(component, "user_id", None)
        if target_user is None:
            return None
        label = getattr(component, "id", None) or getattr(component, "name", None) or "component"
        raise ComponentNotDispatchableError(
            f"The caller has no user, and '{label}' is configured for user '{target_user}', so this run would be "
            "written into that user's memory and learning. Give the caller a user_id, or clear the target's."
        )

    def _registry_instances(self) -> List[Any]:
        """The shared singletons a rebuild can hand back instead of a copy."""
        if self.registry is None:
            return []
        return list(self.registry.agents or []) + list(self.registry.teams or [])

    @staticmethod
    def _shared_registry_instance(node: Any, shared: List[Any], depth: int = 0) -> Optional[Any]:
        """The shared registry instance held at or below this node, else None.

        A component that is itself a fresh rebuild still leaks if one of its own
        members is the registry singleton, so the search descends.

        A member is only a leak when it could have been copied, the same rule
        _shared_member applies: a member with no deep_copy is shared by design,
        because a remote proxy holds no per-run state to isolate. The node the
        search starts from is judged without that exemption."""
        if node is None or depth > _GRAPH_DEPTH_CAP:
            return None
        is_shared = any(node is instance for instance in shared)
        if is_shared and (depth == 0 or callable(getattr(node, "deep_copy", None))):
            return node
        # members= accepts a callable factory; only a materialized list can be walked.
        members = getattr(node, "members", None)
        for member in members if isinstance(members, list) else []:
            found = StudioRunnerTools._shared_registry_instance(member, shared, depth + 1)
            if found is not None:
                return found
        return None

    def _require_isolated_members(self, team: "Team", team_id: str) -> None:
        """Refuse to dispatch a rebuilt team that holds a shared registry
        instance as a member.

        Team.from_dict resolves a member the database does not hold through the
        registry, and keeps whatever deep_copy returned; a class whose deep_copy
        returns self therefore puts the singleton itself into the rebuilt team.
        _shared_member covers the same hazard on the code-defined path, and
        _require_isolated_steps covers it for a workflow's step executors."""
        shared = self._registry_instances()
        if not shared:
            return
        # The team is a rebuild, not the singleton itself, so start below it.
        # depth=1 keeps the shared-by-design exemption for a member that has no
        # deep_copy, which is the rule _shared_member applies.
        members = getattr(team, "members", None)
        for member in members if isinstance(members, list) else []:
            leaked = self._shared_registry_instance(member, shared, depth=1)
            if leaked is None:
                continue
            leaked_label = getattr(leaked, "id", None) or getattr(leaked, "name", None) or "?"
            raise DispatchCopyError(
                f"Team '{team_id}' resolved to the shared registry instance of member '{leaked_label}'; "
                "the runner dispatches only isolated copies. Give that member's class a deep_copy that "
                "rebuilds it, or store the member in the database."
            )

    def _require_isolated_steps(self, wf: "Workflow", workflow_id: str) -> None:
        """Refuse to dispatch a rebuilt workflow that holds a shared registry
        instance in a step.

        Step.from_dict keeps the shared registry agent/team when its deep_copy
        raises; dispatching that instance would let per-run mutation cross
        callers. Reads and edits load the same workflow without this check, so
        the offending step stays inspectable and editable."""
        shared = self._registry_instances()
        if not shared:
            return

        def shared_within(node: Any, depth: int = 0) -> Optional[Any]:
            return StudioRunnerTools._shared_registry_instance(node, shared, depth)

        def walk(item: Any) -> None:
            for attr in ("agent", "team"):
                executor = getattr(item, attr, None)
                leaked = shared_within(executor)
                if leaked is not None:
                    where = (
                        f"{attr} '{getattr(executor, 'id', None)}'"
                        if leaked is executor
                        else f"a member of {attr} '{getattr(executor, 'id', None)}', "
                        f"'{getattr(leaked, 'id', None) or getattr(leaked, 'name', None)}'"
                    )
                    raise DispatchCopyError(
                        f"Workflow '{workflow_id}' step '{getattr(item, 'name', None)}' resolved to the shared "
                        f"registry instance of {where}; the runner dispatches only isolated copies. Give the "
                        "class a deep_copy that rebuilds it, or store the component in the database."
                    )
            for child_attr in ("steps", "else_steps", "choices"):
                children = getattr(item, child_attr, None)
                if isinstance(children, (list, tuple)):
                    for child in children:
                        walk(child)

        steps = getattr(wf, "steps", None)
        if isinstance(steps, (list, tuple)):
            for step in steps:
                walk(step)

    def _load_agent_from_db(
        self, agent_id: str, version: Optional[int] = None, for_dispatch: bool = False
    ) -> Optional["Agent"]:
        """Load an agent from DB via config + from_dict.

        Registry-backed references resolve at their current published version."""
        from agno.db.base import ComponentType

        loaded = self._load_config_row_from_db(agent_id, version=version, component_type=ComponentType.AGENT)
        if loaded is None:
            return None
        config, resolved_version = loaded
        self._require_registry_for("agent", agent_id, config, version=resolved_version)
        from agno.agent.agent import Agent

        try:
            agent = Agent.from_dict(config, registry=self.registry, strict=for_dispatch)
            agent.id = agent_id
            # The catalog db is a fallback only: a config-declared db (resolved
            # by from_dict, possibly with table overrides) must keep winning.
            if getattr(agent, "db", None) is None:
                # Announced on every load, including reads. Whether the
                # routing actually differs is a dispatch question, asked by
                # _require_matching_db after this block: it cannot be raised
                # from inside this try, where the handler below would report
                # the refusal as a rebuild failure.
                if isinstance(config.get("db"), dict):
                    logger.warning(
                        "StudioRunnerTools: agent '%s' declares a db that could not be reconstructed; "
                        "it falls back to the catalog db.",
                        agent_id,
                    )
                agent.db = self.db
        except ComponentRehydrationError as rehydration_error:
            raise self._dispatch_refusal(
                rehydration_error,
                config,
                "agent",
                agent_id,
                lambda: Agent.from_dict(config, registry=self.registry, strict=False),
                version=resolved_version,
            ) from rehydration_error
        except Exception:
            logger.warning("StudioRunnerTools: Agent.from_dict failed for %s", agent_id, exc_info=True)
            return None
        if for_dispatch:
            self._require_dispatchable(agent, config, "agent", agent_id, version=resolved_version)
        return agent

    def _load_team_from_db(
        self, team_id: str, version: Optional[int] = None, for_dispatch: bool = False
    ) -> Optional["Team"]:
        from agno.db.base import ComponentType

        loaded = self._load_config_row_from_db(team_id, version=version, component_type=ComponentType.TEAM)
        if loaded is None:
            return None
        config, resolved_version = loaded
        if for_dispatch:
            # Dispatch only: a null reference cannot be resolved, but the component
            # still has to load so the bad reference can be seen and repaired.
            self._require_resolvable_member_ids("team", team_id, config)
        self._require_registry_for("team", team_id, config, version=resolved_version)
        from agno.team.team import Team

        links = self._load_links_from_db(team_id, version=resolved_version)
        try:
            team = Team.from_dict(config, db=self.db, registry=self.registry, links=links, strict=for_dispatch)
            team.id = team_id
            # The catalog db is a fallback only; a config-declared db wins.
            if getattr(team, "db", None) is None:
                # Announced on every load, including reads. Whether the
                # routing actually differs is a dispatch question, asked by
                # _require_matching_db after this block: it cannot be raised
                # from inside this try, where the handler below would report
                # the refusal as a rebuild failure.
                if isinstance(config.get("db"), dict):
                    logger.warning(
                        "StudioRunnerTools: team '%s' declares a db that could not be reconstructed; "
                        "it falls back to the catalog db.",
                        team_id,
                    )
                team.db = self.db
        except ComponentRehydrationError as rehydration_error:
            raise self._dispatch_refusal(
                rehydration_error,
                config,
                "team",
                team_id,
                lambda: Team.from_dict(config, db=self.db, registry=self.registry, links=links, strict=False),
                version=resolved_version,
            ) from rehydration_error
        except Exception:
            logger.warning("StudioRunnerTools: Team.from_dict failed for %s", team_id, exc_info=True)
            return None
        if for_dispatch:
            self._require_dispatchable(team, config, "team", team_id, version=resolved_version)
        return team

    def _load_workflow_from_db(
        self, workflow_id: str, version: Optional[int] = None, for_dispatch: bool = False
    ) -> Optional["Workflow"]:
        from agno.db.base import ComponentType

        loaded = self._load_config_row_from_db(workflow_id, version=version, component_type=ComponentType.WORKFLOW)
        if loaded is None:
            return None
        config, resolved_version = loaded
        if for_dispatch:
            # Dispatch only: a null reference cannot be resolved, but the component
            # still has to load so the bad reference can be seen and repaired.
            self._require_resolvable_member_ids("workflow", workflow_id, config)
        self._require_registry_for("workflow", workflow_id, config, version=resolved_version)
        from agno.workflow.workflow import Workflow

        links = self._load_links_from_db(workflow_id, version=resolved_version)
        try:
            wf = Workflow.from_dict(config, db=self.db, registry=self.registry, links=links, strict=for_dispatch)
            wf.id = workflow_id
            # The catalog db is a fallback only; a config-declared db wins.
            if getattr(wf, "db", None) is None:
                # Announced on every load, including reads. Whether the
                # routing actually differs is a dispatch question, asked by
                # _require_matching_db after this block: it cannot be raised
                # from inside this try, where the handler below would report
                # the refusal as a rebuild failure.
                if isinstance(config.get("db"), dict):
                    logger.warning(
                        "StudioRunnerTools: workflow '%s' declares a db that could not be reconstructed; "
                        "it falls back to the catalog db.",
                        workflow_id,
                    )
                wf.db = self.db
        except ComponentRehydrationError as rehydration_error:
            raise self._dispatch_refusal(
                rehydration_error,
                config,
                "workflow",
                workflow_id,
                lambda: Workflow.from_dict(config, db=self.db, registry=self.registry, links=links, strict=False),
                version=resolved_version,
            ) from rehydration_error
        except Exception:
            logger.warning("StudioRunnerTools: Workflow.from_dict failed for %s", workflow_id, exc_info=True)
            return None
        if for_dispatch:
            self._require_dispatchable(wf, config, "workflow", workflow_id, version=resolved_version)
        return wf

    def _load_config_from_db(
        self,
        component_id: str,
        version: Optional[int] = None,
        component_type: Optional["ComponentType"] = None,
    ) -> Optional[Dict[str, Any]]:
        """Load a component's config by id. See _load_config_row_from_db."""
        loaded = self._load_config_row_from_db(component_id, version=version, component_type=component_type)
        return loaded[0] if loaded is not None else None

    def _load_config_row_from_db(
        self,
        component_id: str,
        version: Optional[int] = None,
        component_type: Optional["ComponentType"] = None,
    ) -> Optional[Tuple[Dict[str, Any], Optional[int]]]:
        """Load a component's config and its resolved version in one read.

        The resolved version feeds the links fetch and the dispatch guards, so
        a publish between reads can never pair one version's config with
        another version's links.

        When ``component_type`` is given, the stored component must be of that
        type; a mismatch returns None so that, e.g., a team id never loads as an
        Agent.
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
        if not isinstance(row, dict):
            return None
        config = row.get("config")
        if not isinstance(config, dict):
            return None
        resolved_version = row.get("version")
        return config, (resolved_version if isinstance(resolved_version, int) else None)

    def _load_links_from_db(self, component_id: str, version: Optional[int] = None) -> List[Dict[str, Any]]:
        """Links for a component's resolved config version.

        Member and step links carry the child versions pinned at save time, so
        a rebuilt team/workflow resolves its children at the versions the
        parent was saved against. Adapters without link support pin nothing.
        """
        if self.db is None:
            return []
        try:
            if version is None:
                row = self.db.get_config(component_id=component_id)
                version = row.get("version") if isinstance(row, dict) else None
            if not version:
                return []
            return self.db.get_links(component_id=component_id, version=version) or []
        except NotImplementedError:
            return []

    def _list_db_component_rows(
        self, component_type: str, limit: Optional[int] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Thin DB component summaries ({id, name, description}) plus the total count."""
        if self.db is None:
            return [], 0
        from agno.db.base import ComponentType

        try:
            rows, total = self.db.list_components(
                component_type=ComponentType(component_type),
                limit=limit if limit is not None else self.list_limit,
            )
        except NotImplementedError:
            # Not every db adapter implements component storage; degrade to an
            # empty listing like the other db helpers here.
            return [], 0
        return (
            [{"id": r.get("component_id"), "name": r.get("name"), "description": r.get("description")} for r in rows],
            total,
        )

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_agents(self) -> str:
        """List agents this runner can run, newest first.

        Reports the components stored in the platform database, preceded by any
        code-defined agents this runner admits (an explicit list, or the
        registry under include_all_components). What can be run can be found.

        Returns:
            str: JSON object with 'agents' (each {id, name, description}), 'count'
                (returned) and 'total' (every component this runner can run;
                total > count means the list is capped -- components beyond the
                cap still run by exact id).
        """
        return self._list_payload("agent", "agents")

    def list_teams(self) -> str:
        """List teams this runner can run, newest first.

        Reports the components stored in the platform database, preceded by any
        code-defined teams this runner admits (an explicit list, or the
        registry under include_all_components). What can be run can be found.

        Returns:
            str: JSON object with 'teams' (each {id, name, description}), 'count'
                (returned) and 'total' (every component this runner can run;
                total > count means the list is capped -- components beyond the
                cap still run by exact id).
        """
        return self._list_payload("team", "teams")

    def list_workflows(self) -> str:
        """List workflows this runner can run, newest first.

        Reports the components stored in the platform database, preceded by any
        code-defined workflows this runner admits (an explicit list, or the
        registry under include_all_components). What can be run can be found.

        Returns:
            str: JSON object with 'workflows' (each {id, name, description}), 'count'
                (returned) and 'total' (every component this runner can run;
                total > count means the list is capped -- components beyond the
                cap still run by exact id).
        """
        return self._list_payload("workflow", "workflows")

    def _list_payload(self, component_type: str, key: str) -> str:
        admitted = self._admitted_code_components(component_type)
        if self.db is None:
            # A code allowlist runs without a database, so it has to be findable
            # without one too; only the database half is unavailable here.
            if admitted:
                return json.dumps({key: admitted, "count": len(admitted), "total": len(admitted)})
            return json.dumps({"error": "StudioRunnerTools has no db configured; cannot list components."})
        try:
            items, total = self._list_db_component_rows(component_type)
            # What dispatch admits is what discovery reports. The instructions
            # tell the caller to list first and run by id, so a component that
            # runs and cannot be found leaves it no way to reach it. Code
            # components come first, which is the order dispatch resolves in.
            seen_ids = {entry["id"] for entry in admitted}
            # Against the whole table, not this page: a shadowed row beyond the
            # cap is still one component, and counting only what was returned
            # inflated the total.
            shadowed = sum(1 for component_id in seen_ids if self._db_component_exists(component_type, component_id))
            items = admitted + [entry for entry in items if entry.get("id") not in seen_ids]
            # A code component shadows the stored one it shares an id with, so
            # the pair is one component to run, not two to count.
            return json.dumps({key: items, "count": len(items), "total": total + len(admitted) - shadowed})
        except Exception as e:
            logger.exception("Failed to list %s", key)
            return json.dumps({"error": str(e) or type(e).__name__})

    def _admitted_code_components(self, component_type: str) -> List[Dict[str, Any]]:
        """The code-defined components this runner will dispatch, as list rows.

        Only what dispatch admits: an explicit list is its own allowlist, and
        the registry half is included only under ``include_all_components``.
        A component with no id cannot be run by id, so it is not offered."""
        # Annotated because the three return different component types, which
        # mypy otherwise joins to a bare object.
        iterators: Dict[str, Callable[..., List[Any]]] = {
            "agent": self._iter_agents,
            "team": self._iter_teams,
            "workflow": self._iter_workflows,
        }
        rows: List[Dict[str, Any]] = []
        seen_ids: set = set()
        for component in iterators[component_type](for_dispatch=True):
            component_id = getattr(component, "id", None)
            if not isinstance(component_id, str) or component_id in seen_ids:
                continue
            seen_ids.add(component_id)
            rows.append(
                {
                    "id": component_id,
                    "name": getattr(component, "name", None),
                    "description": getattr(component, "description", None),
                }
            )
        return rows

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
        except StudioRunnerError as e:
            # Deliberate refusals with an actionable message; not failures to log.
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
                user_id=self._caller_user_id(_agno_run_context, agent),
                session_id=self._sub_session_id(_agno_run_context, "agent", component_id),
            )
            return self._run_payload("agent_id", component_id, response)
        except Exception as e:
            logger.exception("Failed to run agent")
            return json.dumps({"error": str(e) or type(e).__name__})

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
        except StudioRunnerError as e:
            # Deliberate refusals with an actionable message; not failures to log.
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
                user_id=self._caller_user_id(_agno_run_context, team),
                session_id=self._sub_session_id(_agno_run_context, "team", component_id),
            )
            return self._run_payload("team_id", component_id, response)
        except Exception as e:
            logger.exception("Failed to run team")
            return json.dumps({"error": str(e) or type(e).__name__})

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
        except StudioRunnerError as e:
            # Deliberate refusals with an actionable message; not failures to log.
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
                user_id=self._caller_user_id(_agno_run_context, wf),
                session_id=self._sub_session_id(_agno_run_context, "workflow", component_id),
            )
            return self._run_payload("workflow_id", component_id, response)
        except Exception as e:
            logger.exception("Failed to run workflow")
            return json.dumps({"error": str(e) or type(e).__name__})

    async def arun_agent(self, agent_id: str, message: str, _agno_run_context: Optional[RunContext] = None) -> str:
        """Async variant of run_agent.

        Args:
            agent_id (str): Id of the agent to run (a display name or its slug also resolves).
            message (str): The message to send.
        """
        # Resolution hits the DB synchronously; keep it off the event loop.
        try:
            agent = await asyncio.to_thread(self._agent_for_run, agent_id)
        except StudioRunnerError as e:
            # Deliberate refusals with an actionable message; not failures to log.
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
                user_id=self._caller_user_id(_agno_run_context, agent),
                session_id=self._sub_session_id(_agno_run_context, "agent", component_id),
            )
            return self._run_payload("agent_id", component_id, response)
        except Exception as e:
            logger.exception("Failed to run agent")
            return json.dumps({"error": str(e) or type(e).__name__})

    async def arun_team(self, team_id: str, message: str, _agno_run_context: Optional[RunContext] = None) -> str:
        """Async variant of run_team.

        Args:
            team_id (str): Id of the team to run (a display name or its slug also resolves).
            message (str): The message to send.
        """
        try:
            team = await asyncio.to_thread(self._team_for_run, team_id)
        except StudioRunnerError as e:
            # Deliberate refusals with an actionable message; not failures to log.
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
                user_id=self._caller_user_id(_agno_run_context, team),
                session_id=self._sub_session_id(_agno_run_context, "team", component_id),
            )
            return self._run_payload("team_id", component_id, response)
        except Exception as e:
            logger.exception("Failed to run team")
            return json.dumps({"error": str(e) or type(e).__name__})

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
        except StudioRunnerError as e:
            # Deliberate refusals with an actionable message; not failures to log.
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
                user_id=self._caller_user_id(_agno_run_context, wf),
                session_id=self._sub_session_id(_agno_run_context, "workflow", component_id),
            )
            return self._run_payload("workflow_id", component_id, response)
        except Exception as e:
            logger.exception("Failed to run workflow")
            return json.dumps({"error": str(e) or type(e).__name__})

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
        must not share a session row.

        The key is a digest rather than the three parts joined by a delimiter.
        Joining is not injective once a part can itself contain the delimiter --
        a runner dispatched by a runner produces exactly that -- so
        (`a--agent--b`, `c`) and (`a`, `b--agent--c`) would name one session and
        each component would read the other's history. A digest is also bounded,
        which the joined form is not: nested dispatch grows it without limit and
        MySQL caps session_id at 128 characters.

        A caller without a session (a direct Python call -- run_agent() has no
        session argument) gets None: no session id is passed to the target.
        Dispatch runs on a per-call copy (code-defined) or a per-call rebuild
        (DB-loaded), so each such run starts a session of its own. A component
        constructed with an explicit session_id keeps using it, which is the
        opt-in for continuity across sessionless calls."""
        if run_context is None or not getattr(run_context, "session_id", None):
            return None
        from agno.utils.string import hash_string_sha256

        # The caller's user is part of the key: two people can share one
        # caller session (a shared channel), and without this they would
        # share the target's session and read each other's history. The
        # sentinel holds a NUL so no real user id can collide with it.
        parts = (
            str(run_context.session_id),
            str(getattr(run_context, "user_id", None) or "\0anonymous"),
            component_type,
            component_id,
        )
        # Length-prefixed so no part can impersonate a boundary.
        key = "|".join(f"{len(part)}:{part}" for part in parts)
        return f"{component_type}-{hash_string_sha256(key)[:32]}"

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
            "status": run_status_string(run_output),
            "content": content,
        }
        requirements = serialized_paused_requirements(run_output)
        if requirements is not None:
            payload["requirements"] = requirements
        # Media artifacts cannot travel in a JSON tool result; count them so the
        # caller knows they exist (retrievable from the run via the platform).
        media = {
            kind: len(artifacts)
            for kind in ("images", "videos", "audio", "files")
            if (artifacts := getattr(run_output, kind, None))
        }
        # response_audio is the model's spoken reply, a single object rather than a
        # list. A voice run puts its whole answer there and leaves content empty, so
        # without this the result reads as a successful run that said nothing.
        if getattr(run_output, "response_audio", None) is not None:
            media["response_audio"] = 1
        if media:
            payload["media"] = media
        return json.dumps(payload, default=str)
