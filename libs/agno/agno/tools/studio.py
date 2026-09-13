"""StudioTools -- the control plane an in-platform builder uses to compose
agents, teams, and workflows.

Uses the AgentOS Registry (tools, models, functions, knowledge, schemas) and
the component catalog to create, edit, version, validate, and execute
components described in natural language. Every tool returns one JSON
envelope (StudioResult: ok / status / data / error{code} / warnings) so a
model branches on stable codes instead of parsing prose.

Typical use:
    from agno.tools.studio import StudioTools

    builder = Agent(
        model=Claude(id="claude-sonnet-4-6"),
        tools=[StudioTools(registry=registry, db=db)],
    )

Every tool returns a StudioResult envelope EXCEPT run_agent/run_team/
run_workflow and the mounted schedule-management tools, which return the
runner's and scheduler's flat payloads (documented on each tool) - a run
result is the component's output, not a control-plane response.

Lifecycle:
    * create_* writes version 1 as a DRAFT unless publish=True. Drafts are
      readable, editable, and previewable (run_*(version=)), but never serve
      users, schedules, or dispatch until published.
    * edit_* appends a new immutable version (draft, or published with
      publish=True); name= renames without changing the id; expected_version
      is an optional compare-and-set guard. Omit a field to keep it, pass an
      empty string to clear text or detach a reference, an empty list to
      clear tools.
    * publish_component promotes a draft and re-points the live version;
      set_current_version re-points among published versions; archive_component
      retires a component (id reserved, history kept, dependents refuse);
      restore_component reverses an archive. Only unpublished drafts can be
      deleted; version numbers are never reused.
    * validate_component dry-runs the stored config against the live registry
      exactly as dispatch would -- the cheap check before publish.
    * run_* execute as the current user, one sub-session per conversation;
      PAUSED results carry their unresolved requirements. Execution lives in
      StudioRunnerTools (agno.tools.studio_runner), which platforms mount
      standalone as a dispatch-only surface.

Identity and ownership:
    * The framework injects the caller's RunContext; components and schedules
      created through Studio are owned by that user. A draft-only component
      and every schedule answer not-found to other owners; publishing puts a
      component on the platform, readable and runnable by every user, while
      mutation stays owner-scoped (not_owner). Shared (unowned) rows refuse
      mutation for scoped actors.

Palette policy:
    * Declared registry tools are buildable. Tools that arrived via the
      AgentOS fold (every registered agent's own wiring) are resolvable but
      NOT buildable unless allowed via allowed_tools; denied_tools always
      wins; composing a component that itself carries StudioTools is refused
      the same way. list_tools reports buildable and source per row.

Enable flags:
    * create_agents/create_teams/create_workflows are all True by default;
      versions=True by default (set False to publish every edit immediately and
      hide the version tools); schedules=False by default.
    * requires_confirmation_tools defaults to the deletion-shaped operations
      (archive_component, delete_version, delete_schedule); a consumer may
      replace the list, including with [].

Persistence:
    * Studio saves ONLY the component it creates/edits. It does NOT cascade to
      member agents or step agents -- those are code-defined (registry /
      passed-in lists) or separately persisted by a prior create_*.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Sequence, Set, Union

from agno.exceptions import SchemaMismatchError
from agno.run import RunContext
from agno.tools.function import Function
from agno.tools.studio_runner import AmbiguousComponentNameError, StudioRunnerError, StudioRunnerTools, _slugify
from agno.tools.studio_schema import WorkflowStepSpec, error_result, ok_result
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, log_warning, logger
from agno.utils.string import generate_component_id_from_name, validate_component_id

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

# How many same-name rows a display-name lookup pulls before calling it
# ambiguous. One display name can match several owners now that published
# components are platform-visible, so the window has to be wider than the old
# two -- the actor's own has to be findable among the collisions.
_NAME_MATCH_LIMIT = 20

_NAME_MATCH_PAGES = 10


def _is_mcp_toolkit(tool: Any) -> bool:
    """Checked by class name so the optional mcp extra is never imported here."""
    return any(c.__name__ == "MCPTools" for c in type(tool).__mro__)


# Extra headroom on top of a toolkit's own timeout_seconds for the on-demand
# connect: covers transport setup/teardown around the timed client calls.
_MCP_CONNECT_SLACK_SECONDS = 5.0

# One connect pass at a time, process-wide: MCPTools instances stage transport
# state on unlocked attributes, and a registry (and its toolkits) can be shared
# across StudioTools instances, so this cannot be per-instance state.
_MCP_CONNECT_LOCK = threading.Lock()

# Connect threads abandoned at their join deadline, by toolkit id. A toolkit
# held by a live abandoned thread cannot be safely reconnected -- a second
# connect would interleave with the first on the toolkit's unlocked transport
# state -- so it stays refused until that thread dies. Guarded by
# _MCP_CONNECT_LOCK; entries are pruned once their thread has exited.
_MCP_CONNECT_ZOMBIES: Dict[int, threading.Thread] = {}


def _version_or_latest(version: Optional[int]) -> Optional[int]:
    """Read a "which version" argument, treating 0 as omitted.

    Version numbers start at 1, so on an argument that selects a version 0 is never
    valid and only ever means the model defaulted an optional integer it should have
    left out. Every such argument is documented "omit for the latest", so 0 is answered
    the way omitting it is answered rather than with a version that does not exist.

    Booleans are not versions: ``False == 0`` in Python and a lax JSON coercion can
    deliver one, so it is refused here the same way the live-pointer guard refuses it.

    This is only for arguments that name a version to act on. It must never be applied
    to ``expected_current_version``, where 0 is the compare-and-set spelling for "I
    expect no live version" (``agno.db.base.NO_LIVE_VERSION``) and carries a real guard.
    """
    if isinstance(version, bool) or version != 0:
        return version
    log_debug("StudioTools: version=0 is not a version; reading it as omitted (the latest).")
    return None


def _own_row_across_pages(list_components, actor: Optional[str], **query: Any) -> tuple:
    """(rows, total) for a name query, paged until the actor's own row is seen.

    The window is ordered newest-first and the owner filter is applied after
    it, so a caller whose own component is older than the first page of
    same-named rows never sees it -- and share-on-publish makes same-named
    rows from other owners ordinary. Paging stops as soon as an owned row
    turns up, and is bounded: past the bound the ambiguous-reference answer
    is the honest one.
    """
    rows, total = list_components(limit=_NAME_MATCH_LIMIT, **query)
    if actor is None or total <= _NAME_MATCH_LIMIT:
        return rows, total
    if any(row.get("user_id") == actor for row in rows):
        return rows, total
    for page in range(1, _NAME_MATCH_PAGES):
        offset = page * _NAME_MATCH_LIMIT
        if offset >= total:
            break
        more, _ = list_components(limit=_NAME_MATCH_LIMIT, offset=offset, **query)
        if not more:
            break
        rows = rows + more
        if any(row.get("user_id") == actor for row in more):
            break
    return rows, total


class _UnresolvedFactory:
    """Marker for a tools/members factory the composition guard could not run.

    The guard proves the ABSENCE of the control plane, so a factory it cannot
    resolve is treated as if it carried one: an async factory, a raising
    factory, or one asking for an argument the runtime does not inject is
    refused rather than composed on the assumption that it is harmless.
    """

    __slots__ = ()


_UNRESOLVED_FACTORY = _UnresolvedFactory()


class _ToolsNotFoundError(ValueError):
    """tool_names include names absent from the registry (spec 3.4: distinct
    from tool_not_allowed, which is a palette refusal for a name that exists)."""


class _LiveComponentView(Sequence[Any]):
    """A sequence view over a component resolver, read at access time.

    SchedulerTools' code-defined probe reads its include_* sequences on every
    call; handing it these views keeps the probe aligned with the run tools'
    resolution (explicit lists, else the registry) even when the registry is
    populated after the toolkit is built.
    """

    def __init__(self, resolve: Callable[[], List[Any]]):
        self._resolve = resolve

    def __getitem__(self, index):  # type: ignore[no-untyped-def]
        return self._resolve()[index]

    def __iter__(self):
        return iter(self._resolve())

    def __len__(self) -> int:
        return len(self._resolve())


class StudioTools(Toolkit):
    """Toolkit that lets an agent compose agents, teams, and workflows.

    Args:
        registry: Registry holding models, tools, databases, and code-defined
            agents/teams available for composition.
        db: Database for persisting components. Falls back to ``registry.dbs[0]``.
        include_agents: Optional live list (e.g. ``agent_os.agents``) of the
            code-defined agents to include alongside the registry's own, used
            for discovery in ``list_agents()``. Studio-created components are
            NOT appended to this list -- they are DB components, so appending
            would duplicate them in AgentOS's ``/agents`` response.
        include_teams: Same as ``include_agents`` but for teams.
        include_workflows: Same as ``include_agents`` but for workflows.
        default_model_id: Model id to use when a caller omits one.
        default_num_history_runs: History depth for created agents and teams
            when a caller omits ``num_history_runs``. None lets the
            component's own default apply.
        create_agents: Expose the agent build operations. Defaults to True.
        create_teams: Expose the team build operations. Defaults to True.
        create_workflows: Expose the workflow build operations. Defaults to
            True. Set any of the three False to keep that component type out of
            the palette; setting all three False leaves only discovery tools.
        versions: Expose versioning tools (list_versions, publish_component,
            set_current_version, delete_version). Defaults to True, so create_*
            and edit_* write drafts that serve nobody until publish_component
            promotes them. Set False to publish every edit immediately and hide
            the version tools.
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
        allowed_tools: Extra names a caller may build with even though the
            palette would refuse them. Additive, never exhaustive: declared
            registry tools are buildable without being listed here, so this
            list cannot narrow the palette -- that is what denied_tools is
            for. Two kinds of name are accepted: a folded tool's name, which
            promotes it into the build palette, and the id of a component
            that itself carries StudioTools, which permits composing it into
            teams and workflows -- a control-plane grant, so list one
            deliberately. denied_tools still wins over both.
        denied_tools: Names no caller may build with, whatever their source.
            A denied toolkit covers its member functions too.
        max_dispatch_depth: How many runner-dispatch hops one request may
            chain through the run tools (default 2). 1 means components this
            toolkit runs may not dispatch further; 0 disables dispatch while
            keeping discovery. Bounds depth, not fan-out. The cycle guard --
            no component runs again while it is already running in the same
            dispatch tree -- is always on regardless.
        self_dispatch: "never" (default) refuses a component dispatching
            itself outright. "once" allows a self-run one nested level deep
            (a clean-context self-consult on its own derived session); the
            nested run inherits its caller in the dispatch lineage, so it can
            never re-enter, and indirect cycles stay refused in both modes.
            Per dispatch call, not per conversation: a run that calls the
            tool twice starts two such bounded self-runs.
    """

    def __init__(
        self,
        registry: "Registry",
        db: Optional["BaseDb"] = None,
        include_agents: Optional[List["Agent"]] = None,
        include_teams: Optional[List["Team"]] = None,
        include_workflows: Optional[List["Workflow"]] = None,
        default_model_id: Optional[str] = None,
        default_num_history_runs: Optional[int] = None,
        create_agents: bool = True,
        create_teams: bool = True,
        create_workflows: bool = True,
        versions: bool = True,
        schedules: bool = False,
        list_limit: int = 100,
        allowed_tools: Optional[List[str]] = None,
        denied_tools: Optional[List[str]] = None,
        max_dispatch_depth: int = 2,
        self_dispatch: Literal["never", "once"] = "never",
        **kwargs: Any,
    ):
        self.registry = registry
        # The explicit db wins; otherwise the registry's is adopted lazily on
        # first access (see the db property). Studio is constructed before
        # AgentOS - it is a tool on an agent the OS serves - and registry.dbs
        # is filled by AgentOS afterwards, so an __init__ snapshot would leave
        # every write answering db_not_configured forever.
        self._db: Optional["BaseDb"] = db
        self.include_agents = include_agents
        self.include_teams = include_teams
        self.include_workflows = include_workflows
        # Rehydration resolves code-defined references through the registry
        # only; a component reachable solely via these live lists could be
        # referenced at create time but never reload. Make the lists visible.
        pending_mirrors: List[tuple] = []
        for source, bucket, source_name in (
            (include_agents, registry.agents, "include_agents"),
            (include_teams, registry.teams, "include_teams"),
            (include_workflows, registry.workflows, "include_workflows"),
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
        self.list_limit = list_limit
        # Palette policy: declared registry tools are buildable; folded tools
        # are resolvable but not buildable unless allowed; denials always win.
        self._allowed_tools: Set[str] = set(allowed_tools or [])
        self._denied_tools: Set[str] = set(denied_tools or [])

        # Execution and component resolution live on StudioRunnerTools -- the
        # standalone dispatch toolkit. Studio registers its run tools from this
        # embedded instance and delegates its own lookups to it, so the builder
        # and a dispatcher resolve and run components one way.
        self._runner_tools = StudioRunnerTools(
            registry=registry,
            db=db,
            include_agents=include_agents,
            include_teams=include_teams,
            include_workflows=include_workflows,
            # The Studio holds the registry as its build palette and its run_* are
            # the smoke test for what it just composed, so its reach over registry
            # components is the point rather than an accident. A standalone runner
            # mounted on a router gets the narrower default.
            include_all_components=True,
            # That same reach is what makes an unbounded dispatch chain
            # reachable from one message, so the bound rides along with it.
            max_dispatch_depth=max_dispatch_depth,
            self_dispatch=self_dispatch,
            list_limit=list_limit,
        )

        self.enable_agents = create_agents
        self.enable_teams = create_teams
        self.enable_workflows = create_workflows
        self.enable_versions: bool = versions
        self.enable_schedules: bool = schedules
        # Schedule management is shared with SchedulerTools; Studio owns only
        # create_schedule (component targets, internally built endpoint).
        self._scheduler_tools: Optional["SchedulerTools"] = None
        if self.enable_schedules:
            from agno.tools.scheduler import SchedulerTools

            # The lists ride along: without them the embedded toolkit's own
            # refusals build a probe from nothing, so enable_schedule would
            # refuse a code-defined target that create_schedule just allowed.
            self._scheduler_tools = SchedulerTools(
                db=self._db,
                # A bound method, not a lambda: deepcopy treats plain functions
                # as atomic but rebinds methods through its memo, so a
                # deep-copied toolkit's scheduler resolves through the COPY.
                db_resolver=self._registry_db,
                # Live views, not the raw lists: the embedded toolkit's own
                # refusals build a code-defined probe from these, and that
                # probe must see the same set the run tools resolve from
                # (explicit lists, else the registry) - or enable_schedule
                # refuses a target create_schedule just allowed.
                include_agents=_LiveComponentView(self._runner_tools._iter_agents),
                include_teams=_LiveComponentView(self._runner_tools._iter_teams),
                include_workflows=_LiveComponentView(self._runner_tools._iter_workflows),
            )

        tools: List[Callable] = [
            # Discovery -- always available regardless of flags.
            self.list_models,
            self.list_tools,
            self.list_functions,
            self.list_knowledge,
            self.list_schemas,
            self.list_learning,
            self.list_components,
            self.get_component,
        ]

        if self.enable_agents:
            tools.extend([self.create_agent, self.edit_agent, self.run_agent])
        if self.enable_teams:
            tools.extend([self.create_team, self.edit_team, self.run_team])
        if self.enable_workflows:
            tools.extend([self.create_workflow, self.edit_workflow, self.run_workflow])

        tools.append(self.validate_component)
        tools.extend([self.archive_component, self.restore_component])

        # Versioning tools are opt-out: without them, edits publish
        # immediately and the draft ladder is invisible to the model.
        if self.enable_versions:
            tools.extend(
                [
                    self.list_versions,
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
                    self.update_schedule,
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
            (self.alist_knowledge, "list_knowledge"),
            (self.alist_schemas, "list_schemas"),
            (self.alist_learning, "list_learning"),
            (self.alist_components, "list_components"),
            (self.aget_component, "get_component"),
        ]
        if self.enable_agents:
            async_tools.extend(
                [(self.acreate_agent, "create_agent"), (self.aedit_agent, "edit_agent"), (self.arun_agent, "run_agent")]
            )
        if self.enable_teams:
            async_tools.extend(
                [(self.acreate_team, "create_team"), (self.aedit_team, "edit_team"), (self.arun_team, "run_team")]
            )
        if self.enable_workflows:
            async_tools.extend(
                [
                    (self.acreate_workflow, "create_workflow"),
                    (self.aedit_workflow, "edit_workflow"),
                    (self.arun_workflow, "run_workflow"),
                ]
            )
        async_tools.append((self.avalidate_component, "validate_component"))
        async_tools.extend(
            [(self.aarchive_component, "archive_component"), (self.arestore_component, "restore_component")]
        )
        if self.enable_versions:
            async_tools.extend(
                [
                    (self.alist_versions, "list_versions"),
                    (self.apublish_component, "publish_component"),
                    (self.aset_current_version, "set_current_version"),
                    (self.adelete_version, "delete_version"),
                ]
            )
        if self._scheduler_tools is not None:
            async_tools.extend(
                [
                    (self.acreate_schedule, "create_schedule"),
                    (self.aupdate_schedule, "update_schedule"),
                    (self._scheduler_tools.alist_schedules, "list_schedules"),
                    (self._scheduler_tools.aget_schedule, "get_schedule"),
                    (self._scheduler_tools.aget_schedule_runs, "get_schedule_runs"),
                    (self._scheduler_tools.atrigger_schedule, "trigger_schedule"),
                    (self._scheduler_tools.aenable_schedule, "enable_schedule"),
                    (self._scheduler_tools.adisable_schedule, "disable_schedule"),
                    (self._scheduler_tools.adelete_schedule, "delete_schedule"),
                ]
            )

        # Instructions may only name tools this configuration registers:
        # naming an unregistered tool tells the model to hallucinate a call.
        # The gates mirror the registration blocks above - versions for the
        # publish ladder, the enable_* trio for create/edit/run prose, the
        # scheduler for the schedules line.
        authoring = self.enable_agents or self.enable_teams or self.enable_workflows
        # Name only the types this configuration can actually build. The flags
        # are independently settable, so a workflows-only palette that advertises
        # composing agents and teams sends the model after create_agent, which
        # was never registered.
        buildable = [
            noun
            for noun, enabled in (
                ("agents", self.enable_agents),
                ("teams", self.enable_teams),
                ("workflows", self.enable_workflows),
            )
            if enabled
        ]
        if len(buildable) > 2:
            # Keep the serial comma the full palette has always used, so the
            # default configuration's prompt is unchanged by this gating.
            composable = f"{', '.join(buildable[:-1])}, and {buildable[-1]}"
        elif len(buildable) == 2:
            composable = f"{buildable[0]} and {buildable[1]}"
        else:
            composable = buildable[0] if buildable else ""
        instruction_lines: List[str] = []
        if authoring and self.enable_versions:
            instruction_lines.append(
                f"Compose {composable} from registry primitives. The lifecycle: create "
                "(a draft, unless publish=true) -> validate_component -> publish_component. Only the "
                "published version serves runs and schedules. Drafts are private to you; publishing "
                "puts the component on the platform, where every user can find and run it (but only "
                "you can edit it)."
            )
        elif authoring:
            instruction_lines.append(
                f"Compose {composable} from registry primitives. The lifecycle: create "
                "-> validate_component. There is no draft stage and no publish step here: every create "
                "and edit is published immediately as the new current version, on the platform where "
                "every user can find and run it (but only you can edit it)."
            )
        instruction_lines.append(
            "Discovery first: list_tools/list_functions/list_models names are exact and "
            "case-sensitive; only buildable tools may be wired. Never guess a name."
        )
        if authoring:
            instruction_lines.append(
                "get_component reads the LATEST version (the one you just edited); call it before "
                "every edit and pass only the fields that change. Renaming is edit with name=; the id "
                "never changes. Omit = keep, empty string = clear text, empty list = clear tools."
            )
        if self.enable_versions:
            instruction_lines.append(
                "Version history is immutable: edits append, publish promotes, set_current_version "
                "re-points between published versions, archive_component retires (restore_component "
                "reverses it). Nothing is ever deleted except unpublished drafts."
            )
        else:
            instruction_lines.append(
                "Version history is immutable: every edit appends the next version and makes it "
                "current at once. archive_component retires a component (restore_component reverses "
                "it); nothing is ever deleted."
            )
        if authoring and self.enable_versions:
            instruction_lines.append(
                "Run tools execute as the current user; pass version= to preview a draft before "
                "publishing. A PAUSED result waits on human approval: relay its requirements and keep "
                "the run_id and session_id for the resume."
            )
        elif authoring:
            instruction_lines.append(
                "Run tools execute as the current user; pass version= to pin an earlier published "
                "version. A PAUSED result waits on human approval: relay its requirements and keep "
                "the run_id and session_id for the resume."
            )
        if self._scheduler_tools is not None:
            instruction_lines.append(
                "Schedules: create_schedule targets an existing component by target_type "
                "('agent'/'team'/'workflow') + target_id (ids from list_components) and requires a "
                "message. Cron is 5-field; timezone is an IANA name. trigger_schedule queues an "
                "enabled schedule to run now via the platform poller."
            )

        # Deletion-shaped operations pause for a human by default; a consumer
        # may replace this list (including with []) but is never forced.
        registered_names = {t.__name__ for t in tools} | {name for _, name in async_tools}
        kwargs.setdefault(
            "requires_confirmation_tools",
            [n for n in ("archive_component", "delete_version", "delete_schedule") if n in registered_names],
        )
        # The toolkit ships instructions, so default them on; a consumer may
        # still pass add_instructions=False.
        kwargs.setdefault("add_instructions", True)

        super().__init__(
            name="studio",
            tools=tools,
            async_tools=async_tools,
            instructions="\n".join(instruction_lines),
            **kwargs,
        )

    @property
    def db(self) -> Optional["BaseDb"]:
        if self._db is not None:
            return self._db
        # Resolved on every access, never memoized. Studio is built before
        # AgentOS, so a single read before the OS declares its catalog db -- a
        # log line, a debug print, a health check -- would otherwise pin this
        # toolkit to whatever registry.dbs held at that moment for the life of
        # the process, and the declaration that follows would do nothing. An
        # explicitly passed db is still authoritative and still short-circuits.
        return self.registry.resolve_component_db()

    @db.setter
    def db(self, value: Optional["BaseDb"]) -> None:
        self._db = value

    def _registry_db(self) -> Optional["BaseDb"]:
        return self.db

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
            raise _ToolsNotFoundError(f"Tools not found in registry: {missing}")
        failed_toolkit_ids = self._connect_unconnected_mcp_toolkits(resolved)
        # Persisting a component serializes each toolkit's functions; a toolkit
        # with none (e.g. an MCP toolkit whose on-demand connection failed)
        # would be silently dropped from the config, permanently -- and a
        # toolkit whose connect attempt failed or was abandoned may hold a
        # PARTIAL function list. Refuse both instead.
        empty_toolkits = [
            t.name for t in resolved if isinstance(t, Toolkit) and (not t.functions or id(t) in failed_toolkit_ids)
        ]
        if empty_toolkits:
            raise ValueError(
                f"Toolkits have no functions and cannot be persisted: {empty_toolkits}. "
                "An MCP toolkit has no functions until it is connected; Studio connects "
                "unconnected registry MCP toolkits on demand, so an MCP toolkit named here "
                "failed to connect or its server exposes no tools. Any other toolkit named "
                "here was registered without functions."
            )
        return resolved

    def _connect_unconnected_mcp_toolkits(self, resolved: List[Any]) -> Set[int]:
        """Fetch the function list of registry MCP toolkits nothing has connected.

        A registry MCP toolkit has no functions until something connects it. Under
        AgentOS the server lifespan does that at startup, but a standalone process
        (script, notebook, eval run) has no lifespan, so the toolkit reaches
        persist time empty and the guard in _resolve_tools would refuse a build
        that succeeds against the running server. Persisting needs the toolkit's
        function list, not a live session, so each such toolkit is connected on a
        short-lived private event loop and released again before that loop goes
        away: close() keeps the registered functions, and a released toolkit
        attached to a component as an MCPTools instance reconnects per run,
        while a session left bound to the dead private loop would break the
        toolkit's later tool calls in this process. (A component rehydrated
        from the DB carries bare Functions, which no run path reconnects:
        standalone dispatch of the built component still needs the registry
        toolkit connected by a server lifespan or the eval runner's mcp_tools.)

        The dedicated thread serves every caller shape at once: a sync Studio
        tool on a worker thread (no loop in this thread, but one running
        elsewhere), a plain sync call (no loop anywhere), and a direct call from
        a coroutine -- the caller's loop is never re-entered, though the join
        below still blocks the calling thread for up to the summed connect
        budget.

        Fail-soft: connect errors are logged and swallowed. Returns the ids of
        toolkits whose connect attempt raised, timed out, or was abandoned at
        the join deadline (or that are still held by a connect thread a
        previous call abandoned) -- an interrupted connect may have registered
        only part of the server's tools (or still be registering them), so the
        guard in _resolve_tools must refuse those even when their functions
        dict is non-empty. Toolkits that merely stay empty are refused by the
        guard's own emptiness check -- never silently persisted empty.
        """

        def _candidates() -> List[Toolkit]:
            out: List[Toolkit] = []
            seen: Set[int] = set()
            for tool in resolved:
                if (
                    isinstance(tool, Toolkit)
                    and not tool.functions
                    # A connected toolkit with no functions (its server lists
                    # zero tools) must not be touched: connect() would no-op
                    # and the release below would close a LIVE session bound
                    # to another loop. The guard refuses it on emptiness.
                    and not getattr(tool, "initialized", False)
                    and id(tool) not in seen
                    and _is_mcp_toolkit(tool)
                ):
                    seen.add(id(tool))
                    out.append(tool)
            return out

        if not any(isinstance(tool, Toolkit) and _is_mcp_toolkit(tool) for tool in resolved):
            return set()

        # MCPTools stages its transport state on unlocked instance attributes,
        # so two Studio calls (parallel tool calls each run sync entrypoints in
        # their own worker thread) connecting the same registry toolkit from
        # two private loops corrupt each other roughly half the time. Serialize
        # the whole connect pass; the loser re-checks and finds the work done.
        with _MCP_CONNECT_LOCK:
            for key, zombie in list(_MCP_CONNECT_ZOMBIES.items()):
                if not zombie.is_alive():
                    del _MCP_CONNECT_ZOMBIES[key]
            # Checked against every resolved MCP toolkit, not just the
            # connect candidates: a zombie's partial registrations make its
            # toolkit look connected enough to skip candidacy, but they are
            # still mutating and must not be persisted.
            blocked = {
                id(tool)
                for tool in resolved
                if isinstance(tool, Toolkit) and id(tool) in _MCP_CONNECT_ZOMBIES and _is_mcp_toolkit(tool)
            }
            pending = [toolkit for toolkit in _candidates() if id(toolkit) not in blocked]
            if not pending:
                return blocked

            budgets = {
                id(toolkit): float(getattr(toolkit, "timeout_seconds", None) or 10) + _MCP_CONNECT_SLACK_SECONDS
                for toolkit in pending
            }
            failed: Set[int] = set()
            completed: Set[int] = set()

            async def _call(method: Callable[[], Any]) -> None:
                result = method()
                if inspect.isawaitable(result):
                    await result

            async def _connect_and_release() -> None:
                # BaseException, not Exception: the mcp client surfaces an
                # unreachable server as CancelledError out of its cancel
                # scopes, which would otherwise escape connect()'s own
                # fail-soft handler, skip its cleanup, and kill this thread
                # mid-list. Cancellation cannot mean anything else here --
                # this coroutine is the only thing this private loop ever runs.
                for toolkit in pending:
                    succeeded = False
                    try:
                        # wait_for bounds a hung transport in-loop (some hangs,
                        # e.g. an SSE stream that never sends its endpoint
                        # event, are otherwise bounded only by the mcp SDK's
                        # 300s read default), so cleanup runs on this same
                        # loop and the thread reliably exits.
                        await asyncio.wait_for(_call(toolkit.connect), timeout=budgets[id(toolkit)])
                        succeeded = True
                    except BaseException as exc:
                        failed.add(id(toolkit))
                        log_warning(f"Error connecting MCP toolkit '{toolkit.name}': {exc!r}")
                    finally:
                        try:
                            if getattr(toolkit, "initialized", False):
                                await _call(toolkit.close)
                            else:
                                # A failed connect can leave partially-entered
                                # transport contexts on the toolkit (close()
                                # skips uninitialized toolkits); left in place
                                # they poison the next connect() attempt on a
                                # live loop.
                                safe_cleanup = getattr(toolkit, "_safe_cleanup", None)
                                if safe_cleanup is not None:
                                    await _call(safe_cleanup)
                        except BaseException:
                            pass
                        if not succeeded:
                            # An interrupted connect may have registered part
                            # of the server's tools (MCPToolbox even registers
                            # the unfiltered superset before filtering, and
                            # raises with it in place). The failed-ids refusal
                            # only protects THIS call; restore the unconnected
                            # invariant -- empty functions -- so a retry
                            # reconnects instead of persisting the leftovers.
                            toolkit.functions.clear()
                        completed.add(id(toolkit))

            def _run() -> None:
                loop = asyncio.new_event_loop()
                # A failed connect can leave the mcp client's transport async
                # generators mid-run; their aclose() errors during loop
                # shutdown are unactionable stderr noise on this throwaway
                # loop -- the failure itself is already logged per toolkit.
                loop.set_exception_handler(lambda _loop, context: log_debug(f"MCP connect loop cleanup: {context}"))
                try:
                    loop.run_until_complete(_connect_and_release())
                except BaseException as exc:
                    log_warning(f"Error connecting MCP toolkits: {exc!r}")
                finally:
                    try:
                        loop.run_until_complete(loop.shutdown_asyncgens())
                    except BaseException:
                        pass
                    loop.close()

            timeout = sum(budgets.values()) + _MCP_CONNECT_SLACK_SECONDS
            thread = threading.Thread(target=_run, name="studio-mcp-connect", daemon=True)
            thread.start()
            thread.join(timeout=timeout)
            # A toolkit the abandoned thread never finished counts as failed
            # (its functions dict may still be mutating under the zombie loop)
            # and stays blocked from reconnecting until that thread dies.
            abandoned = {id(toolkit) for toolkit in pending if id(toolkit) not in completed}
            for toolkit_id in abandoned:
                _MCP_CONNECT_ZOMBIES[toolkit_id] = thread
            return failed | blocked | abandoned

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

    def _find_agent(self, agent_id: str, actor: Optional[str] = None) -> Optional["Agent"]:
        return self._runner_tools._find_agent(agent_id, actor=actor)

    def _find_team(self, team_id: str, actor: Optional[str] = None) -> Optional["Team"]:
        return self._runner_tools._find_team(team_id, actor=actor)

    def _find_workflow(self, workflow_id: str, actor: Optional[str] = None) -> Optional["Workflow"]:
        return self._runner_tools._find_workflow(workflow_id, actor=actor)

    # Edit-base lookups: like _find_*, but DB components load from the latest
    # draft when versioning is enabled, so successive partial edits accumulate
    # instead of each resetting to the published config.

    def _find_agent_for_edit(self, agent_id: str, actor: Optional[str] = None) -> Optional["Agent"]:
        for a in self._iter_agents():
            if getattr(a, "id", None) == agent_id:
                return a
        if self._runner_tools._db_component_exists("agent", agent_id, actor=actor):
            return self._load_agent_from_db(agent_id, version=self._edit_base_version(agent_id))
        resolved = self._runner_tools._resolve_db_id_by_name_or_slug("agent", agent_id, actor=actor)
        if resolved is None:
            return None
        return self._load_agent_from_db(resolved, version=self._edit_base_version(resolved))

    def _find_team_for_edit(self, team_id: str, actor: Optional[str] = None) -> Optional["Team"]:
        for t in self._iter_teams():
            if getattr(t, "id", None) == team_id:
                return t
        if self._runner_tools._db_component_exists("team", team_id, actor=actor):
            return self._load_team_from_db(team_id, version=self._edit_base_version(team_id))
        resolved = self._runner_tools._resolve_db_id_by_name_or_slug("team", team_id, actor=actor)
        if resolved is None:
            return None
        return self._load_team_from_db(resolved, version=self._edit_base_version(resolved))

    def _find_workflow_for_edit(self, workflow_id: str, actor: Optional[str] = None) -> Optional["Workflow"]:
        for w in self._iter_workflows():
            if getattr(w, "id", None) == workflow_id:
                return w
        if self._runner_tools._db_component_exists("workflow", workflow_id, actor=actor):
            return self._load_workflow_from_db(workflow_id, version=self._edit_base_version(workflow_id))
        resolved = self._runner_tools._resolve_db_id_by_name_or_slug("workflow", workflow_id, actor=actor)
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
        """Version to base an edit on: the LATEST visible version - the one
        get_component and the toolkit instructions just showed the model.
        Basing on the current published version instead silently resurrects
        rolled-back content: after set_current_version(1) with a published v2,
        an edit would produce a v3 carrying v1's fields while the guard
        (checked against latest) still passes."""
        if not self.enable_versions or self.db is None:
            return None
        # The latest VISIBLE version (max over non-tombstoned configs). A draft
        # is accumulated on only when it is that latest; a draft stranded below
        # a newer published version (edit -> draft v2, edit(publish) -> v3) is
        # stale, and basing on it would resurrect rolled-back fields while the
        # expected_version=latest guard still passes.
        try:
            configs = self.db.list_configs(component_id, include_config=False)
        except NotImplementedError:
            return None
        versions = [c["version"] for c in configs if isinstance(c.get("version"), int)]
        return max(versions) if versions else None

    def _latest_draft_version(self, component_id: str) -> Optional[int]:
        if self.db is None:
            return None
        configs = self.db.list_configs(component_id, include_config=False)
        drafts: List[int] = [
            c["version"] for c in configs if c.get("stage") == "draft" and isinstance(c.get("version"), int)
        ]
        return max(drafts) if drafts else None

    @staticmethod
    def _visible_to(row: Optional[Dict[str, Any]], actor: Optional[str]) -> bool:
        """Whether ``actor`` may see this component row.

        The toolkit-side twin of the catalog read predicate, for the paths that
        read a row unscoped and then decide: own rows, unowned (shared) rows,
        and live published rows. Publishing is what puts a component on the
        platform; a draft stays private to its owner, and archiving withdraws a
        published one again. An unscoped caller (no run identity) sees
        everything. Seeing is not touching -- mutation stays owner-scoped in
        _check_component_access.
        """
        if actor is None or row is None:
            return True
        owner = row.get("user_id")
        if owner is None or owner == actor:
            return True
        return row.get("current_version") is not None and row.get("deleted_at") is None

    @staticmethod
    def _may_read_drafts(row: Optional[Dict[str, Any]], actor: Optional[str]) -> bool:
        """Whether ``actor`` may read this component's draft-stage versions.

        Visibility and readable depth are different questions. Publishing puts a
        component on the platform, but it publishes one version -- work in
        progress above the live pointer stays the owner's. So a non-owner who
        can see a component reads its published stage only; the owner (and an
        unscoped caller, and anyone on a shared row) reads every stage.

        Every read path that can return draft-stage data consults this: the
        config reads in get_component and validate_component, the version
        history in list_versions, and the latest_version/latest_stage hints in
        list_components. _pin_allowed states the same rule for running a pinned
        version, and allow_draft_preview (os/utils.py) for the REST twin.
        """
        if actor is None or row is None:
            return True
        owner = row.get("user_id")
        return owner is None or owner == actor

    def _check_component_access(
        self, component_id: str, actor: Optional[str], action: str, noun: str = "component"
    ) -> Optional[tuple]:
        """Ownership gate for mutating an existing DB component row.

        Returns an error message, or None when the caller may proceed. An
        unscoped caller (no run identity) may touch anything; a scoped caller
        may touch only rows it owns.

        Refusals split on what the caller can already see, so a refusal never
        becomes an existence oracle: a row it cannot see answers the same
        "not found" its absence would, while a row it can see -- a shared
        (unowned) one, or another owner's published one -- gets an honest,
        structured refusal naming the real obstacle.
        """
        if self.db is None or actor is None:
            return None
        # include_deleted: an archived row must still be ownership-checked, or
        # another owner's draft under an archived component could be tombstoned
        # by delete_version (get_component without include_deleted reads the
        # archived row as absent, skipping the owner check).
        try:
            row = self.db.get_component(component_id, include_deleted=True)
        except NotImplementedError:
            # An adapter without the component catalog cannot gate ownership,
            # and every mutator behind this gate needs the same capability, so
            # the capability refusal is answered here for all of them - this
            # call runs before the tools' try blocks and would otherwise
            # escape the envelope as a raw traceback.
            return ("db_not_configured", "This database does not support the component catalog.")
        if row is None:
            return None  # No row: creates proceed; other paths produce their own not-found.
        owner = row.get("user_id")
        if owner == actor:
            return None
        if owner is None:
            return (
                "shared_component",
                f"Cannot {action} shared {noun} '{component_id}': it has no owner; ask an operator.",
            )
        if self._visible_to(row, actor):
            return (
                "not_owner",
                f"Cannot {action} {noun} '{component_id}': it is owned by another user; ask them or an operator.",
            )
        return ("component_not_found", f"{noun.capitalize()} not found: {component_id}")

    def _load_agent_from_db(self, agent_id: str, version: Optional[int] = None) -> Optional["Agent"]:
        return self._runner_tools._load_agent_from_db(agent_id, version=version)

    def _load_team_from_db(self, team_id: str, version: Optional[int] = None) -> Optional["Team"]:
        return self._runner_tools._load_team_from_db(team_id, version=version)

    def _load_workflow_from_db(self, workflow_id: str, version: Optional[int] = None) -> Optional["Workflow"]:
        return self._runner_tools._load_workflow_from_db(workflow_id, version=version)

    # ------------------------------------------------------------------
    # Discovery tools
    # ------------------------------------------------------------------

    def _list_db_components(self, component_type: str, actor: Optional[str] = None) -> tuple[List[Dict[str, Any]], int]:
        """Thin summaries of DB components of a given type plus the total DB count.

        The total makes a capped list visible as capped: components beyond the
        cap still resolve by exact id. A scoped actor sees own plus shared rows."""
        return self._runner_tools._list_db_component_rows(component_type, user_id=actor)

    # ------------------------------------------------------------------
    # Read one
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Create (published v1)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Edit (produces a draft version)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Versioning / configs
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Schedules (component-aware)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Envelope + palette internals
    # ------------------------------------------------------------------

    _TYPED_ERROR_CODES = {
        "_ToolsNotFoundError": "tool_not_found",
        "ComponentNotPublishedError": "component_not_published",
        "ComponentVersionConflictError": "version_conflict",
        "ComponentArchivedError": "component_archived",
        "ComponentDependencyError": "dependency_conflict",
        "ComponentCycleError": "dependency_conflict",
        "ComponentDraftRequiredError": "invalid_request",
        "ComponentLastConfigError": "dependency_conflict",
    }

    @staticmethod
    def _denied_error(denied: tuple) -> str:
        """The access gate's (code, message), rendered as an envelope. The code
        travels structurally - substring-matching the prose let any id
        containing "shared" masquerade as a shared-component refusal."""
        code, message = denied
        return error_result(code, message)  # type: ignore[arg-type]

    def _error_from_exception(self, exc: Exception, fallback_message: str) -> str:
        """Map an exception to the envelope. Typed catalog errors keep their
        meaning and retryability; anything else is an internal error whose
        text stays in the log, not in the model's context."""
        code = self._TYPED_ERROR_CODES.get(type(exc).__name__)
        if code is not None:
            return error_result(code, str(exc), retryable=(code == "version_conflict"))  # type: ignore[arg-type]
        if isinstance(exc, AmbiguousComponentNameError):
            return error_result("ambiguous_reference", str(exc), candidates=exc.matches)
        if isinstance(exc, NotImplementedError):
            # An adapter without the component catalog (e.g. Mongo): an honest
            # capability answer, not an internal error.
            return error_result("db_not_configured", "This database does not support the component catalog.")
        if isinstance(exc, SchemaMismatchError):
            # The catalog table exists but is on an older shape, and the
            # message names the migration that fixes it. Distinct from
            # db_not_configured, where no catalog exists at all: the remedy
            # differs, so the code has to. Matched by type rather than by
            # class name so MigrationRequiredError and any other subclass are
            # covered, and kept ahead of the ValueError branch because these
            # are deliberately not ValueErrors - several routers map those to
            # 400, which would report a stale database as a client error.
            return error_result("db_schema_stale", str(exc))
        if isinstance(exc, ValueError) and str(exc):
            return error_result("invalid_request", str(exc))
        logger.exception(fallback_message)
        return error_result("internal_error", fallback_message)

    def _warning_from_exception(self, exc: Exception, message: str) -> str:
        """Describe a best-effort failure to the caller without quoting the driver.

        Warnings ride in a SUCCESS envelope, so they reach the model's context
        the same way an error message would - and the same rule applies:
        typed catalog errors are ours and safe to name, anything else keeps
        its text in the log. A raw adapter exception carries the failing
        statement, the bound parameter values -- which include the row's own
        metadata, the field most likely to hold something a caller would not
        publish -- and, on a connection error, the server it was reaching for.
        """
        if type(exc).__name__ in self._TYPED_ERROR_CODES or isinstance(exc, (SchemaMismatchError, ValueError)):
            return f"{message}: {exc}"
        logger.exception(message)
        return f"{message}: {type(exc).__name__}. The server log has the details."

    def _require_db(self) -> Optional[str]:
        if self.db is None:
            return error_result("db_not_configured", "StudioTools has no db configured.")
        return None

    def _buildable_tool(self, name: str) -> bool:
        """Palette policy: declared tools are buildable; folded tools are
        resolvable but not buildable unless allowed; denials always win.

        A toolkit member requested by its bare function name resolves to the
        toolkit's tool (see _find_tool), so it is judged by the owning
        toolkit's policy too -- the fold and a denial cover the whole toolkit,
        not just its top-level name."""
        if name in self._denied_tools:
            return False
        if name in self._allowed_tools:
            return True
        if not self.registry.tool_is_declared(name):
            return False
        # Top-level names take precedence in resolution; only a name that is
        # not a top-level tool is judged as a toolkit member.
        for tool in self.registry.tools:
            if isinstance(tool, Toolkit):
                if tool.name == name:
                    return True
            elif isinstance(tool, Function):
                if tool.name == name:
                    return True
            elif callable(tool) and getattr(tool, "__name__", None) == name:
                return True
        for tool in self.registry.tools:
            if isinstance(tool, Toolkit) and name in tool.functions:
                if tool.name in self._denied_tools:
                    return False
                if tool.name in self._allowed_tools:
                    return True
                if not self.registry.tool_is_declared(tool.name):
                    return False
        return True

    def _check_tool_policy(self, tool_names: Optional[List[str]]) -> Optional[str]:
        if not tool_names:
            return None
        blocked = sorted(n for n in tool_names if not self._buildable_tool(n))
        if blocked:
            return error_result(
                "tool_not_allowed",
                f"Not buildable: {blocked}. These tools exist for resolution but are outside the build "
                "palette; a deployer allows one by name via allowed_tools.",
                blocked=blocked,
            )
        return None

    @staticmethod
    def _iterable_attr(component: Any, name: str) -> List[Any]:
        """A list view of an attribute that may be a list OR a callable factory.

        ``tools`` and ``members`` accept callables (per-run factories). The
        factory is resolved exactly the way the runtime resolves it -- by
        name-based injection of agent/team/run_context/session_state -- because
        treating it as empty let ``tools=lambda agent: [studio_tools]`` compose
        where ``tools=[studio_tools]`` is refused, handing the composed member
        the whole control plane. A factory that still will not resolve (async,
        raising, or asking for an argument nothing injects) yields the
        unresolved marker instead of an empty list, so the guard refuses rather
        than assumes.
        """
        value = getattr(component, name, None)
        if value is None:
            return []
        if callable(value) and not isinstance(value, type):
            from agno.run import RunContext
            from agno.utils.callables import invoke_callable_factory

            # A factory may branch on the run context, so one probe sees only
            # one branch: a factory that hands out StudioTools to an identified
            # user and something harmless to nobody would read as unprivileged
            # under a single identity-free probe, and the guard exists to stop
            # exactly that composition. Probe with and without an identity and
            # judge the union.
            probes = (
                RunContext(run_id="studio-guard", session_id="studio-guard"),
                RunContext(run_id="studio-guard", session_id="studio-guard", user_id="studio-guard-probe"),
            )
            collected: List[Any] = []
            for probe_context in probes:
                try:
                    produced = invoke_callable_factory(value, component, probe_context)
                except Exception:
                    logger.debug(f"StudioTools: unresolvable {name} factory treated as privileged", exc_info=True)
                    return [_UNRESOLVED_FACTORY]
                if produced is None:
                    continue
                try:
                    collected.extend(list(produced))
                except TypeError:
                    return [_UNRESOLVED_FACTORY]
            return collected
        try:
            return list(value)
        except TypeError:
            return []

    def _privileged_component_ids(self, only_ids: Optional[Set[str]] = None) -> Set[str]:
        """Components whose own tools include a StudioTools instance.

        Composing one into a team or workflow hands the built component the
        whole control plane; the palette refuses unless explicitly allowed.
        One odd registry object must not break every compose call, so each
        component is inspected under its own try/except.

        Inspecting a component can RUN its tools factory, which is arbitrary
        user code, so ``only_ids`` narrows the scan to the ids the caller is
        actually asking about instead of every component on the platform.
        """
        privileged: Set[str] = set()
        for component in [*self._iter_agents(), *self._iter_teams()]:
            component_id = getattr(component, "id", None)
            if not component_id or (only_ids is not None and component_id not in only_ids):
                continue
            try:
                if self._carries_studio_toolkit(component):
                    privileged.add(component_id)
            except Exception:
                logger.debug("StudioTools: skipping un-inspectable component in privilege scan", exc_info=True)
        return privileged

    def _check_member_policy(self, member_ids: List[str]) -> Optional[str]:
        privileged = self._privileged_component_ids(only_ids=set(member_ids))
        blocked = sorted(m for m in member_ids if m in privileged and m not in self._allowed_tools)
        if blocked:
            return error_result(
                "tool_not_allowed",
                f"Refusing to compose {blocked}: these components carry the Studio control plane "
                "(self-composition). A deployer allows one by listing its id in allowed_tools.",
                blocked=blocked,
            )
        return None

    @staticmethod
    def _carries_studio_toolkit(component: Any) -> bool:
        """Whether the component's own tools include the Studio control plane.

        A live component holds the StudioTools instance itself; a rehydrated
        one holds the toolkit's member Functions, whose bound entrypoints name
        the owning instance."""
        for tool in StudioTools._iterable_attr(component, "tools"):
            if tool is _UNRESOLVED_FACTORY:
                return True
            if isinstance(tool, StudioTools):
                return True
            owner = getattr(getattr(tool, "entrypoint", None), "__self__", None)
            if isinstance(owner, StudioTools):
                return True
        return False

    def _component_is_privileged(self, component: Any, seen: Optional[Set[str]] = None) -> bool:
        """Privileged = carries StudioTools itself, or (for a team) any member
        does, recursively. Resolved objects only: raw identifiers cannot answer
        this, which is why the guard runs after resolution."""
        seen = seen if seen is not None else set()
        component_id = getattr(component, "id", None)
        if isinstance(component_id, str):
            if component_id in seen:
                return False
            seen.add(component_id)
        if self._carries_studio_toolkit(component):
            return True
        for member in self._iterable_attr(component, "members"):
            if member is _UNRESOLVED_FACTORY:
                return True
            if self._component_is_privileged(member, seen):
                return True
        return False

    def _refuse_privileged_resolved(self, components: List[Any]) -> Optional[str]:
        """Post-resolution self-composition guard.

        Runs over resolved objects so display names, nested compound steps,
        teams that merely contain the builder, and stored components whose
        rehydrated tools carry the control plane are all covered - the raw
        identifier check alone sees none of those."""
        blocked = sorted(
            {
                str(getattr(component, "id", None) or getattr(component, "name", ""))
                for component in components
                if self._component_is_privileged(component)
                and getattr(component, "id", None) not in self._allowed_tools
            }
        )
        if blocked:
            return error_result(
                "tool_not_allowed",
                f"Refusing to compose {blocked}: these components carry the Studio control plane "
                "(self-composition). A deployer allows one by listing its id in allowed_tools.",
                blocked=blocked,
            )
        return None

    def _mint_component_id(
        self, name: str, component_id: Optional[str], component_type: str, actor: Optional[str] = None
    ) -> tuple:
        """(id, error): strict mint from the name, or the validated explicit id.

        An id collision or a same-type display-name duplicate is a conflict
        carrying the existing id, so the model edits instead of forking.
        An explicit component_id overrides the name check.
        """
        if self.db is None:
            return None, error_result("db_not_configured", "StudioTools has no db configured.")
        if component_id is not None:
            problem = validate_component_id(component_id)
            if problem is not None:
                return None, error_result("invalid_component_id", problem, component_id=component_id)
            candidate = component_id
        else:
            candidate = generate_component_id_from_name(name)
            existing_by_name = self._same_name_component(name, component_type, actor=actor)
            if existing_by_name is not None and existing_by_name != candidate:
                return None, error_result(
                    "component_conflict",
                    f"A {component_type} named '{name}' already exists as '{existing_by_name}'. "
                    "Edit it, or pass an explicit component_id to create a separate component.",
                    existing_component_id=existing_by_name,
                    reason="name",
                )
        if self._component_id_exists(candidate, self.db):
            return None, error_result(
                "component_conflict",
                f"Component id '{candidate}' is taken. Edit the existing component, or pass a "
                "different explicit component_id.",
                existing_component_id=candidate,
                reason="id",
            )
        return candidate, None

    def _same_name_component(self, name: str, component_type: str, actor: Optional[str] = None) -> Optional[str]:
        """Exact display-name duplicate of the same type: code-defined or stored.

        Deliberately narrower than catalog visibility: only the actor's own and
        unowned rows count. Another owner's published component shares the id
        namespace, so a colliding create is still refused -- by the id check,
        which says "that id is taken, pass another". Letting the name check see
        it instead would answer "already exists, edit it" and send the caller
        into an edit that ownership then refuses."""
        iterators: Dict[str, Callable[[], List[Any]]] = {
            "agent": self._iter_agents,
            "team": self._iter_teams,
            "workflow": self._iter_workflows,
        }
        for component in iterators[component_type]():
            if getattr(component, "name", None) == name:
                return getattr(component, "id", None) or name
        if self.db is not None:
            from agno.db.base import ComponentType

            try:
                rows, _ = _own_row_across_pages(
                    self.db.list_components,
                    actor,
                    component_type=ComponentType(component_type),
                    name=name,
                    include_deleted=True,
                    user_id=actor,
                )
                if actor is not None:
                    rows = [r for r in rows if r.get("user_id") in (None, actor)]
            except NotImplementedError:
                return None
            if rows:
                return rows[0].get("component_id")
        return None

    def _resolve_registry_ref(self, kind: str, name: Optional[str]) -> tuple:
        """(value, error) for knowledge / schema / learning / model refs."""
        if name is None:
            return None, None
        if kind == "knowledge":
            value = self.registry.get_knowledge(name)
            code = "knowledge_not_found"
        elif kind == "schema":
            value = self.registry.get_schema(name)
            code = "schema_not_found"
        elif kind == "learning":
            if self.registry.learning_name_is_ambiguous(name):
                # Two distinct machines under one name: binding the first would
                # publish a component that strict dispatch then refuses.
                return None, error_result(
                    "ambiguous_reference",
                    f"learning machine name '{name}' matches more than one registered machine; "
                    "give the machines distinct names",
                    name=name,
                )
            value = self.registry.get_learning(name)
            code = "learning_not_found"
        elif kind == "model":
            value = self.registry.get_model(name)
            code = "model_not_found"
        else:
            return None, error_result("internal_error", f"Unknown ref kind {kind}")
        if value is None:
            return None, error_result(code, f"{kind} not found in registry: {name}", name=name)  # type: ignore[arg-type]
        return value, None

    def _component_row(self, identifier: str, actor: Optional[str]) -> tuple:
        """(row, resolved_id, error) for a stored component by exact id, then
        exact display name.

        Gates on visibility, not ownership: another owner's published component
        resolves here and the caller reads it. What it must not do is hand back
        draft-stage data -- callers apply _published_only_for_non_owner to the
        config they then read."""
        db_err = self._require_db()
        if db_err is not None:
            return None, None, db_err
        assert self.db is not None
        try:
            row = self.db.get_component(identifier)
            resolved_id: Optional[str] = identifier
            if row is None:
                from agno.db.base import ComponentType as _CT  # noqa: F401

                # limit spans the collisions: a published name can match several
                # owners now, and the actor's own has to be found among them.
                rows, total = _own_row_across_pages(self.db.list_components, actor, name=identifier, user_id=actor)
                owned_rows = [r for r in rows if actor is not None and r.get("user_id") == actor]
                if len(owned_rows) == 1:
                    rows, total = owned_rows, 1
                if total > 1:
                    return (
                        None,
                        None,
                        error_result(
                            "ambiguous_reference",
                            f"Display name '{identifier}' matches {total} components; use the exact id.",
                            candidates=[r.get("component_id") for r in rows],
                        ),
                    )
                if rows:
                    resolved_id = rows[0].get("component_id")
                    row = self.db.get_component(resolved_id) if resolved_id else None
        except NotImplementedError as exc:
            # This resolver runs before the tools' try blocks; without the
            # catch an adapter that lacks the component catalog answers with a
            # raw traceback instead of the capability envelope.
            return None, None, self._error_from_exception(exc, "Failed to read component")
        if row is None:
            return None, None, error_result("component_not_found", f"Component not found: {identifier}")
        if not self._visible_to(row, actor):
            return None, None, error_result("component_not_found", f"Component not found: {identifier}")
        return row, resolved_id, None

    @classmethod
    def _step_config_to_spec(cls, step: Dict[str, Any]) -> Dict[str, Any]:
        """A stored step config rendered in the WorkflowStepSpec shape, nested
        steps included, so what get_component shows is exactly what a steps
        edit accepts back. Unknown keys are dropped; unknown types pass
        through with their name so nothing is silently invisible."""
        step_type = str(step.get("type", "Step")).lower()
        spec: Dict[str, Any] = {"type": step_type if step_type != "step" else "step"}
        if step.get("name"):
            spec["name"] = step.get("name")
        if step.get("description"):
            spec["description"] = step.get("description")
        for key in ("agent_id", "team_id", "function_name"):
            if step.get(key):
                spec[key] = step[key]
        # A function step serializes its executor under "executor_ref"
        # (Step._config_to_dict); the spec shape names it "function_name".
        executor_ref = step.get("executor_ref")
        if isinstance(executor_ref, str) and executor_ref:
            spec.setdefault("function_name", executor_ref)
        # Serialized executors may live under nested objects rather than flat ids.
        agent = step.get("agent")
        if isinstance(agent, dict) and agent.get("agent_id" if "agent_id" in agent else "id"):
            spec.setdefault("agent_id", agent.get("agent_id") or agent.get("id"))
        team = step.get("team")
        if isinstance(team, dict) and (team.get("team_id") or team.get("id")):
            spec.setdefault("team_id", team.get("team_id") or team.get("id"))
        executor = step.get("executor")
        if isinstance(executor, str) and executor:
            spec.setdefault("function_name", executor)
        for list_key in ("steps", "else_steps", "choices"):
            children = step.get(list_key)
            if isinstance(children, list) and children:
                spec[list_key] = [cls._step_config_to_spec(child) for child in children if isinstance(child, dict)]
        for scalar in (
            "max_iterations",
            "end_condition",
            "end_condition_function",
            "evaluator",
            "evaluator_function",
            "selector",
            "selector_function",
        ):
            value = step.get(scalar)
            if isinstance(value, (str, int)) and value != "":
                out_key = {
                    "end_condition": "end_condition_function",
                    "evaluator": "evaluator_function",
                    "selector": "selector_function",
                }.get(scalar, scalar)
                spec.setdefault(out_key, value)
        return spec

    def _curated_config_view(self, component_type: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """The stored config, curated for the model: exact stored references,
        no raw blobs. Reads the raw dict so the view never widens a function
        selection to its whole toolkit."""

        def tool_names(entries: Any) -> List[str]:
            # Each stored entry carries the toolkit that owns it, so members are
            # grouped by their OWN attribution - never by a same-named function
            # from a different toolkit, and never registry-order dependent. An
            # entry with no toolkit key (a standalone Function) is passed through
            # exact and never folded.
            standalone: List[str] = []
            by_toolkit: Dict[str, List[str]] = {}
            for entry in entries or []:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name") or (entry.get("function") or {}).get("name")
                if not name:
                    continue
                toolkit = entry.get("toolkit")
                if isinstance(toolkit, str) and toolkit:
                    by_toolkit.setdefault(toolkit, []).append(name)
                else:
                    standalone.append(name)

            collapsed: List[str] = list(standalone)
            # A COMPLETE selection of a toolkit's members collapses to the
            # toolkit name; a partial selection stays exact function names, so
            # the read-then-edit loop can never widen it to the whole toolkit.
            registry_toolkits = {
                tool.name: set(tool.functions.keys())
                for tool in self.registry.tools
                if isinstance(tool, Toolkit) and tool.functions
            }
            for toolkit, selected in by_toolkit.items():
                member_names = registry_toolkits.get(toolkit)
                if member_names and member_names <= set(selected):
                    collapsed.append(toolkit)
                else:
                    collapsed.extend(selected)
            return collapsed

        view: Dict[str, Any] = {
            "name": config.get("name"),
            "description": config.get("description"),
        }
        if component_type in ("agent", "team"):
            model = config.get("model") or {}
            view.update(
                {
                    "instructions": config.get("instructions"),
                    "model_id": model.get("id") if isinstance(model, dict) else None,
                    "tools": tool_names(config.get("tools")),
                    "role": config.get("role"),
                    "markdown": config.get("markdown"),
                    "expected_output": config.get("expected_output"),
                    "additional_context": config.get("additional_context"),
                    "tool_call_limit": config.get("tool_call_limit"),
                    "add_history_to_context": config.get("add_history_to_context"),
                    "num_history_runs": config.get("num_history_runs"),
                    "add_datetime_to_context": config.get("add_datetime_to_context"),
                    "enable_agentic_memory": config.get("enable_agentic_memory"),
                }
            )
            knowledge = config.get("knowledge")
            if isinstance(knowledge, dict) and knowledge.get("name"):
                view["knowledge_name"] = knowledge.get("name")
            learning = config.get("learning")
            # A registry reference is {"name": ...} and nothing else; any
            # other dict is a machine inlined before Studio authored learning
            # by reference, and True is the framework default machine.
            if isinstance(learning, dict) and set(learning) == {"name"} and learning.get("name"):
                view["learning_name"] = learning["name"]
            elif isinstance(learning, dict):
                view["learning"] = "inline"
            elif learning is True:
                view["learning"] = True
            schema = config.get("output_schema")
            # A registry-referenced schema is stored as its class name (a
            # string); an inline JSON schema stays a dict and has no name.
            if isinstance(schema, str) and schema:
                view["output_schema_name"] = schema
            elif isinstance(schema, dict) and schema.get("name"):
                view["output_schema_name"] = schema.get("name")
            reasoning_model = config.get("reasoning_model")
            if isinstance(reasoning_model, dict) and reasoning_model.get("id"):
                view["reasoning_model_id"] = reasoning_model.get("id")
        if component_type == "team":
            members = []
            for member in config.get("members") or []:
                if isinstance(member, dict):
                    members.append(member.get("agent_id") or member.get("team_id"))
            view["member_ids"] = [m for m in members if m]
            view["mode"] = config.get("mode")
        if component_type == "workflow":
            view["steps"] = [
                self._step_config_to_spec(step) for step in config.get("steps") or [] if isinstance(step, dict)
            ]
        metadata = config.get("metadata")
        if isinstance(metadata, dict):
            view["metadata"] = {k: v for k, v in metadata.items() if k != "studio"}
        return {k: v for k, v in view.items() if v is not None}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_models(self) -> str:
        """List the models available for building components.

        Returns:
            str: StudioResult JSON; data.models is a list of {id, provider},
            data.count the total. Use an exact id in model_id arguments.
        """
        models = [
            {"id": getattr(m, "id", None), "provider": getattr(m, "provider", None)} for m in self.registry.models
        ]
        return ok_result("listed", models=models, count=len(models))

    def list_tools(self) -> str:
        """List the tools available for building components.

        Returns:
            str: StudioResult JSON; data.tools rows are {name, kind, buildable,
            source, functions: [{name, description, has_side_effects}]}. Only rows with
            buildable=true may be wired into a component; the others exist so
            stored components can be rebuilt, and requesting one returns
            tool_not_allowed. Use exact names in tool_names arguments.
        """
        rows: List[Dict[str, Any]] = []
        for tool in self.registry.tools:
            if isinstance(tool, Toolkit):
                functions = [
                    {
                        "name": fname,
                        # Function.description is only set by entrypoint
                        # processing; before that, the docstring is the truth.
                        "description": getattr(fn, "description", None)
                        or (inspect.getdoc(getattr(fn, "entrypoint", None)) or "").split("\n")[0]
                        or None,
                        "has_side_effects": getattr(fn, "has_side_effects", None),
                    }
                    for fname, fn in tool.functions.items()
                ]
                name = tool.name
                kind = "toolkit"
            elif isinstance(tool, Function):
                name = tool.name
                kind = "function"
                functions = [
                    {
                        "name": tool.name,
                        "description": getattr(tool, "description", None),
                        "has_side_effects": tool.has_side_effects,
                    }
                ]
            elif callable(tool):
                name = getattr(tool, "__name__", str(tool))
                kind = "callable"
                functions = [{"name": name, "description": inspect.getdoc(tool), "has_side_effects": None}]
            else:
                continue
            rows.append(
                {
                    "name": name,
                    "kind": kind,
                    "buildable": self._buildable_tool(name),
                    "source": "declared" if self.registry.tool_is_declared(name) else "discovered",
                    "functions": functions,
                }
            )
        return ok_result("listed", tools=rows, count=len(rows))

    def list_functions(self) -> str:
        """List the registered functions usable as workflow steps.

        Returns:
            str: StudioResult JSON; data.functions rows are {name, description,
            signature}. Use exact names in function_name / *_function arguments.
        """
        rows = []
        for func in self.registry.functions:
            name = getattr(func, "__name__", None) or getattr(func, "name", None)
            try:
                signature = str(inspect.signature(func))
            except (TypeError, ValueError):
                signature = None
            rows.append({"name": name, "description": inspect.getdoc(func), "signature": signature})
        return ok_result("listed", functions=rows, count=len(rows))

    def list_knowledge(self) -> str:
        """List the knowledge bases attachable to a component via knowledge_name.

        Returns:
            str: StudioResult JSON; data.knowledge is a list of exact names.
        """
        names = sorted(self.registry.get_knowledge_names())
        return ok_result("listed", knowledge=names, count=len(names))

    def list_schemas(self) -> str:
        """List the output schemas attachable to a component via output_schema_name.

        Returns:
            str: StudioResult JSON; data.schemas is a list of exact names.
        """
        names = sorted(getattr(s, "__name__", str(s)) for s in self.registry.schemas)
        return ok_result("listed", schemas=names, count=len(names))

    def list_learning(self) -> str:
        """List the learning machines attachable to a component via learning_name.

        Returns:
            str: StudioResult JSON; data.learning is a list of {name, namespace,
            stores: {store: {mode[, namespace]}}, model_id, db, knowledge[,
            custom_stores]}; namespace is per store for entity_memory and
            learned_knowledge. Every component wired to a machine reads and
            writes its namespace, so pick by namespace. db false means no db
            is declared: the first component to run binds its own db into the
            machine, permanently, for every component sharing it; model_id or
            knowledge null likewise bind to the first component's. create/edit
            return these as warnings when you wire such a machine.
        """
        rows = _learning_rows(self.registry.learning)
        return ok_result("listed", learning=rows, count=len(rows))

    # ------------------------------------------------------------------
    # Component reads
    # ------------------------------------------------------------------

    def list_components(
        self, component_type: Optional[str] = None, _agno_run_context: Optional[RunContext] = None
    ) -> str:
        """List components: code-defined and stored, every type in one view.

        Args:
            component_type (Optional[str]): 'agent', 'team', or 'workflow'; omit for all.

        Returns:
            str: StudioResult JSON; data.components rows are {id, name,
            component_type, source, description, latest_version, latest_stage,
            current_version}; source is 'code' or 'db'. data.db_total above the
            row count means the stored list was capped; capped components still
            resolve by exact id.
        """
        if component_type is not None and component_type not in ("agent", "team", "workflow"):
            return error_result(
                "invalid_request", f"component_type must be agent, team, or workflow, not {component_type!r}"
            )
        actor = _actor_id(_agno_run_context)
        rows: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()
        idless_names: Set[str] = set()
        sources: List[tuple[str, Callable[[], List[Any]]]] = [
            ("agent", self._iter_agents),
            ("team", self._iter_teams),
            ("workflow", self._iter_workflows),
        ]
        for type_name, iterator in sources:
            if component_type is not None and type_name != component_type:
                continue
            for component in iterator():
                cid = getattr(component, "id", None)
                name = getattr(component, "name", None)
                if cid is not None:
                    seen_ids.add(cid)
                elif name is not None:
                    idless_names.add(name)
                rows.append(
                    {
                        "id": cid,
                        "name": name,
                        "component_type": type_name,
                        "source": "code",
                        "description": getattr(component, "description", None),
                    }
                )
        db_total = 0
        if self.db is not None:
            from agno.db.base import ComponentType as _CT

            try:
                db_rows, db_total = self.db.list_components(
                    component_type=_CT(component_type) if component_type else None,
                    limit=self.list_limit,
                    user_id=actor,
                )
            except NotImplementedError:
                db_rows = []
            latest = {}
            try:
                latest = self.db.get_latest_configs({r["component_id"] for r in db_rows})
            except NotImplementedError:
                pass
            for r in db_rows:
                if r["component_id"] in seen_ids or r.get("name") in idless_names:
                    continue
                latest_row = latest.get(r["component_id"]) or {}
                if not self._may_read_drafts(r, actor):
                    # Collapse the hints onto the live version: a non-owner must
                    # not learn from a listing that a newer draft exists.
                    latest_row = {"version": r.get("current_version"), "stage": "published"}
                rows.append(
                    {
                        "id": r["component_id"],
                        "name": r.get("name"),
                        "component_type": r.get("component_type"),
                        "source": "db",
                        "description": r.get("description"),
                        "current_version": r.get("current_version"),
                        "latest_version": latest_row.get("version"),
                        "latest_stage": latest_row.get("stage"),
                    }
                )
        return ok_result("listed", components=rows, count=len(rows), db_total=db_total)

    def get_component(
        self,
        component_id: str,
        version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Read one component: the LATEST version by default, so what you just
        edited is what you read. Call before every edit.

        Args:
            component_id (str): Exact id, or an exact display name.
            version (Optional[int]): Exact stored version; omit for the latest.

        Returns:
            str: StudioResult JSON; data carries {id, component_type, source,
            version, stage, is_current, current_version, latest_version} plus
            the curated config (instructions, model_id, exact tools, members or
            steps, context flags). 'tools' lists exactly what is stored: a
            single function stays a single function, never its whole toolkit.
        """
        version = _version_or_latest(version)
        actor = _actor_id(_agno_run_context)
        code_tiers = (
            ("agent", self._iter_agents),
            ("team", self._iter_teams),
            ("workflow", self._iter_workflows),
        )

        def _code_result(type_name: str, component: Any) -> str:
            view = self._curated_config_view(type_name, _component_to_dict(component))
            return ok_result(
                "read",
                id=getattr(component, "id", None),
                component_type=type_name,
                source="code",
                **view,
            )

        # Exact ids first: a code-defined id may shadow a row, but a
        # code-defined display NAME never outranks an exact DB id - the same
        # id-first order _is_code_defined applies on the edit path.
        for type_name, iterator in code_tiers:
            for component in iterator():
                if getattr(component, "id", None) == component_id:
                    return _code_result(type_name, component)
        db_id_hit = False
        if self.db is not None:
            try:
                db_id_hit = self.db.get_component(component_id, user_id=actor) is not None
            except NotImplementedError:
                db_id_hit = False
        if not db_id_hit:
            # The display-name tier works even when the code component has an
            # id, matching the runner's name tier.
            for type_name, iterator in code_tiers:
                for component in iterator():
                    if getattr(component, "name", None) == component_id:
                        return _code_result(type_name, component)
        row, resolved_id, err = self._component_row(component_id, actor)
        if err is not None:
            return err
        assert self.db is not None and row is not None
        reads_drafts = self._may_read_drafts(row, actor)
        try:
            if version is not None:
                config_row = self.db.get_config(resolved_id, version=version)
            elif reads_drafts:
                config_row = self.db.get_latest_config(resolved_id)
            else:
                # "Latest" means latest published to a non-owner: the live
                # version, never the owner's work in progress above it.
                config_row = self.db.get_config(resolved_id, version=row.get("current_version"))
        except NotImplementedError:
            config_row = self.db.get_config(resolved_id, version=version)
        if config_row is not None and not reads_drafts and config_row.get("stage") != "published":
            # An explicit draft version answers as if that version were absent:
            # the same answer an id the caller cannot see would give.
            if version is not None:
                return error_result("version_not_found", f"Version not found: {resolved_id} v{version}")
            config_row = None
        if config_row is None or not isinstance(config_row.get("config"), dict):
            if version is not None:
                return error_result("version_not_found", f"Version not found: {resolved_id} v{version}")
            return error_result("component_not_found", f"Component has no readable config: {resolved_id}")
        current_version = row.get("current_version")
        latest_row = None
        try:
            # latest_version tells the reader what is above the live pointer;
            # for a non-owner nothing is, because drafts are not theirs to see.
            latest_row = self.db.get_latest_config(resolved_id) if reads_drafts else config_row
        except NotImplementedError:
            pass
        view = self._curated_config_view(str(row.get("component_type")), config_row["config"])
        return ok_result(
            "read",
            id=resolved_id,
            component_type=row.get("component_type"),
            source="db",
            version=config_row.get("version"),
            stage=config_row.get("stage"),
            is_current=current_version is not None and config_row.get("version") == current_version,
            current_version=current_version,
            latest_version=(latest_row or {}).get("version"),
            **view,
        )

    def list_versions(self, component_id: str, _agno_run_context: Optional[RunContext] = None) -> str:
        """List a component's version history, newest first.

        Args:
            component_id (str): Exact component id.

        Returns:
            str: StudioResult JSON; data.versions rows are {version, stage,
            label, created_at, is_current}. Versions are immutable and never
            renumbered; deleted drafts leave a gap.
        """
        row, resolved_id, err = self._component_row(component_id, _actor_id(_agno_run_context))
        if err is not None:
            return err
        assert self.db is not None and row is not None
        current_version = row.get("current_version")
        try:
            configs = self.db.list_configs(resolved_id, include_config=False)
        except NotImplementedError as exc:
            # Reachable only on an adapter that implements get_component but
            # not list_configs; without the catch it escapes the envelope.
            return self._error_from_exception(exc, "Failed to list versions")
        if not self._may_read_drafts(row, _actor_id(_agno_run_context)):
            # A non-owner sees the published history only: the draft numbers,
            # labels and timestamps above the live pointer are not theirs.
            configs = [c for c in configs if c.get("stage") == "published"]
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
        return ok_result("listed", component_id=resolved_id, versions=versions, count=len(versions))

    # ------------------------------------------------------------------
    # Create / edit field application (shared coverage)
    # ------------------------------------------------------------------

    _CLEARABLE_TEXT = ("description", "role", "expected_output", "additional_context")

    def _apply_component_fields(
        self,
        component: Any,
        is_edit: bool,
        replaced_keys: Set[str],
        instructions: Optional[str] = None,
        description: Optional[str] = None,
        model_id: Optional[str] = None,
        tool_names: Optional[List[str]] = None,
        role: Optional[str] = None,
        markdown: Optional[bool] = None,
        expected_output: Optional[str] = None,
        additional_context: Optional[str] = None,
        tool_call_limit: Optional[int] = None,
        add_history_to_context: Optional[bool] = None,
        num_history_runs: Optional[int] = None,
        add_datetime_to_context: Optional[bool] = None,
        knowledge_name: Optional[str] = None,
        output_schema_name: Optional[str] = None,
        reasoning_model_id: Optional[str] = None,
        learning_name: Optional[str] = None,
        enable_learning: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
        warnings: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Apply the shared agent/team fields. Returns an error envelope or None.
        Non-fatal disclosures are appended to ``warnings`` for the result envelope.

        Edit sentinels: omit (None) keeps the stored value, an empty string
        clears a text field, an empty list clears the tool list.
        """
        if instructions is not None:
            component.instructions = instructions
        for field_name, value in (
            ("description", description),
            ("role", role),
            ("expected_output", expected_output),
            ("additional_context", additional_context),
        ):
            if value is not None:
                setattr(component, field_name, value or None)
        if description is not None:
            # The catalog projection reads key presence in the config as "this
            # version owns the description column"; record that the caller
            # touched it so _save_edit writes the key even for a clear.
            replaced_keys.add("description")
        if model_id is not None:
            model = self._find_model(model_id)
            if model is None:
                return error_result("model_not_found", f"Model not found: {model_id}", model_id=model_id)
            component.model = model
            replaced_keys.add("model")
        if tool_names is not None:
            policy_err = self._check_tool_policy(tool_names)
            if policy_err is not None:
                return policy_err
            component.tools = self._resolve_tools(tool_names) or None
            replaced_keys.add("tools")
        if markdown is not None:
            component.markdown = markdown
        if tool_call_limit is not None:
            component.tool_call_limit = tool_call_limit or None
        if add_history_to_context is not None:
            component.add_history_to_context = add_history_to_context
        if num_history_runs is not None:
            component.num_history_runs = num_history_runs
            if hasattr(component, "num_history_messages"):
                # Mirror Agent.__init__'s resolution: num_history_runs wins.
                component.num_history_messages = None
        if add_datetime_to_context is not None:
            component.add_datetime_to_context = add_datetime_to_context
        if knowledge_name is not None:
            if knowledge_name == "":
                component.knowledge = None
            else:
                knowledge, err = self._resolve_registry_ref("knowledge", knowledge_name)
                if err is not None:
                    return err
                component.knowledge = knowledge
            replaced_keys.add("knowledge")
        if output_schema_name is not None:
            if output_schema_name == "":
                component.output_schema = None
            else:
                schema, err = self._resolve_registry_ref("schema", output_schema_name)
                if err is not None:
                    return err
                component.output_schema = schema
            replaced_keys.add("output_schema")
        if reasoning_model_id is not None:
            if reasoning_model_id == "":
                component.reasoning_model = None
            else:
                model, err = self._resolve_registry_ref("model", reasoning_model_id)
                if err is not None:
                    return err
                component.reasoning_model = model
            replaced_keys.add("reasoning_model")
        if enable_learning is not None or learning_name is not None:
            from agno.learn.machine import LearningMachine

            # Studio authors learning only. learning_name wires a registry
            # machine (the reference wins when both are given); the empty string
            # drops the reference, after which enable_learning decides between
            # the default machine and off. enable_learning=True on a component
            # already wired to a machine keeps that machine: replacing it would
            # silently move the component off the shared namespace.
            if learning_name == "":
                component.learning = None
            if learning_name:
                machine, err = self._resolve_registry_ref("learning", learning_name)
                if err is not None:
                    return err
                component.learning = machine
                # A registry machine is one instance shared by every component
                # that references it, and the framework injects db / model /
                # knowledge into it only when unset: the first component to run
                # binds them for every sharer. Disclose that to the caller in
                # the result, not only in the server log.
                for disclosure in _shared_machine_disclosures(learning_name, machine, component):
                    log_warning(disclosure)
                    if warnings is not None:
                        warnings.append(disclosure)
            elif enable_learning:
                wired = component.learning
                if isinstance(wired, LearningMachine):
                    wired_name = getattr(wired, "name", None)
                    label = f"learning machine '{wired_name}'" if wired_name else "an inline learning machine"
                    kept = (
                        f"'{getattr(component, 'id', None)}' is already wired to {label}; enable_learning=True "
                        "kept it. Pass learning_name='' together with enable_learning=True to switch to the "
                        "default machine."
                    )
                    log_warning(kept)
                    if warnings is not None:
                        warnings.append(kept)
                else:
                    # The zero-config path: learning=True makes the framework
                    # build the default machine (user profile + user memory on
                    # the component's own db and model) at init.
                    component.learning = True
            elif enable_learning is False:
                component.learning = None
            replaced_keys.add("learning")
            if component.learning is not None:
                # A component wired to learning drops the legacy user-memory
                # pair: both register a tool named update_user_memory and the
                # legacy one would shadow the store's. Keyed on the outcome, so
                # a call that ends with no learning leaves the pair alone.
                component.enable_agentic_memory = False
                component.memory_manager = None
                replaced_keys.add("memory_manager")
        if metadata is not None:
            existing = getattr(component, "metadata", None) or {}
            studio_meta = existing.get("studio")
            merged = dict(metadata)
            if studio_meta is not None and "studio" not in merged:
                merged["studio"] = studio_meta
            component.metadata = merged or None
            replaced_keys.add("metadata")
        return None

    def _created_payload(
        self,
        component: Any,
        component_type: str,
        version: Optional[int],
        stage: str,
        warnings: Optional[List[str]] = None,
    ) -> str:
        return ok_result(
            "created",
            warnings=warnings,
            id=getattr(component, "id", None),
            name=getattr(component, "name", None),
            component_type=component_type,
            version=version,
            stage=stage,
            is_current=stage == "published",
        )

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_agent(
        self,
        name: str,
        instructions: str,
        model_id: Optional[str] = None,
        tool_names: Optional[List[str]] = None,
        description: Optional[str] = None,
        component_id: Optional[str] = None,
        publish: bool = False,
        role: Optional[str] = None,
        markdown: Optional[bool] = None,
        expected_output: Optional[str] = None,
        additional_context: Optional[str] = None,
        tool_call_limit: Optional[int] = None,
        add_history_to_context: bool = True,
        num_history_runs: Optional[int] = None,
        add_datetime_to_context: bool = True,
        knowledge_name: Optional[str] = None,
        output_schema_name: Optional[str] = None,
        reasoning_model_id: Optional[str] = None,
        learning_name: Optional[str] = None,
        enable_learning: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Create an agent as version 1. Draft by default; publish=True makes it
        live immediately.

        Args:
            name (str): Display name. The id is minted from it (single-segment,
                lowercase); a same-name duplicate is a conflict carrying the
                existing id.
            instructions (str): System instructions.
            model_id (Optional[str]): Exact model id from list_models. Omit for the default.
            tool_names (Optional[List[str]]): Exact buildable names from list_tools.
                Include EVERY tool the user asked for.
            description (Optional[str]): A description of the agent added at the
                beginning of the system message.
            component_id (Optional[str]): Explicit id; overrides the name mint.
            publish (bool): True publishes version 1 immediately, putting the
                agent on the platform for every user; False leaves a draft only
                you can see, which publish_component promotes.
            role (Optional[str]): The agent's role when used as a team member.
            markdown (Optional[bool]): Format responses as markdown.
            expected_output (Optional[str]): What a good answer looks like.
            additional_context (Optional[str]): Extra context appended to the system message.
            tool_call_limit (Optional[int]): Maximum tool calls per run.
            add_history_to_context (bool): Remember the session. Default True.
            num_history_runs (Optional[int]): History depth when history is on.
            add_datetime_to_context (bool): Show the agent the current date and time. Default True.
            knowledge_name (Optional[str]): Exact name from list_knowledge.
            output_schema_name (Optional[str]): Exact name from list_schemas.
            reasoning_model_id (Optional[str]): Exact model id used for reasoning.
            learning_name (Optional[str]): Exact name from list_learning; wires the
                agent to that shared learning machine.
            enable_learning (Optional[bool]): Give the agent the default learning
                machine (user profile and user memory on its own db and model).
                A non-empty learning_name takes precedence.
            metadata (Optional[Dict]): Arbitrary metadata stored on the component.

        Returns:
            str: StudioResult JSON; data is {id, name, component_type, version,
            stage, is_current}.
        """
        from agno.agent.agent import Agent

        db_err = self._require_db()
        if db_err is not None:
            return db_err
        try:
            agent_id, mint_err = self._mint_component_id(
                name, component_id, "agent", actor=_actor_id(_agno_run_context)
            )
            if mint_err is not None:
                return mint_err
            model = self._find_model(model_id)
            if model is None:
                return error_result("model_not_found", f"Model not found: {model_id or 'default'}")
            agent = Agent(
                id=agent_id,
                name=name,
                model=model,
                instructions=instructions,
                db=self.db,
                add_history_to_context=add_history_to_context,
                num_history_runs=num_history_runs if num_history_runs is not None else self.default_num_history_runs,
                add_datetime_to_context=add_datetime_to_context,
            )
            warnings: List[str] = []
            field_err = self._apply_component_fields(
                agent,
                is_edit=False,
                replaced_keys=set(),
                warnings=warnings,
                description=description,
                tool_names=tool_names,
                role=role,
                markdown=markdown,
                expected_output=expected_output,
                additional_context=additional_context,
                tool_call_limit=tool_call_limit,
                knowledge_name=knowledge_name,
                output_schema_name=output_schema_name,
                reasoning_model_id=reasoning_model_id,
                learning_name=learning_name,
                enable_learning=enable_learning,
                metadata=metadata,
            )
            if field_err is not None:
                return field_err
            _stamp_actor(agent, _agno_run_context, "create")
            # Without the version tools there is no publish ladder: creates go
            # live immediately, matching the pre-3.0 surface.
            stage = "published" if (publish or not self.enable_versions) else "draft"
            version = _persist_only(agent, self.db, stage=stage, user_id=_actor_id(_agno_run_context))
            log_debug(f"StudioTools created agent id={agent_id} version={version} stage={stage}")
            return self._created_payload(agent, "agent", version, stage, warnings=warnings)
        except Exception as e:
            return self._error_from_exception(e, "Failed to create agent")

    def create_team(
        self,
        name: str,
        instructions: str,
        member_ids: List[str],
        model_id: Optional[str] = None,
        description: Optional[str] = None,
        component_id: Optional[str] = None,
        publish: bool = False,
        mode: str = "coordinate",
        markdown: Optional[bool] = None,
        expected_output: Optional[str] = None,
        additional_context: Optional[str] = None,
        add_history_to_context: bool = True,
        num_history_runs: Optional[int] = None,
        add_datetime_to_context: bool = True,
        knowledge_name: Optional[str] = None,
        output_schema_name: Optional[str] = None,
        learning_name: Optional[str] = None,
        enable_learning: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Create a team of existing components as version 1. Draft by default.

        Args:
            name (str): Display name; the id is minted from it.
            instructions (str): How the team collaborates.
            member_ids (List[str]): Exact ids of existing agents or teams. A
                published team requires published members; a draft may reference
                drafts.
            model_id (Optional[str]): Leader model. Omit for the default.
            description (Optional[str]): A description of the team added at the
                beginning of the system message.
            component_id (Optional[str]): Explicit id; overrides the name mint.
            publish (bool): True publishes version 1 immediately, putting the team
                on the platform for every user; a draft stays private to you.
            mode (str): 'coordinate' (leader delegates and synthesizes),
                'route' (leader routes, member answers), 'broadcast'
                (every member gets the task), or 'tasks' (leader keeps a
                shared task list and loops until all work is done).
            markdown (Optional[bool]): Format responses as markdown.
            expected_output (Optional[str]): What a good answer looks like.
            additional_context (Optional[str]): Extra leader context.
            add_history_to_context (bool): Remember the session. Default True.
            num_history_runs (Optional[int]): History depth when history is on.
            add_datetime_to_context (bool): Show the current date and time. Default True.
            knowledge_name (Optional[str]): Exact name from list_knowledge.
            output_schema_name (Optional[str]): Exact name from list_schemas.
            learning_name (Optional[str]): Exact name from list_learning; wires the
                team to that shared learning machine.
            enable_learning (Optional[bool]): Give the team the default learning
                machine (user profile and user memory on its own db and model).
                A non-empty learning_name takes precedence.
            metadata (Optional[Dict]): Arbitrary metadata stored on the component.

        Returns:
            str: StudioResult JSON; data is {id, name, component_type, version,
            stage, is_current, member_ids}.
        """
        from agno.team.team import Team

        db_err = self._require_db()
        if db_err is not None:
            return db_err
        try:
            from agno.team.mode import TeamMode

            if mode not in {m.value for m in TeamMode}:
                return error_result(
                    "invalid_request", f"mode must be one of {sorted(m.value for m in TeamMode)}, not {mode!r}"
                )
            if not member_ids:
                # edit_team refuses an empty roster; a create must not mint the
                # team edit_team calls invalid.
                return error_result("invalid_request", "member_ids must not be empty; a team needs members")
            member_err = self._check_member_policy(member_ids)
            if member_err is not None:
                return member_err
            team_id, mint_err = self._mint_component_id(name, component_id, "team", actor=_actor_id(_agno_run_context))
            if mint_err is not None:
                return mint_err
            model = self._find_model(model_id)
            if model is None:
                return error_result("model_not_found", f"Model not found: {model_id or 'default'}")
            members, missing = self._resolve_members(member_ids, actor=_actor_id(_agno_run_context))
            if missing:
                return error_result("component_not_found", f"Members not found: {missing}", missing=missing)
            member_err = self._refuse_privileged_resolved(members)
            if member_err is not None:
                return member_err
            assert self.db is not None
            members, member_pins = self._bind_members_to_target_db(
                members,
                self.db,
                require_published=publish or not self.enable_versions,
                actor=_actor_id(_agno_run_context),
            )
            team = Team(
                id=team_id,
                name=name,
                model=model,
                members=members,
                instructions=instructions,
                db=self.db,
                mode=TeamMode(mode),
                add_history_to_context=add_history_to_context,
                num_history_runs=num_history_runs if num_history_runs is not None else self.default_num_history_runs,
                add_datetime_to_context=add_datetime_to_context,
            )
            warnings: List[str] = []
            field_err = self._apply_component_fields(
                team,
                is_edit=False,
                replaced_keys=set(),
                warnings=warnings,
                description=description,
                markdown=markdown,
                expected_output=expected_output,
                additional_context=additional_context,
                knowledge_name=knowledge_name,
                output_schema_name=output_schema_name,
                learning_name=learning_name,
                enable_learning=enable_learning,
                metadata=metadata,
            )
            if field_err is not None:
                return field_err
            _stamp_actor(team, _agno_run_context, "create")
            # Without the version tools there is no publish ladder: creates go
            # live immediately, matching the pre-3.0 surface.
            stage = "published" if (publish or not self.enable_versions) else "draft"
            version = _persist_only(
                team,
                self.db,
                stage=stage,
                links=self._links_for_component(team, db=self.db, pinned_versions=member_pins),
                user_id=_actor_id(_agno_run_context),
            )
            log_debug(f"StudioTools created team id={team_id} members={member_ids} version={version} stage={stage}")
            result = json.loads(self._created_payload(team, "team", version, stage, warnings=warnings))
            result["data"]["member_ids"] = [getattr(m, "id", None) for m in members]
            return json.dumps(result, default=str)
        except Exception as e:
            return self._error_from_exception(e, "Failed to create team")

    def create_workflow(
        self,
        name: str,
        steps: List[WorkflowStepSpec],
        description: Optional[str] = None,
        component_id: Optional[str] = None,
        publish: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Create a workflow of existing components and functions as version 1.
        Draft by default.

        Args:
            name (str): Display name; the id is minted from it.
            steps (List[WorkflowStepSpec]): Ordered steps. A plain step names
                exactly one of agent_id / team_id / function_name; compound
                steps (type parallel, loop, condition, router, steps) nest
                further steps. See the WorkflowStepSpec fields.
            description (Optional[str]): A description of the workflow.
            component_id (Optional[str]): Explicit id; overrides the name mint.
            publish (bool): True publishes version 1 immediately, putting the
                workflow on the platform for every user; a draft stays private
                to you.
            metadata (Optional[Dict]): Arbitrary metadata stored on the component.

        Returns:
            str: StudioResult JSON; data is {id, name, component_type, version,
            stage, is_current, steps}.
        """
        from agno.workflow.workflow import Workflow

        db_err = self._require_db()
        if db_err is not None:
            return db_err
        try:
            steps, coerce_err = self._coerce_step_specs(steps)
            if coerce_err is not None:
                return coerce_err
            member_err = self._check_member_policy(
                [executor for s in steps if (executor := s.agent_id or s.team_id) is not None]
            )
            if member_err is not None:
                return member_err
            built_steps, build_err = self._build_steps_from_specs(steps, actor=_actor_id(_agno_run_context))
            if build_err is not None:
                return build_err
            step_executors = [
                child
                for leaf in self._iter_leaf_steps(built_steps)
                for child in (getattr(leaf, "agent", None), getattr(leaf, "team", None))
                if child is not None
            ]
            member_err = self._refuse_privileged_resolved(step_executors)
            if member_err is not None:
                return member_err
            workflow_id, mint_err = self._mint_component_id(
                name, component_id, "workflow", actor=_actor_id(_agno_run_context)
            )
            if mint_err is not None:
                return mint_err
            assert self.db is not None
            step_pins = self._bind_steps_to_target_db(
                built_steps,
                self.db,
                require_published=publish or not self.enable_versions,
                actor=_actor_id(_agno_run_context),
            )
            workflow = Workflow(
                id=workflow_id,
                name=name,
                description=description,
                steps=built_steps,
                db=self.db,
            )
            if metadata is not None:
                workflow.metadata = metadata
            _stamp_actor(workflow, _agno_run_context, "create")
            # Without the version tools there is no publish ladder: creates go
            # live immediately, matching the pre-3.0 surface.
            stage = "published" if (publish or not self.enable_versions) else "draft"
            version = _persist_only(
                workflow,
                self.db,
                stage=stage,
                links=self._links_for_component(workflow, db=self.db, pinned_versions=step_pins),
                user_id=_actor_id(_agno_run_context),
            )
            log_debug(f"StudioTools created workflow id={workflow_id} version={version} stage={stage}")
            result = json.loads(self._created_payload(workflow, "workflow", version, stage))
            result["data"]["steps"] = [getattr(s, "name", None) for s in built_steps]
            return json.dumps(result, default=str)
        except Exception as e:
            return self._error_from_exception(e, "Failed to create workflow")

    @staticmethod
    def _coerce_step_specs(steps: Any) -> tuple:
        """(specs, error): accept WorkflowStepSpec objects or plain dicts.

        The framework's validate_call coerces model tool calls; direct Python
        callers pass dicts. Both get the same envelope-shaped refusal."""
        from pydantic import ValidationError

        if steps is None:
            return None, None
        coerced: List[WorkflowStepSpec] = []
        for index, step in enumerate(steps):
            if isinstance(step, WorkflowStepSpec):
                coerced.append(step)
                continue
            try:
                coerced.append(WorkflowStepSpec.model_validate(step))
            except ValidationError as exc:
                problems = "; ".join(e.get("msg", "") for e in exc.errors()[:3])
                return None, error_result("invalid_request", f"steps[{index}] is invalid: {problems}", index=index)
        return coerced, None

    def _build_steps_from_specs(self, specs: List[WorkflowStepSpec], actor: Optional[str] = None) -> tuple:
        """(steps, error): WorkflowStepSpec trees to workflow step objects."""
        from agno.workflow.condition import Condition
        from agno.workflow.loop import Loop
        from agno.workflow.parallel import Parallel
        from agno.workflow.router import Router
        from agno.workflow.step import Step
        from agno.workflow.steps import Steps

        if not specs:
            return None, error_result("invalid_request", "steps must contain at least one step")

        def resolve_function_or_cel(value: str, field: str) -> tuple:
            func = self.registry.get_function(value)
            if func is not None:
                return func, None
            if value.replace("_", "").isalnum():
                return None, error_result(
                    "function_not_found",
                    f"{field} '{value}' is not a registered function (see list_functions). "
                    "A CEL expression is also accepted.",
                    name=value,
                )
            return value, None  # CEL expression passes through

        def build(spec: WorkflowStepSpec) -> tuple:
            if spec.type == "step":
                if spec.function_name is not None:
                    func = self.registry.get_function(spec.function_name)
                    if func is None:
                        return None, error_result(
                            "function_not_found",
                            f"Function not found in registry: {spec.function_name}",
                            name=spec.function_name,
                        )
                    return Step(name=spec.name or spec.function_name, executor=func, description=spec.description), None
                identifier = spec.agent_id or spec.team_id
                assert identifier is not None
                if spec.agent_id is not None:
                    agent_component = self._find_agent(spec.agent_id, actor=actor)
                    if agent_component is None:
                        return None, error_result("component_not_found", f"Agent not found: {spec.agent_id}")
                    return Step(name=spec.name or identifier, agent=agent_component, description=spec.description), None
                assert spec.team_id is not None
                team_component = self._find_team(spec.team_id, actor=actor)
                if team_component is None:
                    return None, error_result("component_not_found", f"Team not found: {spec.team_id}")
                return Step(name=spec.name or identifier, team=team_component, description=spec.description), None

            def build_list(children: Optional[List[WorkflowStepSpec]]) -> tuple:
                built = []
                for child in children or []:
                    obj, err = build(child)
                    if err is not None:
                        return None, err
                    built.append(obj)
                return built, None

            children, err = build_list(spec.steps)
            if err is not None:
                return None, err
            if spec.type == "parallel":
                return Parallel(*children, name=spec.name, description=spec.description), None
            if spec.type == "steps":
                return Steps(name=spec.name, description=spec.description, steps=children), None
            if spec.type == "loop":
                end_condition = None
                if spec.end_condition_function:
                    end_condition, cel_err = resolve_function_or_cel(
                        spec.end_condition_function, "end_condition_function"
                    )
                    if cel_err is not None:
                        return None, cel_err
                return (
                    Loop(
                        steps=children,
                        name=spec.name,
                        description=spec.description,
                        max_iterations=spec.max_iterations or 3,
                        end_condition=end_condition,
                    ),
                    None,
                )
            if spec.type == "condition":
                assert spec.evaluator_function is not None
                evaluator, cel_err = resolve_function_or_cel(spec.evaluator_function, "evaluator_function")
                if cel_err is not None:
                    return None, cel_err
                else_children, err = build_list(spec.else_steps)
                if err is not None:
                    return None, err
                return (
                    Condition(
                        evaluator=evaluator,
                        steps=children,
                        else_steps=else_children or None,
                        name=spec.name,
                        description=spec.description,
                    ),
                    None,
                )
            if spec.type == "router":
                assert spec.selector_function is not None
                selector, cel_err = resolve_function_or_cel(spec.selector_function, "selector_function")
                if cel_err is not None:
                    return None, cel_err
                choices, err = build_list(spec.choices)
                if err is not None:
                    return None, err
                return (
                    Router(selector=selector, choices=choices, name=spec.name, description=spec.description),
                    None,
                )
            return None, error_result("invalid_request", f"Unknown step type: {spec.type}")

        built = []
        for spec in specs:
            obj, err = build(spec)
            if err is not None:
                return None, err
            built.append(obj)
        return built, None

    # ------------------------------------------------------------------
    # Edit
    # ------------------------------------------------------------------

    def _edit_component(
        self,
        component_type: str,
        identifier: str,
        expected_version: Optional[int],
        publish: bool,
        run_context: Optional[RunContext],
        mutate,
        warnings: Optional[List[str]] = None,
    ) -> str:
        """Shared edit path: resolve for edit, gate ownership, apply ``mutate``,
        append a new version (draft, or published when ``publish``). ``warnings``
        is the list ``mutate`` appends its disclosures to; it rides on the
        success envelope."""
        # expected_version is NOT coerced here even though 0 can never match a latest
        # version. Refusing is the safe direction for a compare-and-set: reading 0 as
        # "unset" would turn a guard the caller asked for into an unguarded append, and
        # the REST guard (`guard.latest_version`) would still refuse the same value.
        db_err = self._require_db()
        if db_err is not None:
            return db_err
        finders: Dict[str, tuple] = {
            "agent": (self._iter_agents, self._find_agent_for_edit),
            "team": (self._iter_teams, self._find_team_for_edit),
            "workflow": (self._iter_workflows, self._find_workflow_for_edit),
        }
        iterator, finder = finders[component_type]
        actor = _actor_id(run_context)
        try:
            if self._is_code_defined(identifier, iterator(), component_type):
                hint = ""
                try:
                    shadowed = self._runner_tools._resolve_db_id_by_name_or_slug(
                        component_type, identifier, actor=actor
                    )
                    if shadowed is not None:
                        hint = f" A stored {component_type} with this name exists: use its exact id '{shadowed}'."
                except AmbiguousComponentNameError:
                    pass
                return error_result(
                    "invalid_request",
                    f"Cannot edit code-defined {component_type}: {identifier}. "
                    f"Only stored components are editable.{hint}",
                )
            component = finder(identifier, actor=actor)
        except AmbiguousComponentNameError as e:
            # Ambiguity is its own code with the candidate ids attached, the
            # same answer get_component and list_versions give. It subclasses
            # StudioRunnerError, so this branch has to precede that one or the
            # caller loses the list of ids it needs to pick from.
            return self._error_from_exception(e, f"Failed to resolve {component_type} '{identifier}'")
        except StudioRunnerError as e:
            return error_result("invalid_request", str(e))
        except Exception as e:
            return self._error_from_exception(e, f"Failed to resolve {component_type} '{identifier}'")
        if component is None:
            return error_result("component_not_found", f"{component_type.capitalize()} not found: {identifier}")
        resolved_id = getattr(component, "id", None) or identifier
        denied = self._check_component_access(resolved_id, _actor_id(run_context), "edit", component_type)
        if denied is not None:
            return self._denied_error(denied)
        if expected_version is not None:
            latest = None
            try:
                latest_row = self.db.get_latest_config(resolved_id) if self.db else None
                latest = (latest_row or {}).get("version")
            except NotImplementedError:
                pass
            if latest is not None and latest != expected_version:
                return error_result(
                    "version_conflict",
                    f"{component_type.capitalize()} {resolved_id} latest version is {latest}, "
                    f"expected {expected_version}. Re-read and retry.",
                    retryable=True,
                    latest_version=latest,
                )
        try:
            try:
                component = component.deep_copy()
            except Exception as copy_error:
                # The edit base is a fresh DB rebuild (code-defined components
                # were rejected above); only its nested references can be shared
                # registry singletons, and no edit mutates below the top level.
                # A nested deep_copy failure must not make the component
                # unrepairable -- the edit is how the offending step gets replaced.
                log_debug(f"StudioTools: edit base deep_copy failed ({copy_error}); editing the rebuilt object.")
            if getattr(component, "id", None) is None:
                component.id = identifier
            component.db = self.db
            replaced_keys: Set[str] = set()
            pinned_children: Optional[Dict[str, int]] = None
            mutate_err, pinned_children = mutate(component, replaced_keys)
            if mutate_err is not None:
                return mutate_err
            result = self._save_edit(
                component,
                replaced_keys=replaced_keys,
                pinned_children=pinned_children,
                run_context=run_context,
                publish=publish,
                expected_latest_version=expected_version,
            )
            log_debug(f"StudioTools edited {component_type} id={component.id} result={result}")
            return ok_result("edited", warnings=warnings, id=resolved_id, component_type=component_type, **result)
        except Exception as e:
            return self._error_from_exception(e, f"Failed to edit {component_type}")

    def edit_agent(
        self,
        agent_id: str,
        name: Optional[str] = None,
        instructions: Optional[str] = None,
        model_id: Optional[str] = None,
        tool_names: Optional[List[str]] = None,
        description: Optional[str] = None,
        role: Optional[str] = None,
        markdown: Optional[bool] = None,
        expected_output: Optional[str] = None,
        additional_context: Optional[str] = None,
        tool_call_limit: Optional[int] = None,
        add_history_to_context: Optional[bool] = None,
        num_history_runs: Optional[int] = None,
        add_datetime_to_context: Optional[bool] = None,
        knowledge_name: Optional[str] = None,
        output_schema_name: Optional[str] = None,
        reasoning_model_id: Optional[str] = None,
        learning_name: Optional[str] = None,
        enable_learning: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
        expected_version: Optional[int] = None,
        publish: bool = False,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Edit a stored agent: appends a new version. Call get_component first
        and pass only the fields that change.

        Omitted fields keep their stored values; an empty string clears a text
        field; an empty tool_names list clears the tools. name renames the
        agent - the id never changes. The new version is a draft unless
        publish=True; the live version keeps serving until publish.

        Args:
            agent_id (str): Exact id (or exact display name) of a stored agent.
            name (Optional[str]): New display name; the id stays stable.
            instructions (Optional[str]): New instructions.
            model_id (Optional[str]): New exact model id from list_models.
            tool_names (Optional[List[str]]): Replacement tool list; [] clears.
            description (Optional[str]): New description added at the beginning
                of the system message; "" clears.
            role (Optional[str]): New member role; "" clears.
            markdown (Optional[bool]): Format responses as markdown.
            expected_output (Optional[str]): What a good answer looks like; "" clears.
            additional_context (Optional[str]): Extra system context; "" clears.
            tool_call_limit (Optional[int]): Max tool calls per run; 0 clears.
            add_history_to_context (Optional[bool]): Session memory on or off.
            num_history_runs (Optional[int]): History depth.
            add_datetime_to_context (Optional[bool]): Date and time in context.
            knowledge_name (Optional[str]): Exact name from list_knowledge; "" detaches.
            output_schema_name (Optional[str]): Exact name from list_schemas; "" detaches.
            reasoning_model_id (Optional[str]): Reasoning model id; "" detaches.
            learning_name (Optional[str]): Exact name from list_learning; "" detaches.
            enable_learning (Optional[bool]): True gives the default learning machine
                unless one is already wired (kept, with a warning); False turns
                learning off whatever shape it has. A non-empty learning_name takes
                precedence; learning_name="" with enable_learning=True switches a
                wired component to the default machine.
            metadata (Optional[Dict]): Replacement metadata.
            expected_version (Optional[int]): Compare-and-set guard against the
                latest version you read; a conflict means someone else edited.
            publish (bool): True publishes this edit immediately, replacing the
                version every user runs; otherwise it stays a draft only you see.

        Returns:
            str: StudioResult JSON; data is {id, component_type, version|draft_version, stage}.
        """

        warnings: List[str] = []

        def mutate(agent, replaced_keys):
            if name is not None:
                agent.name = name
            err = self._apply_component_fields(
                agent,
                is_edit=True,
                replaced_keys=replaced_keys,
                warnings=warnings,
                instructions=instructions,
                description=description,
                model_id=model_id,
                tool_names=tool_names,
                role=role,
                markdown=markdown,
                expected_output=expected_output,
                additional_context=additional_context,
                tool_call_limit=tool_call_limit,
                add_history_to_context=add_history_to_context,
                num_history_runs=num_history_runs,
                add_datetime_to_context=add_datetime_to_context,
                knowledge_name=knowledge_name,
                output_schema_name=output_schema_name,
                reasoning_model_id=reasoning_model_id,
                learning_name=learning_name,
                enable_learning=enable_learning,
                metadata=metadata,
            )
            return err, None

        return self._edit_component(
            "agent", agent_id, expected_version, publish, _agno_run_context, mutate, warnings=warnings
        )

    def edit_team(
        self,
        team_id: str,
        name: Optional[str] = None,
        instructions: Optional[str] = None,
        model_id: Optional[str] = None,
        member_ids: Optional[List[str]] = None,
        description: Optional[str] = None,
        mode: Optional[str] = None,
        markdown: Optional[bool] = None,
        expected_output: Optional[str] = None,
        additional_context: Optional[str] = None,
        add_history_to_context: Optional[bool] = None,
        num_history_runs: Optional[int] = None,
        add_datetime_to_context: Optional[bool] = None,
        knowledge_name: Optional[str] = None,
        output_schema_name: Optional[str] = None,
        learning_name: Optional[str] = None,
        enable_learning: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
        expected_version: Optional[int] = None,
        publish: bool = False,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Edit a stored team: appends a new version. Call get_component first
        and pass only the fields that change.

        Args:
            team_id (str): Exact id (or exact display name) of a stored team.
            name (Optional[str]): New display name; the id stays stable.
            instructions (Optional[str]): New collaboration instructions.
            model_id (Optional[str]): New leader model id.
            member_ids (Optional[List[str]]): Replacement member list (exact ids).
            description (Optional[str]): New description added at the beginning
                of the system message; "" clears.
            mode (Optional[str]): 'coordinate', 'route', 'broadcast', or 'tasks'.
            markdown (Optional[bool]): Format responses as markdown.
            expected_output (Optional[str]): What a good answer looks like; "" clears.
            additional_context (Optional[str]): Extra leader context; "" clears.
            add_history_to_context (Optional[bool]): Session memory on or off.
            num_history_runs (Optional[int]): History depth.
            add_datetime_to_context (Optional[bool]): Date and time in context.
            knowledge_name (Optional[str]): Exact name from list_knowledge; "" detaches.
            output_schema_name (Optional[str]): Exact name from list_schemas; "" detaches.
            learning_name (Optional[str]): Exact name from list_learning; "" detaches.
            enable_learning (Optional[bool]): True gives the default learning machine
                unless one is already wired (kept, with a warning); False turns
                learning off whatever shape it has. A non-empty learning_name takes
                precedence; learning_name="" with enable_learning=True switches a
                wired component to the default machine.
            metadata (Optional[Dict]): Replacement metadata.
            expected_version (Optional[int]): Compare-and-set guard.
            publish (bool): True publishes this edit immediately, replacing the
                version every user runs; otherwise it stays a draft only you see.

        Returns:
            str: StudioResult JSON; data is {id, component_type, version|draft_version, stage}.
        """

        warnings: List[str] = []

        def mutate(team, replaced_keys):
            if name is not None:
                team.name = name
            if mode is not None:
                from agno.team.mode import TeamMode

                if mode not in {m.value for m in TeamMode}:
                    return (
                        error_result(
                            "invalid_request",
                            f"mode must be one of {sorted(m.value for m in TeamMode)}, not {mode!r}",
                        ),
                        None,
                    )
                team.mode = TeamMode(mode)
            pinned = None
            if member_ids is not None:
                if not member_ids:
                    return error_result("invalid_request", "member_ids must not be empty; a team needs members"), None
                member_err = self._check_member_policy(member_ids)
                if member_err is not None:
                    return member_err, None
                members, missing = self._resolve_members(member_ids, actor=_actor_id(_agno_run_context))
                if missing:
                    return error_result("component_not_found", f"Members not found: {missing}", missing=missing), None
                member_err = self._refuse_privileged_resolved(members)
                if member_err is not None:
                    return member_err, None
                assert self.db is not None
                members, pinned = self._bind_members_to_target_db(
                    members,
                    self.db,
                    require_published=publish or not self.enable_versions,
                    actor=_actor_id(_agno_run_context),
                )
                team.members = members
                replaced_keys.add("members")
            err = self._apply_component_fields(
                team,
                is_edit=True,
                replaced_keys=replaced_keys,
                warnings=warnings,
                instructions=instructions,
                description=description,
                model_id=model_id,
                markdown=markdown,
                expected_output=expected_output,
                additional_context=additional_context,
                add_history_to_context=add_history_to_context,
                num_history_runs=num_history_runs,
                add_datetime_to_context=add_datetime_to_context,
                knowledge_name=knowledge_name,
                output_schema_name=output_schema_name,
                learning_name=learning_name,
                enable_learning=enable_learning,
                metadata=metadata,
            )
            return err, pinned

        return self._edit_component(
            "team", team_id, expected_version, publish, _agno_run_context, mutate, warnings=warnings
        )

    def edit_workflow(
        self,
        workflow_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        steps: Optional[List[WorkflowStepSpec]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        expected_version: Optional[int] = None,
        publish: bool = False,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Edit a stored workflow: appends a new version. Call get_component
        first and pass only the fields that change.

        Args:
            workflow_id (str): Exact id (or exact display name) of a stored workflow.
            name (Optional[str]): New display name; the id stays stable.
            description (Optional[str]): New description; "" clears.
            steps (Optional[List[WorkflowStepSpec]]): Replacement step list.
            metadata (Optional[Dict]): Replacement metadata.
            expected_version (Optional[int]): Compare-and-set guard.
            publish (bool): True publishes this edit immediately, replacing the
                version every user runs; otherwise it stays a draft only you see.

        Returns:
            str: StudioResult JSON; data is {id, component_type, version|draft_version, stage}.
        """

        def mutate(workflow, replaced_keys):
            if name is not None:
                workflow.name = name
            if description is not None:
                workflow.description = description or None
                replaced_keys.add("description")
            pinned = None
            if steps is not None:
                coerced, coerce_err = self._coerce_step_specs(steps)
                if coerce_err is not None:
                    return coerce_err, None
                member_err = self._check_member_policy(
                    [executor for s in coerced if (executor := s.agent_id or s.team_id) is not None]
                )
                if member_err is not None:
                    return member_err, None
                built, build_err = self._build_steps_from_specs(coerced, actor=_actor_id(_agno_run_context))
                if build_err is not None:
                    return build_err, None
                step_executors = [
                    child
                    for leaf in self._iter_leaf_steps(built)
                    for child in (getattr(leaf, "agent", None), getattr(leaf, "team", None))
                    if child is not None
                ]
                member_err = self._refuse_privileged_resolved(step_executors)
                if member_err is not None:
                    return member_err, None
                if self.db is not None:
                    pinned = self._bind_steps_to_target_db(
                        built,
                        self.db,
                        require_published=publish or not self.enable_versions,
                        actor=_actor_id(_agno_run_context),
                    )
                workflow.steps = built
                replaced_keys.add("steps")
            if metadata is not None:
                existing = getattr(workflow, "metadata", None) or {}
                studio_meta = existing.get("studio")
                merged = dict(metadata)
                if studio_meta is not None and "studio" not in merged:
                    merged["studio"] = studio_meta
                workflow.metadata = merged or None
                replaced_keys.add("metadata")
            return None, pinned

        return self._edit_component("workflow", workflow_id, expected_version, publish, _agno_run_context, mutate)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def publish_component(
        self,
        component_id: str,
        version: Optional[int] = None,
        expected_current_version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Promote a draft to published and make it the live version.

        Args:
            component_id (str): Exact component id.
            version (Optional[int]): The draft to publish; omit for the latest draft.
            expected_current_version (Optional[int]): Compare-and-set guard on
                the live pointer being replaced. Omit it unless you are
                deliberately guarding against a concurrent publish. A component
                that has never been published has no live pointer, so on a
                first publish the only value that can ever match is 0.

        Returns:
            str: StudioResult JSON; data is {id, version}; status "published" or
            "already_published".
        """
        # `version` names the draft to publish, so 0 reads as omitted. The
        # expected_current_version guard beside it does NOT: 0 is its "nothing is
        # live yet" spelling and stays a guard.
        coerced_version = _version_or_latest(version)
        # This one moves the live pointer, so a caller whose argument was
        # reinterpreted hears about it on the envelope, not only in a debug log.
        version_warnings = (
            []
            if coerced_version == version
            else ["Ignored version=0, which is not a version, and published the latest draft instead."]
        )
        version = coerced_version
        db_err = self._require_db()
        if db_err is not None:
            return db_err
        actor = _actor_id(_agno_run_context)
        denied = self._check_component_access(component_id, actor, "publish")
        if denied is not None:
            return self._denied_error(denied)
        assert self.db is not None
        try:
            configs = self.db.list_configs(component_id, include_config=False)
            if not configs:
                return error_result("component_not_found", f"Component not found: {component_id}")
            target = version
            already_published = False
            if target is None:
                drafts = [c for c in configs if c.get("stage") == "draft"]
                if not drafts:
                    return error_result("invalid_request", "No draft version to publish.")
                target = max(d.get("version", 0) for d in drafts)
                # The newest draft is not necessarily ahead of the live version:
                # a draft saved before a later publish stays the newest draft
                # while sitting behind the pointer. Promoting it would move the
                # live version backwards, which an unversioned publish must
                # never do silently - deliberate rollback is set_current_version.
                live_version = (self.db.get_component(component_id) or {}).get("current_version")
                if isinstance(live_version, int) and target < live_version:
                    return error_result(
                        "invalid_request",
                        f"The newest draft of '{component_id}' is v{target}, behind the live v{live_version}; "
                        f"publishing it would move the live version backwards. Edit it again to get a draft "
                        f"ahead of v{live_version}, or use set_current_version to roll back deliberately.",
                        draft_version=target,
                        current_version=live_version,
                    )
            else:
                match = next((c for c in configs if c.get("version") == target), None)
                if match is None:
                    return error_result("version_not_found", f"Version not found: {component_id} v{target}")
                already_published = match.get("stage") == "published"
            # The compare-and-set guard is answered before the already-published
            # no-op returns: a caller who guarded on a live version it no longer
            # holds must hear version_conflict, not a success envelope.
            if expected_current_version is not None:
                from agno.db.base import current_version_matches

                row = self.db.get_component(component_id) or {}
                current_version = row.get("current_version")
                if not current_version_matches(current_version, expected_current_version):
                    if current_version is None:
                        # A first publish has no live pointer, so no value but
                        # 0 can ever match: this is not a conflict to retry
                        # with a different number, and saying so is what
                        # stops a model from looping on it.
                        return error_result(
                            "version_conflict",
                            f"Cannot guard a first publish: '{component_id}' has no live version yet, so "
                            f"expected_current_version={expected_current_version} has nothing to compare "
                            f"against. Omit it, or pass 0 to assert that nothing is live, to publish v{target}.",
                            retryable=False,
                            current_version=None,
                        )
                    return error_result(
                        "version_conflict",
                        f"Current version is {current_version}, expected {expected_current_version}. "
                        "Re-read and retry.",
                        retryable=True,
                        current_version=current_version,
                    )
            if already_published:
                # Nothing to write. The catalog row belongs to whichever version
                # the live pointer names, so re-projecting this one would make
                # the row describe a version that is not live; moving the
                # pointer backwards is set_current_version's job, not publish's.
                return ok_result("already_published", warnings=version_warnings, id=component_id, version=target)
            try:
                result = self.db.upsert_config(
                    component_id=component_id,
                    version=target,
                    stage="published",
                    expected_current_version=expected_current_version,
                    user_id=actor,
                )
            except ValueError:
                # The write is owner-scoped, so it also refuses a row that
                # appeared under another owner after the gate read above. Ask
                # the gate again: it answers with the refusal that read would
                # have produced, and anything else is a real ValueError.
                denied = self._check_component_access(component_id, actor, "publish")
                if denied is not None:
                    return self._denied_error(denied)
                raise
            published_version = result.get("version", target)
            warnings = version_warnings + self._sync_component_row_after_commit(component_id, published_version)
            return ok_result("published", warnings=warnings, id=component_id, version=published_version)
        except Exception as e:
            return self._error_from_exception(e, "Failed to publish component")

    def set_current_version(
        self,
        component_id: str,
        version: int,
        expected_current_version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Re-point the live version to a previously published one (rollback or
        roll-forward). Reversible by pointing back.

        Args:
            component_id (str): Exact component id.
            version (int): A published version to make live.
            expected_current_version (Optional[int]): Compare-and-set guard on
                the pointer being replaced; omit to skip the check.

        Returns:
            str: StudioResult JSON; data is {id, version}.
        """
        db_err = self._require_db()
        if db_err is not None:
            return db_err
        actor = _actor_id(_agno_run_context)
        denied = self._check_component_access(component_id, actor, "re-point")
        if denied is not None:
            return self._denied_error(denied)
        assert self.db is not None
        try:
            ok = self.db.set_current_version(
                component_id, version=version, expected_current_version=expected_current_version, user_id=actor
            )
            if not ok:
                # An owner-scoped refusal reads the same as a missing row, so a
                # component that appeared under another owner since the gate
                # read lands here: re-ask the gate before reporting.
                denied = self._check_component_access(component_id, actor, "re-point")
                if denied is not None:
                    return self._denied_error(denied)
                missing = self._missing_component_error(component_id)
                if missing is not None:
                    return missing
                return error_result("version_not_found", f"Version not found: {component_id} v{version}")
            warnings = self._sync_component_row_after_commit(component_id, version)
            return ok_result("set_current", warnings=warnings, id=component_id, version=version)
        except Exception as e:
            return self._error_from_exception(e, "Failed to set current version")

    def _missing_component_error(self, component_id: str) -> Optional[str]:
        """A component_not_found envelope when the id names no catalog row.

        The pointer and tombstone writes report failure as a bare boolean,
        which cannot separate "no such component" from "no such version"; the
        row read separates them so a caller gets the same component_not_found
        every other surface returns for a missing id. Ownership was already
        settled by _check_component_access, so another owner's row never
        reaches this read.
        """
        if self.db is None:
            return None
        try:
            row = self.db.get_component(component_id, include_deleted=True)
        except NotImplementedError:
            return None
        if row is None:
            return error_result("component_not_found", f"Component not found: {component_id}")
        return None

    def _redact_dependents(self, component_id: str, actor: Optional[str], verb: str) -> str:
        """A dependency_conflict envelope naming only the dependents ``actor``
        can see, counting the rest, so a scoped caller never learns another
        owner's ids from the refusal."""
        assert self.db is not None
        try:
            links = self.db.get_dependents(component_id) or []
        except NotImplementedError:
            links = []
        parent_ids = sorted({str(link.get("parent_component_id")) for link in links if link.get("parent_component_id")})
        if actor is None:
            visible, hidden = parent_ids, 0
        else:
            visible = [pid for pid in parent_ids if self.db.get_component(pid, user_id=actor) is not None]
            hidden = len(parent_ids) - len(visible)
        parts: List[str] = []
        if visible:
            parts.append(f"referenced by {', '.join(visible)}")
        if hidden:
            parts.append(f"and {hidden} other component(s)" if visible else f"referenced by {hidden} component(s)")
        detail = " ".join(parts) or "referenced by other components"
        return error_result(
            "dependency_conflict",
            f"Cannot {verb} {component_id}: {detail}. Archive or edit the dependents first.",
        )

    def delete_version(self, component_id: str, version: int, _agno_run_context: Optional[RunContext] = None) -> str:
        """Delete a draft version. Published versions are immutable history and
        the version number is never reused.

        Args:
            component_id (str): Exact component id.
            version (int): The draft version to delete.

        Returns:
            str: StudioResult JSON; data is {id, version}.
        """
        db_err = self._require_db()
        if db_err is not None:
            return db_err
        actor = _actor_id(_agno_run_context)
        denied = self._check_component_access(component_id, actor, "delete a version of")
        if denied is not None:
            return self._denied_error(denied)
        assert self.db is not None
        try:
            deleted = self.db.delete_config(component_id, version=version, user_id=actor)
            if not deleted:
                # Owner-scoped refusals answer False exactly as a missing
                # version does; re-ask the gate so a row that appeared under
                # another owner since the read is reported as such.
                denied = self._check_component_access(component_id, actor, "delete a version of")
                if denied is not None:
                    return self._denied_error(denied)
                missing = self._missing_component_error(component_id)
                if missing is not None:
                    return missing
                return error_result("version_not_found", f"Version not found: {component_id} v{version}")
            return ok_result("deleted", id=component_id, version=version)
        except Exception as e:
            from agno.db.base import ComponentDependencyError

            if isinstance(e, ComponentDependencyError):
                return self._redact_dependents(component_id, _actor_id(_agno_run_context), "delete a version of")
            return self._error_from_exception(e, "Failed to delete version")

    def archive_component(
        self,
        component_id: str,
        expected_current_version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Archive a component: it stops resolving and running, its id stays
        reserved, and every version survives. restore_component reverses this.

        Refuses while other components pin it - archive or edit the dependents
        first. Deletion of history is not offered; archive is the terminal
        lifecycle state.

        Args:
            component_id (str): Exact id of a stored component. Display names
                do not resolve for destructive operations.
            expected_current_version (Optional[int]): Compare-and-set guard on
                the live pointer. Omit it unless you are deliberately guarding
                against a concurrent write. A component that has never been
                published has no live pointer, so for one of those the only
                value that can ever match is 0.

        Returns:
            str: StudioResult JSON; data is {id}; warnings report side effects.
        """
        db_err = self._require_db()
        if db_err is not None:
            return db_err
        assert self.db is not None
        try:
            row = self.db.get_component(component_id)
            if row is None:
                archived_row = self.db.get_component(component_id, include_deleted=True)
                if archived_row is not None:
                    actor = _actor_id(_agno_run_context)
                    # An archived row is withdrawn from every other user, so it is
                    # never visible across owners: the refusal is the plain 404.
                    if not self._visible_to(archived_row, actor):
                        return error_result("component_not_found", f"Component not found: {component_id}")
                    return ok_result("already_archived", id=component_id)
                try:
                    resolved = None
                    for type_name in ("agent", "team", "workflow"):
                        resolved = self._runner_tools._resolve_db_id_by_name_or_slug(
                            type_name, component_id, actor=_actor_id(_agno_run_context)
                        )
                        if resolved is not None:
                            break
                except AmbiguousComponentNameError:
                    resolved = None
                if resolved is not None:
                    return error_result(
                        "invalid_request",
                        f"Archive requires the exact id: '{component_id}' resolves to '{resolved}'.",
                    )
                return error_result("component_not_found", f"Component not found: {component_id}")
            denied = self._check_component_access(component_id, _actor_id(_agno_run_context), "archive")
            if denied is not None:
                return self._denied_error(denied)
            component_type = str(row.get("component_type"))
            if expected_current_version is not None and row.get("current_version") is None:
                from agno.db.base import expects_no_live_version

                if not expects_no_live_version(expected_current_version):
                    # Same dead end as a guarded first publish: no value but 0
                    # can match a NULL live pointer, so this is terminal, not a
                    # conflict to retry with a different number. The adapter's
                    # own guard still rides the delete for the 0 case.
                    return error_result(
                        "version_conflict",
                        f"Cannot guard this archive: '{component_id}' has no live version yet, so "
                        f"expected_current_version={expected_current_version} has nothing to compare "
                        f"against. Omit it, or pass 0 to assert that nothing is live.",
                        retryable=False,
                        current_version=None,
                    )
            # The cascade runs inside delete_component, in the archive's own
            # transaction, and reports back what it silenced: the count is only
            # knowable there, because it counts the rows this archive flipped
            # from enabled and restore does not re-enable them.
            cascade_stats: Dict[str, int] = {}
            archived = self.db.delete_component(
                component_id,
                hard_delete=False,
                user_id=_actor_id(_agno_run_context),
                expected_current_version=expected_current_version,
                cascade_stats=cascade_stats,
            )
            if not archived:
                return error_result("component_not_found", f"Component not found: {component_id}")
            warnings: List[str] = []
            disabled = cascade_stats.get("schedules_disabled", 0)
            if disabled:
                # The count only - listing ids would disclose other owners' rows
                # through the archiver's result.
                warnings.append(
                    f"Disabled {disabled} schedule(s) that targeted {component_type} '{component_id}'. "
                    "They cannot be re-enabled while the target is archived."
                )
            return ok_result("archived", warnings=warnings, id=component_id)
        except Exception as e:
            from agno.db.base import ComponentDependencyError

            actor = _actor_id(_agno_run_context)
            if isinstance(e, ComponentDependencyError):
                return self._redact_dependents(component_id, actor, "archive")
            return self._error_from_exception(e, "Failed to archive component")

    def restore_component(self, component_id: str, _agno_run_context: Optional[RunContext] = None) -> str:
        """Restore an archived component: it resolves and runs again at the
        version that was live when it was archived. Schedules that were
        disabled by the archive stay disabled.

        Args:
            component_id (str): Exact id of an archived component.

        Returns:
            str: StudioResult JSON; data is {id}.
        """
        db_err = self._require_db()
        if db_err is not None:
            return db_err
        assert self.db is not None
        try:
            actor = _actor_id(_agno_run_context)
            restored = self.db.restore_component(component_id, user_id=actor)
            if restored:
                return ok_result("restored", id=component_id)
            # The restore missed. Ownership decides which refusal that is before
            # state does: another owner's component is refused for being theirs,
            # never for "is not archived" -- restoring it was not on offer either
            # way, and an invisible row still answers the plain not-found.
            denied = self._check_component_access(component_id, actor, "restore")
            if denied is not None:
                return self._denied_error(denied)
            if self.db.get_component(component_id, user_id=actor) is not None:
                return error_result("invalid_request", f"Component is not archived: {component_id}")
            return error_result("component_not_found", f"Component not found: {component_id}")
        except Exception as e:
            return self._error_from_exception(e, "Failed to restore component")

    # ------------------------------------------------------------------
    # Validate (dry run)
    # ------------------------------------------------------------------

    def validate_component(
        self, component_id: str, version: Optional[int] = None, _agno_run_context: Optional[RunContext] = None
    ) -> str:
        """Dry-run a stored component without dispatching it: resolve every
        reference against the live registry and rebuild it exactly as a run
        would. Cheaper and more precise than a live trial run; use it before
        publish_component.

        Args:
            component_id (str): Exact component id.
            version (Optional[int]): Version to validate; omit for the latest.

        Returns:
            str: StudioResult JSON; data is {id, component_type, version, stage,
            valid: true} on success; validation_failed carries the exact
            problem otherwise.
        """
        version = _version_or_latest(version)
        row, resolved_id, err = self._component_row(component_id, _actor_id(_agno_run_context))
        if err is not None:
            return err
        assert self.db is not None and row is not None
        component_type = str(row.get("component_type"))
        reads_drafts = self._may_read_drafts(row, _actor_id(_agno_run_context))
        try:
            if version is None:
                # A non-owner validates what is live, not what is being written.
                latest = (
                    self.db.get_latest_config(resolved_id)
                    if reads_drafts
                    else self.db.get_config(resolved_id, version=row.get("current_version"))
                )
                if latest is None:
                    return error_result("component_not_found", f"Component has no config: {resolved_id}")
                version = latest.get("version")
                stage = latest.get("stage")
            else:
                config_row = self.db.get_config(resolved_id, version=version)
                if config_row is not None and not reads_drafts and config_row.get("stage") != "published":
                    return error_result("version_not_found", f"Version not found: {resolved_id} v{version}")
                if config_row is None:
                    return error_result("version_not_found", f"Version not found: {resolved_id} v{version}")
                stage = config_row.get("stage")
            loaders = {
                "agent": self._runner_tools._load_agent_from_db,
                "team": self._runner_tools._load_team_from_db,
                "workflow": self._runner_tools._load_workflow_from_db,
            }
            loader = loaders.get(component_type)
            if loader is None:
                return error_result("invalid_request", f"Unknown component type: {component_type}")
            rebuilt = loader(resolved_id, version=version, for_dispatch=True)
            if rebuilt is None:
                return error_result(
                    "validation_failed",
                    f"{component_type.capitalize()} {resolved_id} v{version} did not rebuild; "
                    "its stored config could not be loaded.",
                )
            return ok_result(
                "validated", id=resolved_id, component_type=component_type, version=version, stage=stage, valid=True
            )
        except (StudioRunnerError, Exception) as e:  # noqa: B014
            if isinstance(e, StudioRunnerError) or "rehydrat" in str(e).lower():
                return error_result("validation_failed", str(e) or type(e).__name__, id=resolved_id, version=version)
            return self._error_from_exception(e, "Failed to validate component")

    # ------------------------------------------------------------------
    # Run (data plane; preview via explicit version)
    # ------------------------------------------------------------------

    def _pin_allowed(
        self, component_id: Optional[str], version: Optional[int], row: Optional[Dict[str, Any]], actor: Optional[str]
    ) -> bool:
        """Whether a scoped actor may run this exact version. Published pins
        were always reachable, so any caller who can see the component may
        pin one - matching the REST preview gate. A draft pin is a
        control-plane preview and stays owner-only."""
        if actor is None or component_id is None:
            return True
        try:
            config_row = self.db.get_config(component_id=component_id, version=version) if self.db else None
        except NotImplementedError:
            config_row = None
        if isinstance(config_row, dict) and config_row.get("stage") == "published":
            return True
        return (row or {}).get("user_id") == actor

    @staticmethod
    def _version_stamp(version: Optional[int]) -> Dict[str, Any]:
        """Run-metadata entries that record the pinned version on the run itself.

        A preview of an exact version must stay pinned for the whole run: the
        continue/resume surfaces re-resolve the component from this stamp, and
        without it an approved tool call on a paused draft preview silently
        resumes on the published version. An unpinned run carries no stamp, so
        it keeps re-resolving the live version as before.

        Merged OVER the dispatch metadata, which has already stripped any
        inbound stamp as a runtime-reserved key: the toolkit's own pinned
        version is the only source. Only the key is imported, because the
        writer that sanitizes caller metadata lives in the server package and
        the toolkit must keep working without it installed.
        """
        from agno.db.schemas.scheduler import COMPONENT_VERSION_METADATA_KEY

        if version is None:
            return {}
        return {COMPONENT_VERSION_METADATA_KEY: version}

    def _run_component(
        self,
        component_type: str,
        identifier: str,
        message: str,
        version: Optional[int],
        run_context: Optional[RunContext],
        caller_agent: Any = None,
        caller_team: Any = None,
    ) -> str:
        version = _version_or_latest(version)
        runner_calls = {
            "agent": self._runner_tools.run_agent,
            "team": self._runner_tools.run_team,
            "workflow": self._runner_tools.run_workflow,
        }
        if version is None:
            # By keyword: the runner's own injected parameters share these
            # names, and a positional fourth argument would land in the wrong
            # slot without an error the day either signature grows.
            return self._alias_runner_result(
                runner_calls[component_type](
                    identifier,
                    message,
                    _agno_run_context=run_context,
                    _agno_agent=caller_agent,
                    _agno_team=caller_team,
                )
            )
        # Preview: run an exact version, drafts included. Owner-gated like the
        # REST preview: a scoped actor may only preview components it owns.
        row, resolved_id, err = self._component_row(identifier, _actor_id(run_context))
        if err is not None:
            return err
        actor = _actor_id(run_context)
        if not self._pin_allowed(resolved_id, version, row, actor):
            return error_result("component_not_found", f"Component not found: {identifier}")
        # The preview dispatches the component directly rather than through the
        # runner's run tools, so it carries the same dispatch lineage and
        # refusals itself -- otherwise a pinned version would be the one door
        # left open to unbounded self-dispatch.
        try:
            dispatch_metadata = self._runner_tools._dispatch_metadata(
                run_context, component_type, resolved_id, caller_agent=caller_agent, caller_team=caller_team
            )
        except StudioRunnerError as e:
            return error_result("dispatch_refused", str(e))
        loaders = {
            "agent": self._runner_tools._load_agent_from_db,
            "team": self._runner_tools._load_team_from_db,
            "workflow": self._runner_tools._load_workflow_from_db,
        }
        try:
            component = loaders[component_type](resolved_id, version=version, for_dispatch=True)
        except StudioRunnerError as e:
            return error_result("validation_failed", str(e))
        except Exception as e:
            return self._error_from_exception(e, f"Failed to load {component_type} '{identifier}' v{version}")
        if component is None:
            return error_result("version_not_found", f"Version not found: {resolved_id} v{version}")
        sub_run_id = self._runner_tools._registered_sub_run_id(run_context)
        try:
            response = component.run(
                message,
                stream=False,
                user_id=self._runner_tools._caller_user_id(run_context, component),
                session_id=self._runner_tools._sub_session_id(run_context, component_type, resolved_id),
                run_id=sub_run_id,
                metadata={**dispatch_metadata, **self._version_stamp(version)},
            )
            payload = self._runner_tools._run_payload(f"{component_type}_id", resolved_id, response)
            return self._alias_runner_result(payload)
        except Exception as e:
            return self._error_from_exception(e, f"Failed to run {component_type}")

    async def _arun_component(
        self,
        component_type: str,
        identifier: str,
        message: str,
        version: Optional[int],
        run_context: Optional[RunContext],
        caller_agent: Any = None,
        caller_team: Any = None,
    ) -> str:
        """Async mirror of _run_component: the target's arun actually runs on
        the event loop (async hooks and tools included) instead of the sync
        run being pushed to a thread; only the sync DB reads are off-loaded."""
        import asyncio

        version = _version_or_latest(version)
        runner_calls = {
            "agent": self._runner_tools.arun_agent,
            "team": self._runner_tools.arun_team,
            "workflow": self._runner_tools.arun_workflow,
        }
        if version is None:
            # By keyword: the runner's own injected parameters share these
            # names, and a positional fourth argument would land in the wrong
            # slot without an error the day either signature grows.
            return self._alias_runner_result(
                await runner_calls[component_type](
                    identifier,
                    message,
                    _agno_run_context=run_context,
                    _agno_agent=caller_agent,
                    _agno_team=caller_team,
                )
            )
        row, resolved_id, err = await asyncio.to_thread(self._component_row, identifier, _actor_id(run_context))
        if err is not None:
            return err
        actor = _actor_id(run_context)
        if not await asyncio.to_thread(self._pin_allowed, resolved_id, version, row, actor):
            return error_result("component_not_found", f"Component not found: {identifier}")
        # The preview dispatches the component directly rather than through the
        # runner's run tools, so it carries the same dispatch lineage and
        # refusals itself -- otherwise a pinned version would be the one door
        # left open to unbounded self-dispatch. Pure in-memory work; no thread hop.
        try:
            dispatch_metadata = self._runner_tools._dispatch_metadata(
                run_context, component_type, resolved_id, caller_agent=caller_agent, caller_team=caller_team
            )
        except StudioRunnerError as e:
            return error_result("dispatch_refused", str(e))
        loaders = {
            "agent": self._runner_tools._load_agent_from_db,
            "team": self._runner_tools._load_team_from_db,
            "workflow": self._runner_tools._load_workflow_from_db,
        }
        try:
            component = await asyncio.to_thread(
                loaders[component_type], resolved_id, version=version, for_dispatch=True
            )
        except StudioRunnerError as e:
            return error_result("validation_failed", str(e))
        except Exception as e:
            return self._error_from_exception(e, f"Failed to load {component_type} '{identifier}' v{version}")
        if component is None:
            return error_result("version_not_found", f"Version not found: {resolved_id} v{version}")
        sub_run_id = await self._runner_tools._aregistered_sub_run_id(run_context)
        try:
            response = await component.arun(
                message,
                stream=False,
                user_id=self._runner_tools._caller_user_id(run_context, component),
                session_id=self._runner_tools._sub_session_id(run_context, component_type, resolved_id),
                run_id=sub_run_id,
                metadata={**dispatch_metadata, **self._version_stamp(version)},
            )
            payload = self._runner_tools._run_payload(f"{component_type}_id", resolved_id, response)
            return self._alias_runner_result(payload)
        except Exception as e:
            return self._error_from_exception(e, f"Failed to run {component_type}")

    def run_agent(
        self,
        agent_id: str,
        message: str,
        version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
        _agno_agent: Optional[Any] = None,
        _agno_team: Optional[Any] = None,
    ) -> str:
        """Run an agent as the current user. Omit version to run the live
        published version; pass one to preview an exact version, drafts
        included (a preview run is recorded and continuable like any run).

        Args:
            agent_id (str): Id of the agent (a display name or its slug also resolves).
            message (str): The message to send.
            version (Optional[int]): Exact stored version to preview.

        Returns:
            str: JSON with agent_id, id, run_id, session_id, status, content
            and, when paused, the unresolved requirements to continue with.
        """
        return self._run_component(
            "agent", agent_id, message, version, _agno_run_context, caller_agent=_agno_agent, caller_team=_agno_team
        )

    def run_team(
        self,
        team_id: str,
        message: str,
        version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
        _agno_agent: Optional[Any] = None,
        _agno_team: Optional[Any] = None,
    ) -> str:
        """Run a team as the current user. Omit version to run the live
        published version; pass one to preview an exact version.

        Args:
            team_id (str): Id of the team (a display name or its slug also resolves).
            message (str): The message to send.
            version (Optional[int]): Exact stored version to preview.

        Returns:
            str: JSON with team_id, id, run_id, session_id, status, content
            and, when paused, the unresolved requirements.
        """
        return self._run_component(
            "team", team_id, message, version, _agno_run_context, caller_agent=_agno_agent, caller_team=_agno_team
        )

    def run_workflow(
        self,
        workflow_id: str,
        message: str,
        version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
        _agno_agent: Optional[Any] = None,
        _agno_team: Optional[Any] = None,
    ) -> str:
        """Run a workflow as the current user. Omit version to run the live
        published version; pass one to preview an exact version.

        Args:
            workflow_id (str): Id of the workflow (a display name or its slug also resolves).
            message (str): The input message.
            version (Optional[int]): Exact stored version to preview.

        Returns:
            str: JSON with workflow_id, id, run_id, session_id, status, content
            and, when paused, the unresolved requirements.
        """
        return self._run_component(
            "workflow",
            workflow_id,
            message,
            version,
            _agno_run_context,
            caller_agent=_agno_agent,
            caller_team=_agno_team,
        )

    # ------------------------------------------------------------------
    # Async variants (same names on the model surface)
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

    async def alist_knowledge(self) -> str:
        """Async variant of list_knowledge."""
        return await self._run_sync_tool(self.list_knowledge)

    async def alist_schemas(self) -> str:
        """Async variant of list_schemas."""
        return await self._run_sync_tool(self.list_schemas)

    async def alist_learning(self) -> str:
        """Async variant of list_learning."""
        return await self._run_sync_tool(self.list_learning)

    async def alist_components(
        self, component_type: Optional[str] = None, _agno_run_context: Optional[RunContext] = None
    ) -> str:
        """Async variant of list_components."""
        return await self._run_sync_tool(self.list_components, component_type, _agno_run_context=_agno_run_context)

    async def aget_component(
        self, component_id: str, version: Optional[int] = None, _agno_run_context: Optional[RunContext] = None
    ) -> str:
        """Async variant of get_component."""
        return await self._run_sync_tool(
            self.get_component, component_id, version=version, _agno_run_context=_agno_run_context
        )

    async def alist_versions(self, component_id: str, _agno_run_context: Optional[RunContext] = None) -> str:
        """Async variant of list_versions."""
        return await self._run_sync_tool(self.list_versions, component_id, _agno_run_context=_agno_run_context)

    async def acreate_agent(
        self,
        name: str,
        instructions: str,
        model_id: Optional[str] = None,
        tool_names: Optional[List[str]] = None,
        description: Optional[str] = None,
        component_id: Optional[str] = None,
        publish: bool = False,
        role: Optional[str] = None,
        markdown: Optional[bool] = None,
        expected_output: Optional[str] = None,
        additional_context: Optional[str] = None,
        tool_call_limit: Optional[int] = None,
        add_history_to_context: bool = True,
        num_history_runs: Optional[int] = None,
        add_datetime_to_context: bool = True,
        knowledge_name: Optional[str] = None,
        output_schema_name: Optional[str] = None,
        reasoning_model_id: Optional[str] = None,
        learning_name: Optional[str] = None,
        enable_learning: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Async variant of create_agent."""
        return await self._run_sync_tool(
            self.create_agent,
            name=name,
            instructions=instructions,
            model_id=model_id,
            tool_names=tool_names,
            description=description,
            component_id=component_id,
            publish=publish,
            role=role,
            markdown=markdown,
            expected_output=expected_output,
            additional_context=additional_context,
            tool_call_limit=tool_call_limit,
            add_history_to_context=add_history_to_context,
            num_history_runs=num_history_runs,
            add_datetime_to_context=add_datetime_to_context,
            knowledge_name=knowledge_name,
            output_schema_name=output_schema_name,
            reasoning_model_id=reasoning_model_id,
            learning_name=learning_name,
            enable_learning=enable_learning,
            metadata=metadata,
            _agno_run_context=_agno_run_context,
        )

    async def acreate_team(
        self,
        name: str,
        instructions: str,
        member_ids: List[str],
        model_id: Optional[str] = None,
        description: Optional[str] = None,
        component_id: Optional[str] = None,
        publish: bool = False,
        mode: str = "coordinate",
        markdown: Optional[bool] = None,
        expected_output: Optional[str] = None,
        additional_context: Optional[str] = None,
        add_history_to_context: bool = True,
        num_history_runs: Optional[int] = None,
        add_datetime_to_context: bool = True,
        knowledge_name: Optional[str] = None,
        output_schema_name: Optional[str] = None,
        learning_name: Optional[str] = None,
        enable_learning: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Async variant of create_team."""
        return await self._run_sync_tool(
            self.create_team,
            name=name,
            instructions=instructions,
            member_ids=member_ids,
            model_id=model_id,
            description=description,
            component_id=component_id,
            publish=publish,
            mode=mode,
            markdown=markdown,
            expected_output=expected_output,
            additional_context=additional_context,
            add_history_to_context=add_history_to_context,
            num_history_runs=num_history_runs,
            add_datetime_to_context=add_datetime_to_context,
            knowledge_name=knowledge_name,
            output_schema_name=output_schema_name,
            learning_name=learning_name,
            enable_learning=enable_learning,
            metadata=metadata,
            _agno_run_context=_agno_run_context,
        )

    async def acreate_workflow(
        self,
        name: str,
        steps: List[WorkflowStepSpec],
        description: Optional[str] = None,
        component_id: Optional[str] = None,
        publish: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Async variant of create_workflow."""
        return await self._run_sync_tool(
            self.create_workflow,
            name=name,
            steps=steps,
            description=description,
            component_id=component_id,
            publish=publish,
            metadata=metadata,
            _agno_run_context=_agno_run_context,
        )

    async def aedit_agent(
        self,
        agent_id: str,
        name: Optional[str] = None,
        instructions: Optional[str] = None,
        model_id: Optional[str] = None,
        tool_names: Optional[List[str]] = None,
        description: Optional[str] = None,
        role: Optional[str] = None,
        markdown: Optional[bool] = None,
        expected_output: Optional[str] = None,
        additional_context: Optional[str] = None,
        tool_call_limit: Optional[int] = None,
        add_history_to_context: Optional[bool] = None,
        num_history_runs: Optional[int] = None,
        add_datetime_to_context: Optional[bool] = None,
        knowledge_name: Optional[str] = None,
        output_schema_name: Optional[str] = None,
        reasoning_model_id: Optional[str] = None,
        learning_name: Optional[str] = None,
        enable_learning: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
        expected_version: Optional[int] = None,
        publish: bool = False,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Async variant of edit_agent."""
        return await self._run_sync_tool(
            self.edit_agent,
            agent_id=agent_id,
            name=name,
            instructions=instructions,
            model_id=model_id,
            tool_names=tool_names,
            description=description,
            role=role,
            markdown=markdown,
            expected_output=expected_output,
            additional_context=additional_context,
            tool_call_limit=tool_call_limit,
            add_history_to_context=add_history_to_context,
            num_history_runs=num_history_runs,
            add_datetime_to_context=add_datetime_to_context,
            knowledge_name=knowledge_name,
            output_schema_name=output_schema_name,
            reasoning_model_id=reasoning_model_id,
            learning_name=learning_name,
            enable_learning=enable_learning,
            metadata=metadata,
            expected_version=expected_version,
            publish=publish,
            _agno_run_context=_agno_run_context,
        )

    async def aedit_team(
        self,
        team_id: str,
        name: Optional[str] = None,
        instructions: Optional[str] = None,
        model_id: Optional[str] = None,
        member_ids: Optional[List[str]] = None,
        description: Optional[str] = None,
        mode: Optional[str] = None,
        markdown: Optional[bool] = None,
        expected_output: Optional[str] = None,
        additional_context: Optional[str] = None,
        add_history_to_context: Optional[bool] = None,
        num_history_runs: Optional[int] = None,
        add_datetime_to_context: Optional[bool] = None,
        knowledge_name: Optional[str] = None,
        output_schema_name: Optional[str] = None,
        learning_name: Optional[str] = None,
        enable_learning: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
        expected_version: Optional[int] = None,
        publish: bool = False,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Async variant of edit_team."""
        return await self._run_sync_tool(
            self.edit_team,
            team_id=team_id,
            name=name,
            instructions=instructions,
            model_id=model_id,
            member_ids=member_ids,
            description=description,
            mode=mode,
            markdown=markdown,
            expected_output=expected_output,
            additional_context=additional_context,
            add_history_to_context=add_history_to_context,
            num_history_runs=num_history_runs,
            add_datetime_to_context=add_datetime_to_context,
            knowledge_name=knowledge_name,
            output_schema_name=output_schema_name,
            learning_name=learning_name,
            enable_learning=enable_learning,
            metadata=metadata,
            expected_version=expected_version,
            publish=publish,
            _agno_run_context=_agno_run_context,
        )

    async def aedit_workflow(
        self,
        workflow_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        steps: Optional[List[WorkflowStepSpec]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        expected_version: Optional[int] = None,
        publish: bool = False,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Async variant of edit_workflow."""
        return await self._run_sync_tool(
            self.edit_workflow,
            workflow_id=workflow_id,
            name=name,
            description=description,
            steps=steps,
            metadata=metadata,
            expected_version=expected_version,
            publish=publish,
            _agno_run_context=_agno_run_context,
        )

    async def apublish_component(
        self,
        component_id: str,
        version: Optional[int] = None,
        expected_current_version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Async variant of publish_component."""
        return await self._run_sync_tool(
            self.publish_component,
            component_id,
            version=version,
            expected_current_version=expected_current_version,
            _agno_run_context=_agno_run_context,
        )

    async def aset_current_version(
        self,
        component_id: str,
        version: int,
        expected_current_version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Async variant of set_current_version."""
        return await self._run_sync_tool(
            self.set_current_version,
            component_id,
            version,
            expected_current_version=expected_current_version,
            _agno_run_context=_agno_run_context,
        )

    async def adelete_version(
        self, component_id: str, version: int, _agno_run_context: Optional[RunContext] = None
    ) -> str:
        """Async variant of delete_version."""
        return await self._run_sync_tool(
            self.delete_version, component_id, version, _agno_run_context=_agno_run_context
        )

    async def aarchive_component(
        self,
        component_id: str,
        expected_current_version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Async variant of archive_component."""
        return await self._run_sync_tool(
            self.archive_component,
            component_id,
            expected_current_version=expected_current_version,
            _agno_run_context=_agno_run_context,
        )

    async def arestore_component(self, component_id: str, _agno_run_context: Optional[RunContext] = None) -> str:
        """Async variant of restore_component."""
        return await self._run_sync_tool(self.restore_component, component_id, _agno_run_context=_agno_run_context)

    async def avalidate_component(
        self, component_id: str, version: Optional[int] = None, _agno_run_context: Optional[RunContext] = None
    ) -> str:
        """Async variant of validate_component."""
        return await self._run_sync_tool(
            self.validate_component, component_id, version=version, _agno_run_context=_agno_run_context
        )

    async def arun_agent(
        self,
        agent_id: str,
        message: str,
        version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
        _agno_agent: Optional[Any] = None,
        _agno_team: Optional[Any] = None,
    ) -> str:
        """Async variant of run_agent."""
        return await self._arun_component(
            "agent", agent_id, message, version, _agno_run_context, caller_agent=_agno_agent, caller_team=_agno_team
        )

    async def arun_team(
        self,
        team_id: str,
        message: str,
        version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
        _agno_agent: Optional[Any] = None,
        _agno_team: Optional[Any] = None,
    ) -> str:
        """Async variant of run_team."""
        return await self._arun_component(
            "team", team_id, message, version, _agno_run_context, caller_agent=_agno_agent, caller_team=_agno_team
        )

    async def arun_workflow(
        self,
        workflow_id: str,
        message: str,
        version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
        _agno_agent: Optional[Any] = None,
        _agno_team: Optional[Any] = None,
    ) -> str:
        """Async variant of run_workflow."""
        return await self._arun_component(
            "workflow",
            workflow_id,
            message,
            version,
            _agno_run_context,
            caller_agent=_agno_agent,
            caller_team=_agno_team,
        )

    def create_schedule(
        self,
        name: str,
        cron: str,
        target_type: str,
        target_id: str,
        message: str,
        timezone: str = "UTC",
        description: Optional[str] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Create a schedule that runs an existing PUBLISHED component on a cron
        cadence. Create means create: a name you already used is a conflict,
        and update_schedule changes an existing schedule's cadence or message.

        The schedule is owned by the current user and its runs execute as that
        user. Always tell the user the next run time, the timezone, and how to
        turn it off (disable_schedule or the AgentOS UI toggle) - and name any
        recurring model cost.

        Args:
            name (str): Unique schedule name (e.g. "daily-news-digest").
            cron (str): 5-field cron expression (e.g. "0 9 * * *" for daily at 9am).
            target_type (str): One of 'agent', 'team', or 'workflow'.
            target_id (str): Id (or name) of an existing component.
            message (str): The prompt sent to the component on every scheduled run.
            timezone (str): IANA timezone name for the cron expression
                (e.g. "America/New_York"). Defaults to "UTC".
            description (Optional[str]): Human-readable description of the schedule.

        Returns:
            str: StudioResult JSON; data carries {id, name, cron, target_type,
            target_id, endpoint, timezone, enabled, next_run_at, runs_as}.
        """
        from agno.db.schemas.scheduler import build_run_endpoint

        actor = _actor_id(_agno_run_context)
        try:
            component_id, target_error = self._resolve_schedule_target(target_type, target_id, actor=actor)
            if target_error is not None:
                target_code, target_message = target_error
                return error_result(target_code, target_message)  # type: ignore[arg-type]
            if not message or not message.strip():
                return error_result(
                    "invalid_request",
                    "message must be a non-empty string; it is the prompt sent to the "
                    "component on every scheduled run.",
                )
            assert component_id is not None
            # A schedule fires the live published version; a draft-only target
            # would 404 on every tick. The shared predicate decides that, the
            # same one the REST schedule routes and SchedulerTools apply: a
            # catalog row carrying no configs at all is a code-defined target
            # with nothing to publish and stays schedulable, and the read is
            # scoped to the acting owner so another owner's draft neither
            # blocks the schedule nor is disclosed by the refusal.
            from agno.tools.scheduler import _draft_only_component_refusal, code_defined_probe

            if (
                _draft_only_component_refusal(
                    self.db,
                    target_type,
                    component_id,
                    user_id=actor,
                    # The probe must see the same code-defined set the run
                    # tools resolve from - lists when given, registry
                    # otherwise - or a registry-only component would read as
                    # catalog-defined here while its run path treats it as
                    # code.
                    is_code_defined=code_defined_probe(
                        self._runner_tools._iter_agents(),
                        self._runner_tools._iter_teams(),
                        self._runner_tools._iter_workflows(),
                    ),
                )
                is not None
            ):
                return error_result(
                    "target_not_published",
                    f"{target_type.capitalize()} '{component_id}' has no published version; "
                    "publish it before scheduling it.",
                    target_id=component_id,
                )
            # Read again for the response payload only: adapters without the
            # component catalog cannot answer, and their targets are code-defined.
            row = None
            if self.db is not None:
                from agno.db.base import ComponentType

                try:
                    row = self.db.get_component(component_id, component_type=ComponentType(target_type), user_id=actor)
                except (NotImplementedError, ValueError):
                    row = None
            manager = self._get_schedule_manager()
            from agno.db.schemas.scheduler import STUDIO_SCHEDULE_MANAGED_BY

            # Provenance rides the insert: a separate stamp write could fail
            # and leave a live unmanaged row whose name then blocks the retry
            # with schedule_conflict.
            provenance: Dict[str, str] = {
                "managed_by": STUDIO_SCHEDULE_MANAGED_BY,
                "target_type": target_type,
                "target_id": component_id,
            }
            if _agno_run_context is not None:
                if _agno_run_context.run_id:
                    provenance["created_by_run_id"] = _agno_run_context.run_id
                if _agno_run_context.session_id:
                    provenance["created_by_session_id"] = _agno_run_context.session_id
            # The schedule is owned by the acting user: the run executes as the
            # owner, and the owner-scoped schedule tools can see and manage it.
            schedule = manager.create(
                name=name,
                cron=cron,
                endpoint=build_run_endpoint(target_type, component_id),
                method="POST",
                description=description,
                payload={"message": message},
                timezone=timezone,
                if_exists="raise",
                user_id=actor,
                provenance=provenance,
            )
            log_debug(f"StudioTools created schedule name={name} target={target_type}:{component_id}")
            return ok_result(
                "created",
                id=schedule.id,
                name=schedule.name,
                cron=schedule.cron_expr,
                target_type=target_type,
                target_id=component_id,
                endpoint=schedule.endpoint,
                timezone=schedule.timezone,
                enabled=schedule.enabled,
                next_run_at=schedule.next_run_at,
                runs_as=actor or "the platform (unowned schedule)",
                target={
                    "id": component_id,
                    "type": target_type,
                    "name": (row or {}).get("name") if isinstance(row, dict) else None,
                    "source": "db" if isinstance(row, dict) else "code",
                },
            )
        except ValueError as e:
            if "already exists" in str(e):
                existing_id = None
                try:
                    existing = manager._to_schedule(manager._call("get_schedule_by_name", name, user_id=actor))
                    existing_id = getattr(existing, "id", None)
                except Exception:
                    pass
                return error_result(
                    "schedule_conflict",
                    f"A schedule named '{name}' already exists. Change its cadence or message with "
                    "update_schedule, or pick a new name.",
                    name=name,
                    existing_schedule_id=existing_id,
                )
            return self._error_from_exception(e, "Failed to create schedule")
        except Exception as e:
            return self._error_from_exception(e, "Failed to create schedule")

    def update_schedule(
        self,
        schedule_id: str,
        cron: Optional[str] = None,
        message: Optional[str] = None,
        timezone: Optional[str] = None,
        description: Optional[str] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Change an existing schedule's cadence, message, timezone, or
        description. The target component is immutable: pointing at a
        different component is a new schedule.

        Args:
            schedule_id (str): Exact schedule id from list_schedules.
            cron (Optional[str]): New 5-field cron expression. Omit to keep.
            message (Optional[str]): New prompt for every run. Omit to keep.
            timezone (Optional[str]): New IANA timezone. Omit to keep.
            description (Optional[str]): New description. Omit to keep.

        Returns:
            str: StudioResult JSON; data carries the updated schedule fields.
        """
        try:
            if cron is None and message is None and timezone is None and description is None:
                return error_result("invalid_request", "Pass at least one field to change.")
            actor = _actor_id(_agno_run_context)
            manager = self._get_schedule_manager()
            existing = manager.get(schedule_id, user_id=actor)
            if existing is None:
                return error_result("schedule_not_found", f"Schedule not found: {schedule_id}")
            updates: Dict[str, Any] = {}
            if cron is not None:
                updates["cron_expr"] = cron
            if timezone is not None:
                updates["timezone"] = timezone
            if description is not None:
                updates["description"] = description or None
            # Validate the cadence and recompute next_run_at here, the way the REST
            # route does: manager.update is a bare passthrough, so an unvalidated
            # cron would be reported as success, fire once at the stale time, and
            # then be force-disabled by the executor with no disabled_reason. A
            # valid change needs the recompute too, or the old cadence fires once
            # more before the new one takes effect.
            if cron is not None or timezone is not None:
                from agno.scheduler.cron import compute_next_run, validate_cron_expr, validate_timezone

                new_cron = cron if cron is not None else existing.cron_expr
                new_tz = timezone if timezone is not None else (existing.timezone or "UTC")
                if not validate_cron_expr(new_cron):
                    return error_result(
                        "invalid_request",
                        f"Invalid cron expression: {new_cron}. Use 5 fields, e.g. '0 9 * * *' for daily at 9am.",
                    )
                if not validate_timezone(new_tz):
                    return error_result(
                        "invalid_request",
                        f"Invalid timezone: {new_tz}. Use an IANA name, e.g. 'America/New_York'.",
                    )
                updates["next_run_at"] = compute_next_run(new_cron, new_tz)
            if message is not None:
                if not message.strip():
                    return error_result("invalid_request", "message must be a non-empty string.")
                payload = dict(existing.payload or {})
                payload["message"] = message
                updates["payload"] = payload
            schedule = manager.update(schedule_id, user_id=actor, **updates)
            if schedule is None:
                return error_result("schedule_not_found", f"Schedule not found: {schedule_id}")
            warnings: List[str] = []
            if _agno_run_context is not None:
                # Through the manager, not the adapter: on an async database the
                # direct call builds a coroutine nobody awaits, so the stamp is
                # dropped while the tool reports success.
                #
                # The update above is already committed, so the stamp is
                # best-effort: a failure here loses only the record of who made
                # a change that did happen, while reporting an error would tell
                # the caller a cadence it can see take effect was never applied.
                try:
                    manager.stamp_provenance(
                        schedule_id,
                        updated_by_run_id=_agno_run_context.run_id,
                        updated_by_session_id=_agno_run_context.session_id,
                    )
                except Exception as e:
                    warnings.append(
                        self._warning_from_exception(
                            e, f"Updated schedule {schedule_id} but could not stamp provenance on it"
                        )
                    )
            return ok_result(
                "updated",
                warnings=warnings,
                id=schedule.id,
                name=schedule.name,
                cron=schedule.cron_expr,
                timezone=schedule.timezone,
                enabled=schedule.enabled,
                next_run_at=schedule.next_run_at,
            )
        except Exception as e:
            return self._error_from_exception(e, "Failed to update schedule")

    async def acreate_schedule(
        self,
        name: str,
        cron: str,
        target_type: str,
        target_id: str,
        message: str,
        timezone: str = "UTC",
        description: Optional[str] = None,
        _agno_run_context: Optional[RunContext] = None,
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
            _agno_run_context=_agno_run_context,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def aupdate_schedule(
        self,
        schedule_id: str,
        cron: Optional[str] = None,
        message: Optional[str] = None,
        timezone: Optional[str] = None,
        description: Optional[str] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Async variant of update_schedule."""
        return await self._run_sync_tool(
            self.update_schedule,
            schedule_id,
            cron=cron,
            message=message,
            timezone=timezone,
            description=description,
            _agno_run_context=_agno_run_context,
        )

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

    def _resolve_schedule_target(
        self, target_type: str, target_id: str, actor: Optional[str] = None
    ) -> tuple[Optional[str], Optional[tuple[str, str]]]:
        """Resolve a schedule target to a real component id.

        Returns ``(component_id, error)``: exactly one side is set, and the
        error carries its own code with the message. A malformed target_type
        is a bad argument, not a missing component - reported as the latter, a
        model retries a target_id that was never the problem.

        Targets resolve through the Studio lookup path (code-defined lists,
        then DB; matched by id or name), so schedules always point at a
        component's real id even when the caller passed its display name.
        """
        if target_type not in _SCHEDULE_TARGET_TYPES:
            return None, (
                "invalid_request",
                f"Invalid target_type: {target_type}. Must be one of {list(_SCHEDULE_TARGET_TYPES)}.",
            )
        finders: Dict[str, Callable[..., Optional[Any]]] = {
            "agent": self._find_agent,
            "team": self._find_team,
            "workflow": self._find_workflow,
        }
        component = finders[target_type](target_id, actor=actor)
        if component is None:
            return None, ("component_not_found", f"{target_type.capitalize()} not found: {target_id}")
        component_id = getattr(component, "id", None)
        if component_id is None:
            return None, ("component_not_found", f"{target_type.capitalize()} has no id: {target_id}")
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

    def _bind_child_to_target_db(
        self, child: Any, target_db: "BaseDb", noun: str, require_published: bool = True, actor: Optional[str] = None
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
                typed_row = target_db.get_component(child_id, component_type=expected_type, user_id=actor)
                untyped = target_db.get_component(child_id, user_id=actor) if typed_row is None else typed_row
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
        self, members: List[Any], target_db: "BaseDb", require_published: bool = True, actor: Optional[str] = None
    ) -> tuple[List[Any], Dict[str, int]]:
        bound: List[Any] = []
        pins: Dict[str, int] = {}
        for member in members:
            rebound, version = self._bind_child_to_target_db(
                member, target_db, "Member", require_published=require_published, actor=actor
            )
            bound.append(rebound)
            if version is not None and getattr(rebound, "id", None):
                pins[rebound.id] = version
        return bound, pins

    @staticmethod
    def _iter_leaf_steps(steps: List[Any]) -> List[Any]:
        """Every plain step in a workflow step tree, however deeply nested.

        Compound containers (Parallel, Loop, Steps, Condition, Router) carry
        children under .steps, .else_steps, or .choices; a node holding its
        own .agent/.team executor is a leaf. Without the recursion, a leaf
        inside a compound step would bypass the require-published check, the
        code-vs-db id-claim check, and the exact-version rebind.
        """
        leaves: List[Any] = []
        stack = list(steps or [])
        while stack:
            node = stack.pop()
            for attr in ("steps", "else_steps", "choices"):
                children = getattr(node, attr, None)
                if isinstance(children, list):
                    stack.extend(children)
            if getattr(node, "agent", None) is not None or getattr(node, "team", None) is not None:
                leaves.append(node)
        return leaves

    def _bind_steps_to_target_db(
        self, steps: List[Any], target_db: "BaseDb", require_published: bool = True, actor: Optional[str] = None
    ) -> Dict[str, int]:
        pins: Dict[str, int] = {}
        for step in self._iter_leaf_steps(steps):
            for attr, noun in (("agent", "Step agent"), ("team", "Step team")):
                child = getattr(step, attr, None)
                if child is None:
                    continue
                rebound, version = self._bind_child_to_target_db(
                    child, target_db, noun, require_published=require_published, actor=actor
                )
                setattr(step, attr, rebound)
                if version is not None and getattr(rebound, "id", None):
                    pins[rebound.id] = version
        return pins

    def _target_db_exact(self, identifier: str, target_db: "BaseDb", actor: Optional[str] = None) -> Optional[Any]:
        """The component ``identifier`` names by exact id in the target db.

        Checked across both types; a target db claiming the id as both an
        agent and a team is undecidable from the identifier alone.
        """
        from agno.agent.agent import get_agent_by_id
        from agno.db.base import ComponentType
        from agno.exceptions import ComponentRehydrationError
        from agno.team.team import get_team_by_id

        try:
            agent_row = target_db.get_component(identifier, component_type=ComponentType.AGENT, user_id=actor)
            team_row = target_db.get_component(identifier, component_type=ComponentType.TEAM, user_id=actor)
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
        self, member_ids: List[str], target_db: Optional["BaseDb"] = None, actor: Optional[str] = None
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
            agent_match = runner._find_agent_by_exact_id(mid, actor=actor)
            team_match = runner._find_team_by_exact_id(mid, actor=actor)
            if agent_match is None and team_match is None and target_db is not None and target_db is not self.db:
                # Exact ids in the selected target db outrank every name tier.
                target_match = self._target_db_exact(mid, target_db, actor=actor)
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
                runner._db_component_exists("agent", mid, actor=actor)
                or runner._db_component_exists("team", mid, actor=actor)
            ):
                agent_named = runner._find_agent_by_name(mid, actor=actor)
                team_named = runner._find_team_by_name(mid, actor=actor)
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
        self, step_specs: List[Dict[str, Any]], fallback_db: Optional["BaseDb"] = None, actor: Optional[str] = None
    ) -> tuple[List[Any], Optional[str]]:
        from agno.workflow.step import Step

        if not step_specs:
            return [], "step_specs must contain at least one step"

        def find_agent(identifier: str) -> Optional[Any]:
            found = self._runner_tools._find_agent_by_exact_id(identifier, actor=actor)
            if found is None and fallback_db is not None and fallback_db is not self.db:
                from agno.agent.agent import get_agent_by_id

                # Exact ids in the selected target db outrank catalog name tiers.
                found = get_agent_by_id(db=fallback_db, id=identifier, registry=self.registry, user_id=actor)
            return found if found is not None else self._find_agent(identifier, actor=actor)

        def find_team(identifier: str) -> Optional[Any]:
            found = self._runner_tools._find_team_by_exact_id(identifier, actor=actor)
            if found is None and fallback_db is not None and fallback_db is not self.db:
                from agno.team.team import get_team_by_id

                found = get_team_by_id(db=fallback_db, id=identifier, registry=self.registry, user_id=actor)
            return found if found is not None else self._find_team(identifier, actor=actor)

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
        "memory_manager",
        "learning",
        "reasoning_model",
        "parser_model",
        "output_model",
    )

    def _save_edit(
        self,
        component: Component,
        replaced_keys: Optional[Set[str]] = None,
        pinned_children: Optional[Dict[str, int]] = None,
        run_context: Optional[RunContext] = None,
        publish: bool = False,
        expected_latest_version: Optional[int] = None,
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
        _stamp_actor(component, run_context, "edit")
        config = _component_to_dict(component)
        replaced = replaced_keys or set()
        component_id = getattr(component, "id", None)
        self._preserve_unresolved_keys(component_id, config, replaced)
        # description and metadata are also row-only columns (PATCH
        # /components), so the catalog projection needs an explicit signal
        # that THIS version authored them: for description the key's presence
        # (serialization drops a cleared None, so the empty string is written
        # back); for metadata the marker, because the provenance stamp above
        # makes every scoped config carry a metadata dict whether or not the
        # caller touched the field.
        if "description" in replaced:
            config["description"] = getattr(component, "description", None) or ""
        if "metadata" in replaced:
            config["metadata"] = getattr(component, "metadata", None) or {}
            config["metadata_authored"] = True
        if replaced & {"members", "steps"}:
            # The edit replaced the composition: pin the new children at the
            # exact versions the binder rebuilt them from.
            links = self._links_for_component(component, pinned_versions=pinned_children)
        else:
            # Untouched composition keeps the base version's pins verbatim,
            # including link kinds this walk does not reconstruct.
            links = self._base_links(component_id)
        if self.enable_versions and not publish:
            version = self._upsert_draft(
                component,
                config=config,
                links=links,
                user_id=_actor_id(run_context),
                expected_latest_version=expected_latest_version,
            )
            return {"draft_version": version, "stage": "draft"}
        version = _persist_only(
            component,
            self.db,
            config=config,
            links=links,
            user_id=_actor_id(run_context),
            expected_latest_version=expected_latest_version,
        )
        return {"version": version, "stage": "published"}

    def _preserve_unresolved_keys(
        self, component_id: Optional[str], config: Dict[str, Any], replaced_keys: Set[str]
    ) -> None:
        """Copy stored keys the lenient load dropped back into ``config``.

        Reference keys the rebuild could not resolve, and the marker that says
        which version owns the catalog row's metadata column.
        """
        if self.db is None or component_id is None:
            return
        base = self._runner_tools._load_config_from_db(component_id, version=self._edit_base_version(component_id))
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
        # metadata_authored records that a version owns the catalog row's
        # metadata column, and it does not survive the rehydrate-and-
        # reserialize this edit round-trips through: it is a marker on the
        # config, not a field on the component. An edit that leaves metadata
        # alone carries the same metadata forward, so it inherits the base
        # version's authorship too - without this, a version that authored an
        # empty metadata (a deliberate clear, whose only remaining content is
        # the provenance stamp) stops owning the column as soon as any later
        # edit touches a different field, and publishing that version restores
        # the metadata the clear removed.
        if "metadata" not in replaced_keys and base.get("metadata_authored"):
            config["metadata_authored"] = True

    def _base_links(self, component_id: Optional[str]) -> Optional[List[Dict[str, Any]]]:
        """The base version's links, carried forward verbatim on an edit that
        did not replace the component's composition."""
        if self.db is None or component_id is None:
            return None
        return self._runner_tools._load_links_from_db(component_id, version=self._edit_base_version(component_id))

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
        user_id: Optional[str] = None,
        expected_latest_version: Optional[int] = None,
    ) -> Optional[int]:
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
                user_id=user_id,
            )

        # Every edit appends a new immutable draft. The old in-place reuse made
        # two builders (or a builder and the UI) silently overwrite each other;
        # with append-only history both edits survive and publish takes the
        # latest by default.
        result = self.db.upsert_config(
            component_id=component_id,
            config=config if config is not None else _component_to_dict(component),
            stage="draft",
            links=links,
            expected_latest_version=expected_latest_version,
            user_id=user_id,
        )
        return result.get("version")

    def _sync_component_row_after_commit(self, component_id: str, version: Optional[int]) -> List[str]:
        """Re-project the catalog row for a pointer move that already committed.

        The publish or re-point is durable before this runs, so a projection
        failure leaves the row stale - recoverable by publishing or re-pointing
        again. Reporting it as an error is not: the caller hears that a move
        which actually happened did not, and retries or reports a failure that
        never was. The row sync is therefore best-effort here, and the returned
        warning tells the caller the row lags the live version. The envelope
        is where these tools report a side effect of an operation that
        otherwise succeeded, so it is the only channel used here; the REST
        route for the same move has no such field and logs instead.
        """
        try:
            self._sync_component_row(component_id, version)
        except Exception as e:
            return [
                self._warning_from_exception(
                    e, f"{component_id} is live at v{version} but its catalog row could not be re-projected"
                )
            ]
        return []

    def _sync_component_row(self, component_id: str, version: Optional[int]) -> None:
        """Bring the component row's name/description/metadata in line with a
        newly published config version."""
        if self.db is None:
            return
        from agno.db.base import ComponentType, project_config_identity

        component = self.db.get_component(component_id)
        row = self.db.get_config(component_id=component_id, version=version)
        config = row.get("config") if isinstance(row, dict) else None
        if component is None or not isinstance(config, dict):
            return
        # project_config_identity states which row fields the version owns; a
        # key it omits is row-only and upsert_component's None leaves that
        # column alone.
        projection = project_config_identity(config)
        self.db.upsert_component(
            component_id=component_id,
            component_type=ComponentType(component["component_type"]),
            name=projection.get("name") or component.get("name"),
            description=projection.get("description"),
            metadata=projection.get("metadata"),
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


def _actor_id(run_context: Optional[RunContext]) -> Optional[str]:
    """The acting user for ownership.

    ``None`` means unscoped: direct Python use, tests, and admin surfaces.
    Unscoped writes create unowned (shared) rows and unscoped reads see
    everything -- the same semantics SchedulerTools and the REST router give
    a caller without an identity."""
    return getattr(run_context, "user_id", None) if run_context is not None else None


def _stamp_actor(component: Component, run_context: Optional[RunContext], action: str) -> None:
    """Record who acted on the component in its metadata, under one key.

    The stamp merges into existing metadata rather than replacing it, so user
    keys survive. Without a run context there is no actor to record."""
    if run_context is None:
        return
    stamp: Dict[str, Any] = {
        "last_actor": run_context.user_id,
        "last_action": action,
        "last_run_id": run_context.run_id,
        "last_session_id": run_context.session_id,
    }
    existing = getattr(component, "metadata", None) or {}
    studio_meta = dict(existing.get("studio") or {})
    if action == "create":
        stamp["created_by"] = run_context.user_id
        stamp["created_run_id"] = run_context.run_id
        stamp["created_session_id"] = run_context.session_id
    else:
        # Creation provenance survives every later action.
        for key in ("created_by", "created_run_id", "created_session_id"):
            if key in studio_meta:
                stamp[key] = studio_meta[key]
    studio_meta.update(stamp)
    component.metadata = {**existing, "studio": studio_meta}


def _persist_only(
    component: Component,
    db: Optional["BaseDb"],
    stage: str = "published",
    config: Optional[Dict[str, Any]] = None,
    links: Optional[List[Dict[str, Any]]] = None,
    user_id: Optional[str] = None,
    expected_latest_version: Optional[int] = None,
) -> Optional[int]:
    """Save a component WITHOUT cascading to members or step agents.

    Agno's built-in ``component.save()`` recursively persists every member of
    a team and every agent/team referenced by a workflow step. That pulls
    code-defined agents (ones you passed via ``include_agents`` or the registry)
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
    from agno.db.base import ComponentArchivedError as _ComponentArchivedError
    from agno.db.base import ComponentType, project_config_identity

    resolved_config = config if config is not None else _component_to_dict(component)
    if db.get_component(component_id) is None:
        # An id that resolves only with include_deleted is a tombstone: answer
        # the archived error + restore hint the create tool maps, instead of
        # falling into create_component_with_config and getting a generic
        # "not available".
        try:
            if db.get_component(component_id, include_deleted=True) is not None:
                raise _ComponentArchivedError(
                    f"Component '{component_id}' is archived. Restore it (restore_component) "
                    "before writing to it, or choose a different id."
                )
        except NotImplementedError:
            pass
        # First write: one atomic transaction, so a failed config write can
        # never leave an active component with zero configs whose id and name
        # then block the retry with a strict-mint conflict.
        try:
            _, config_row = db.create_component_with_config(
                component_id=component_id,
                component_type=ComponentType(_component_type(component)),
                name=getattr(component, "name", component_id),
                config=resolved_config,
                description=getattr(component, "description", None),
                metadata=getattr(component, "metadata", None),
                stage=stage,
                links=links,
                user_id=user_id,
            )
            return config_row.get("version")
        except NotImplementedError:
            pass  # Adapter without the atomic path: fall through to two writes.

    identity = {
        "component_id": component_id,
        "component_type": _component_type(component),
        "name": getattr(component, "name", component_id),
        "description": getattr(component, "description", None),
        "metadata": getattr(component, "metadata", None),
        "user_id": user_id,
    }
    if db.get_component(component_id) is not None:
        # Existing component (edit/publish): the GUARDED config write goes
        # first, so a refused write (CAS conflict) raises before the identity
        # projection is touched - otherwise the row would carry the loser's
        # name while the live config keeps the winner's.
        result = db.upsert_config(
            component_id=component_id,
            config=resolved_config,
            stage=stage,
            links=links,
            expected_latest_version=expected_latest_version,
            user_id=user_id,
        )
        # project_config_identity states which row fields this config version
        # owns; a key it omits is row-only (set through PATCH /components,
        # never present in a config) and upsert_component's None leaves that
        # column alone.
        # The config write above is already committed, so the projection is
        # best-effort from here: a failure leaves the row describing the
        # previous version, which the next save fixes, while reporting an error
        # would tell the caller a version it can see was never written - and an
        # edit retried on that report appends yet another version.
        try:
            projection = project_config_identity(resolved_config)
            db.upsert_component(
                **{
                    **identity,
                    "name": projection.get("name") or identity["name"],
                    "description": projection.get("description"),
                    "metadata": projection.get("metadata"),
                }
            )
        except Exception as e:
            logger.warning(f"Saved {component_id} v{result.get('version')} but could not re-project its row: {e}")
        return result.get("version")

    # Create fallback (the atomic path was unavailable): the component does
    # not exist yet, so identity must be written first for the config to attach.
    db.upsert_component(**identity)
    result = db.upsert_config(
        component_id=component_id,
        config=resolved_config,
        stage=stage,
        links=links,
        expected_latest_version=expected_latest_version,
        user_id=user_id,
    )
    return result.get("version")


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


def _shared_machine_disclosures(learning_name: str, machine: Any, component: Any) -> List[str]:
    """What a caller wiring ``machine`` should know about first-component binding.

    The framework injects db / model / knowledge into a shared machine only
    when unset, so whichever component runs first fixes them for every sharer;
    and a machine already bound to a different db than the component writes
    its learning there, not where the component's own data lives.
    """
    disclosures: List[str] = []
    machine_db = getattr(machine, "db", None)
    component_db = getattr(component, "db", None)
    component_db_id = getattr(component_db, "id", None)
    if machine_db is None:
        bound_to = f" (this component's db is '{component_db_id}')" if component_db_id else ""
        disclosures.append(
            f"Learning machine '{learning_name}' declares no db: the first component to run binds its own db "
            f"into it, permanently, for every component sharing it{bound_to}. Declare db on the machine if "
            "the deployer should choose."
        )
    elif component_db is not None and machine_db is not component_db:
        machine_db_id = getattr(machine_db, "id", None)
        if machine_db_id != component_db_id:
            disclosures.append(
                f"Learning machine '{learning_name}' is bound to db '{machine_db_id}' while this component uses "
                f"'{component_db_id}': its learning is read and written there, not in this component's db."
            )
    if getattr(machine, "model", None) is None:
        disclosures.append(
            f"Learning machine '{learning_name}' declares no model: the first component to run binds its own "
            "model into it for every component sharing it. Declare model on the machine if the deployer "
            "should choose."
        )
    if getattr(machine, "learned_knowledge", False) and getattr(machine, "knowledge", None) is None:
        disclosures.append(
            f"Learning machine '{learning_name}' enables learned_knowledge without a knowledge: the first "
            "component to run that has one binds it for every component sharing it."
        )
    return disclosures


def _learning_rows(machines: List[Any]) -> List[Dict[str, Any]]:
    """One list_learning row per NAMED registered machine, read from its
    declared fields (describe_learning_machine never builds the stores)."""
    from agno.learn.machine import describe_learning_machine

    rows: List[Dict[str, Any]] = []
    for machine in machines:
        name = getattr(machine, "name", None)
        if not isinstance(name, str) or not name:
            continue
        rows.append(describe_learning_machine(machine))
    return rows


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


def _mirror_async_docstrings() -> None:
    """The async variants register under the sync names, so the model sees one
    schema whichever mode picks the entrypoint. Parameter descriptions parse
    from the entrypoint docstring at schema build time; the async wrappers
    carry the sync method's docstring so neither surface is stripped."""
    for attribute_name, member in list(vars(StudioTools).items()):
        if not inspect.iscoroutinefunction(member) or not attribute_name.startswith("a"):
            continue
        sync_member = getattr(StudioTools, attribute_name[1:], None)
        if sync_member is not None and callable(sync_member) and sync_member.__doc__:
            member.__doc__ = sync_member.__doc__


_mirror_async_docstrings()
