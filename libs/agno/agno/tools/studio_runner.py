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

Mount it INSTEAD of StudioTools, not beside it. StudioTools embeds this same
toolkit and already exposes list_agents/list_teams/list_workflows/run_agent, and
agno's tool namespace is flat: co-mounting collapses the overlapping names to
whichever toolkit the tools list holds first, and a warning names the skipped
one. Two runners scoped to different component lists collapse the same way, so
the loser's allowlist becomes unreachable. ``name=`` names the toolkit, not its
functions, so it does not disambiguate them.

Semantics:
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
      DB-loaded components are reconstructed per call already.
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

from agno.exceptions import ComponentRehydrationError
from agno.run import RunContext
from agno.run.utils import run_status_string, serialized_paused_requirements
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


def _references_executors(value: Any) -> bool:
    """True when a stored workflow config references a registry function step."""
    if isinstance(value, dict):
        if value.get("executor_ref"):
            return True
        return any(_references_executors(v) for v in value.values())
    if isinstance(value, list):
        return any(_references_executors(v) for v in value)
    return False


def _references_idless_components(value: Any) -> bool:
    """True when a stored config carries an agent/team reference whose id is
    null. Serialization writes the referenced component's id even when it is
    None, and a code-defined component that never ran has no id, so a null id
    marks a component only the registry can supply."""
    if isinstance(value, dict):
        if ("agent_id" in value and not value["agent_id"]) or ("team_id" in value and not value["team_id"]):
            return True
        return any(_references_idless_components(v) for v in value.values())
    if isinstance(value, list):
        return any(_references_idless_components(v) for v in value)
    return False


def _component_references(component_type: str, config: Dict[str, Any]) -> List[tuple]:
    """(type, id) pairs for the components a stored config references by id."""
    refs: List[tuple] = []
    if component_type == "team":
        for member in config.get("members") or []:
            if not isinstance(member, dict):
                continue
            if member.get("team_id"):
                refs.append(("team", str(member["team_id"])))
            elif member.get("agent_id"):
                refs.append(("agent", str(member["agent_id"])))
    if component_type == "workflow":

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                if value.get("agent_id"):
                    refs.append(("agent", str(value["agent_id"])))
                if value.get("team_id"):
                    refs.append(("team", str(value["team_id"])))
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(config.get("steps"))
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

    def _iter_agents(self, for_dispatch: bool = False) -> List["Agent"]:
        """Code-defined agents: passed-in list, else registry.

        The registry half is opt-in for dispatch (``include_all_components``).
        A registry is passed so persisted components can rehydrate their tools
        and members, which is not the same as consenting to run every agent the
        application happens to define -- and ``list_*`` report the database
        only, so those agents are reachable without being discoverable. An
        explicit ``agents_list`` is itself the allowlist and always runs.
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
        return self._load_agent_from_db(resolved, for_dispatch=for_dispatch) if resolved is not None else None

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
        return self._load_team_from_db(resolved, for_dispatch=for_dispatch) if resolved is not None else None

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
        return self._load_workflow_from_db(resolved, for_dispatch=for_dispatch) if resolved is not None else None

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
        lost = type(fresh) is not type(component)
        for attribute in ("id", "name", "model", "instructions"):
            original = getattr(component, attribute, None)
            copied = getattr(fresh, attribute, None)
            # A rebuild that drops a field leaves it None; equality would also
            # reject a model instance the copier legitimately rebuilt.
            lost = (
                lost
                or (original is not None and copied is None)
                or (attribute in ("id", "name") and original != copied)
            )
        if lost:
            raise DispatchCopyError(
                f"deep_copy of '{label}' lost its identity. "
                "Give the class a deep_copy that rebuilds it, or store the component in the database."
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
    def _member_divergence(original: Any, fresh: Any, depth: int = 0) -> Optional[str]:
        """How the copy's member list differs in shape from the original's, else None.

        Whether a member is aliased is _shared_member's question; this one is
        whether the copy holds the same members at all. A copier that drops a
        member or rebuilds it as a different component has not produced the
        component that was asked for, and neither shows up as sharing."""
        if depth > 12:  # A cycle or pathological nesting; stop rather than recurse forever.
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
            for attribute in ("id", "name"):
                if getattr(original_member, attribute, None) != getattr(fresh_member, attribute, None):
                    return f"member '{member_label}' lost its {attribute}"
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
        if any(a is agent for a in self._iter_agents(for_dispatch=True)):
            return self._fresh_copy(agent)
        self._warn_if_model_rebuilt(agent, "agent", agent_id)
        return agent

    def _team_for_run(self, team_id: str) -> Optional["Team"]:
        team = self._find_team(team_id, for_dispatch=True)
        if team is None:
            self._refuse_if_only_reachable_with_include_all("team", team_id)
            return None
        if any(t is team for t in self._iter_teams(for_dispatch=True)):
            return self._fresh_copy(team)
        self._warn_if_model_rebuilt(team, "team", team_id)
        return team

    def _workflow_for_run(self, workflow_id: str) -> Optional["Workflow"]:
        wf = self._find_workflow(workflow_id, for_dispatch=True)
        if wf is None:
            self._refuse_if_only_reachable_with_include_all("workflow", workflow_id)
            return None
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
        key = "members" if component_type == "team" else "steps"
        if component_type not in ("team", "workflow") or not _references_idless_components(config.get(key)):
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
        key = f"{component_type}:{component_id}"
        if key in _seen:
            return
        _seen.add(key)
        needs: List[str] = []
        if config.get("tools"):
            needs.append("tools")
        if config.get("knowledge"):
            needs.append("knowledge")
        if isinstance(config.get("input_schema"), str) or isinstance(config.get("output_schema"), str):
            needs.append("schemas")
        if component_type == "workflow" and _references_executors(config.get("steps")):
            needs.append("function steps")
        if needs:
            raise ComponentNeedsRegistryError(
                f"{component_type.capitalize()} '{component_id}' references registry-backed resources "
                f"({', '.join(needs)}); construct StudioRunnerTools with the registry to run it."
            )
        from agno.db.base import ComponentType

        for ref_type, ref_id in _component_references(component_type, config):
            ref_config = self._load_config_from_db(ref_id, component_type=ComponentType(ref_type))
            if ref_config is None:
                raise ComponentNeedsRegistryError(
                    f"{component_type.capitalize()} '{component_id}' references {ref_type} '{ref_id}', "
                    "which is not stored in the database (a code-defined component); "
                    "construct StudioRunnerTools with the registry to run it."
                )
            self._require_registry_for(ref_type, ref_id, ref_config, _seen)

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
                    if isinstance(tool, Function) and tool.entrypoint is None
                }
            )
            if unresolved:
                missing.append(f"tools ({', '.join(unresolved)})")
            elif len(rebuilt_tools) < len(declared_tools):
                missing.append(f"tools ({len(declared_tools) - len(rebuilt_tools)} of {len(declared_tools)} dropped)")

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

        if node is None or depth > 12:
            return None
        seen = set() if seen is None else seen
        if id(node) in seen:
            return None
        seen.add(id(node))

        children: List[Any] = list(getattr(node, "members", None) or [])
        for step in getattr(node, "steps", None) or []:
            for attribute in ("agent", "team"):
                child = getattr(step, attribute, None)
                if child is not None:
                    children.append(child)
            for nested_attribute in ("steps", "else_steps", "choices"):
                children.extend(getattr(step, nested_attribute, None) or [])

        for child in children:
            unresolved = sorted(
                {
                    str(getattr(tool, "name", None) or "?")
                    for tool in (getattr(child, "tools", None) or [])
                    if isinstance(tool, Function) and tool.entrypoint is None
                }
            )
            if unresolved:
                label = getattr(child, "id", None) or getattr(child, "name", None) or type(child).__name__
                return f"{label}: tools ({', '.join(unresolved)})"
            found = StudioRunnerTools._unresolved_below(child, depth + 1, seen)
            if found is not None:
                return found
        return None

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

    def _warn_if_declared_db_dropped(self, config: Dict[str, Any], component_type: str, component_id: str) -> None:
        """Log when a config declared a db that could not be reconstructed.

        db_from_dict rebuilds postgres, sqlite and clickhouse configs that
        carry their connection field; anything else resolves through the
        registry. When neither supplies it, the component falls back to the
        catalog db, so its sessions and memory land elsewhere than configured."""
        db_config = config.get("db")
        if not isinstance(db_config, dict):
            return
        logger.warning(
            "StudioRunnerTools: %s '%s' declares db '%s', which could not be reconstructed; "
            "the component falls back to the catalog db.",
            component_type,
            component_id,
            db_config.get("id") or db_config.get("type") or "unknown",
        )

    def _require_isolated_steps(self, wf: "Workflow", workflow_id: str) -> None:
        """Refuse to dispatch a rebuilt workflow that holds a shared registry
        instance in a step.

        Step.from_dict keeps the shared registry agent/team when its deep_copy
        raises; dispatching that instance would let per-run mutation cross
        callers. Reads and edits load the same workflow without this check, so
        the offending step stays inspectable and editable."""
        if self.registry is None:
            return
        shared: List[Any] = list(self.registry.agents or []) + list(self.registry.teams or [])
        if not shared:
            return

        def shared_within(node: Any, depth: int = 0) -> Optional[Any]:
            """The shared registry instance held at or below this executor. A step
            whose team is a fresh copy still leaks if one of that team's own
            members is the registry singleton.

            A member is only a leak when it could have been copied, the same rule
            _shared_member applies: a member with no deep_copy is shared by design,
            because a remote proxy holds no per-run state to isolate. The executor
            itself is judged without that exemption, as it was before."""
            if node is None or depth > 12:
                return None
            is_shared = any(node is instance for instance in shared)
            if is_shared and (depth == 0 or callable(getattr(node, "deep_copy", None))):
                return node
            for member in getattr(node, "members", None) or []:
                found = shared_within(member, depth + 1)
                if found is not None:
                    return found
            return None

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

        config = self._load_config_from_db(agent_id, version=version, component_type=ComponentType.AGENT)
        if config is None:
            return None
        self._require_registry_for("agent", agent_id, config)
        from agno.agent.agent import Agent

        try:
            agent = Agent.from_dict(config, registry=self.registry, strict=for_dispatch)
            agent.id = agent_id
            # The catalog db is a fallback only: a config-declared db (resolved
            # by from_dict, possibly with table overrides) must keep winning.
            if getattr(agent, "db", None) is None:
                self._warn_if_declared_db_dropped(config, "agent", agent_id)
                agent.db = self.db
        except ComponentRehydrationError:
            raise
        except Exception:
            logger.warning("StudioRunnerTools: Agent.from_dict failed for %s", agent_id, exc_info=True)
            return None
        if for_dispatch:
            self._require_faithful_rebuild(agent, config, "agent", agent_id)
        return agent

    def _load_team_from_db(
        self, team_id: str, version: Optional[int] = None, for_dispatch: bool = False
    ) -> Optional["Team"]:
        from agno.db.base import ComponentType

        config = self._load_config_from_db(team_id, version=version, component_type=ComponentType.TEAM)
        if config is None:
            return None
        if for_dispatch:
            # Dispatch only: a null reference cannot be resolved, but the component
            # still has to load so the bad reference can be seen and repaired.
            self._require_resolvable_member_ids("team", team_id, config)
        self._require_registry_for("team", team_id, config)
        from agno.team.team import Team

        try:
            team = Team.from_dict(config, db=self.db, registry=self.registry, strict=for_dispatch)
            team.id = team_id
            # The catalog db is a fallback only; a config-declared db wins.
            if getattr(team, "db", None) is None:
                self._warn_if_declared_db_dropped(config, "team", team_id)
                team.db = self.db
        except ComponentRehydrationError:
            raise
        except Exception:
            logger.warning("StudioRunnerTools: Team.from_dict failed for %s", team_id, exc_info=True)
            return None
        if for_dispatch:
            self._require_faithful_rebuild(team, config, "team", team_id)
        return team

    def _load_workflow_from_db(
        self, workflow_id: str, version: Optional[int] = None, for_dispatch: bool = False
    ) -> Optional["Workflow"]:
        from agno.db.base import ComponentType

        config = self._load_config_from_db(workflow_id, version=version, component_type=ComponentType.WORKFLOW)
        if config is None:
            return None
        if for_dispatch:
            # Dispatch only: a null reference cannot be resolved, but the component
            # still has to load so the bad reference can be seen and repaired.
            self._require_resolvable_member_ids("workflow", workflow_id, config)
        self._require_registry_for("workflow", workflow_id, config)
        from agno.workflow.workflow import Workflow

        try:
            wf = Workflow.from_dict(config, db=self.db, registry=self.registry, strict=for_dispatch)
            wf.id = workflow_id
            # The catalog db is a fallback only; a config-declared db wins.
            if getattr(wf, "db", None) is None:
                self._warn_if_declared_db_dropped(config, "workflow", workflow_id)
                wf.db = self.db
        except ComponentRehydrationError:
            raise
        except Exception:
            logger.warning("StudioRunnerTools: Workflow.from_dict failed for %s", workflow_id, exc_info=True)
            return None
        if for_dispatch:
            self._require_faithful_rebuild(wf, config, "workflow", workflow_id)
        return wf

    def _load_config_from_db(
        self,
        component_id: str,
        version: Optional[int] = None,
        component_type: Optional["ComponentType"] = None,
    ) -> Optional[Dict[str, Any]]:
        """Load a component's config by id.

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
            return json.dumps({"error": str(e) or type(e).__name__})

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
                user_id=_agno_run_context.user_id if _agno_run_context is not None else None,
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
                user_id=_agno_run_context.user_id if _agno_run_context is not None else None,
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
                user_id=_agno_run_context.user_id if _agno_run_context is not None else None,
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
                user_id=_agno_run_context.user_id if _agno_run_context is not None else None,
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
                user_id=_agno_run_context.user_id if _agno_run_context is not None else None,
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
                user_id=_agno_run_context.user_id if _agno_run_context is not None else None,
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

        parts = (str(run_context.session_id), component_type, component_id)
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
