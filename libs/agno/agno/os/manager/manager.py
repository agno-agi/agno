"""Create the OS Manager team and its members."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from agno.agent import Agent
from agno.os.manager.config import OSManager
from agno.os.manager.prompts import (
    BUILDER_INSTRUCTIONS,
    MANAGER_INSTRUCTIONS,
    OPERATOR_INSTRUCTIONS,
)
from agno.registry._reserved import BUILDER_ID, OPERATOR_ID, RESERVED_MEMBER_IDS
from agno.run.authorization import requires_permission
from agno.team import Team

if TYPE_CHECKING:
    from agno.os.app import AgentOS


@dataclass
class _Manager:
    """The OS Manager team, its configuration and its platform specialists."""

    config: OSManager
    team: Team
    builder: Agent
    operator: Agent
    product_manager: Optional[Agent] = None

    @property
    def agents(self) -> List[Agent]:
        return [self.builder, self.operator, *([self.product_manager] if self.product_manager is not None else [])]

    @property
    def components(self) -> List[Any]:
        return [self.team, *self.agents]

    def owns(self, component: Any) -> bool:
        """Check whether this object is the manager team or one of its members."""
        return any(component is owned for owned in self.components)

    def manifest(self) -> Dict[str, Any]:
        """Default description and prompts for the public manager team."""
        from agno.os.config import Manifest

        entries = {
            self.config.id: Manifest(
                description="Builds and runs components, and checks the AgentOS status.",
                quick_prompts=[
                    "What can you help me do?",
                    "What agents and workflows can I run?",
                    "Run diagnostics and explain any issues",
                ],
            ),
        }
        return entries


def _resolve_model(agent_os: "AgentOS", config: OSManager) -> Any:
    if config.model is not None:
        return config.model
    registry = agent_os.registry
    if registry is not None and registry.models:
        return registry.models[0]
    raise ValueError(
        "The manager needs a model: pass OSManager(model=...) or declare one on the registry (Registry(models=[...]))"
    )


def _resolve_workspace(config: OSManager) -> Optional[Any]:
    if config.root is None:
        return None
    from agno.context.mode import ContextMode
    from agno.context.workspace import WorkspaceContextProvider

    if isinstance(config.root, (str, Path)):
        # Give Platform Manager file tools directly. Default exclusions block
        # environment and credential files.
        return WorkspaceContextProvider(
            id="platform-source",
            name="Platform Source",
            root=config.root,
            mode=ContextMode.tools,
        )
    if not isinstance(config.root, WorkspaceContextProvider):
        raise TypeError("OSManager.root must be a path or WorkspaceContextProvider")
    from agno.tools.workspace import DEFAULT_EXCLUDE_PATTERNS

    provider = config.root
    if provider.allow_paths or any(
        pattern.startswith("!") and pattern not in DEFAULT_EXCLUDE_PATTERNS for pattern in provider.exclude_patterns
    ):
        raise ValueError("OSManager.root cannot override exclusions with allow_paths or custom exemptions")
    # Copy the provider's settings without changing the original or accepting
    # custom tools that could bypass file exclusions.
    return WorkspaceContextProvider(
        id=provider.id,
        name=provider.name,
        root=provider.root,
        mode=ContextMode.tools,
        exclude_patterns=list(dict.fromkeys([*DEFAULT_EXCLUDE_PATTERNS, *provider.exclude_patterns])),
        max_file_lines=provider.max_file_lines,
        max_file_length=provider.max_file_length,
    )


def _raise_if_reserved_ids(components: List[Any], owned: Sequence[Any] = ()) -> None:
    from agno.registry._reserved import RESERVED_MANAGER_IDS

    reserved = RESERVED_MANAGER_IDS
    collisions = sorted(
        {
            component_id
            for component in components
            if (component_id := getattr(component, "id", None)) in reserved and all(component is not c for c in owned)
        }
    )
    if collisions:
        raise ValueError(f"Duplicate IDs reserved for the manager: {', '.join(collisions)}")


def _diagnostics_tool(agent_os: "AgentOS", required_env: Sequence[str]) -> Any:
    from agno.tools import Toolkit

    @requires_permission("config", "read")
    def run_diagnostics() -> str:
        """Run the OS diagnostics now: database, authorization, component ids, registry names, interfaces,
        scheduler, MCP and required environment variables. Makes no model calls.

        Returns JSON with an overall status (PASS, WARN, FAIL or SKIP) and one entry per check with its
        evidence type: configuration (settings were checked) or live (a database or network read succeeded).
        """
        return json.dumps(agent_os.run_diagnostics(required_env=required_env).to_dict())

    @requires_permission("config", "read")
    async def arun_diagnostics() -> str:
        """Async variant of run_diagnostics."""
        return json.dumps((await agent_os.arun_diagnostics(required_env=required_env)).to_dict())

    arun_diagnostics.__doc__ = run_diagnostics.__doc__
    return Toolkit(
        name="manager_diagnostics",
        tools=[run_diagnostics],
        async_tools=[(arun_diagnostics, "run_diagnostics")],
    )


def _build_manager(agent_os: "AgentOS", config: OSManager) -> _Manager:
    """Create the manager using the OS registry and database.

    Called internally by AgentOS after its registry and database are set.
    """
    from agno.db.base import AsyncBaseDb, BaseDb
    from agno.tools.agentos import AgentOSTools
    from agno.tools.platform_context import PlatformContextTools
    from agno.tools.studio import StudioTools
    from agno.tools.studio_runner import StudioRunnerTools
    from agno.utils.live_sequence import LiveSequence

    db = agent_os.db
    if db is None:
        raise ValueError("The manager needs AgentOS(db=...): its conversations, builds and diagnostics live there")
    if isinstance(db, AsyncBaseDb) or not isinstance(db, BaseDb):
        raise ValueError("The manager needs a synchronous OS database; the Studio tools write the component catalog")
    registry = agent_os.registry
    if registry is None:
        raise ValueError("The manager needs the OS registry to be set before it is built")
    _raise_if_reserved_ids(
        [
            *(agent_os.agents or []),
            *(agent_os.teams or []),
            *(agent_os.workflows or []),
            *registry.agents,
            *registry.teams,
            *registry.workflows,
        ],
    )
    model = _resolve_model(agent_os, config)
    registry.add_model(model)
    workspace = _resolve_workspace(config)

    builder = Agent(
        id=BUILDER_ID,
        metadata={"_agno": {"internal": True, "id": BUILDER_ID}},
        name="Platform Builder",
        model=model,
        db=db,
        offload_tool_results=config.offload_tool_results,
        tools=[
            StudioTools(
                registry=registry,
                db=db,
                create_agents=True,
                create_teams=True,
                create_workflows=True,
                versions=True,
                schedules=True,
                default_num_history_runs=5,
                # Create, edit and publish keep version history. Archive and delete
                # operations remove access or data, so they require confirmation.
                requires_confirmation_tools=["archive_component", "delete_version", "delete_schedule"],
            ),
        ],
        instructions=BUILDER_INSTRUCTIONS,
        add_datetime_to_context=True,
        add_history_to_context=True,
        num_history_runs=5,
    )

    # Resolves the items the UI references; the OS discovers its databases later.
    manager_db: BaseDb = db

    def platform_context() -> PlatformContextTools:
        return PlatformContextTools(db=manager_db, get_dbs=lambda: dict(agent_os.dbs))

    operator_tools = [AgentOSTools(db=db), platform_context(), _diagnostics_tool(agent_os, config.required_env)]
    operator_instructions = [OPERATOR_INSTRUCTIONS]
    if workspace is not None:
        operator_tools.extend(workspace.get_tools())
        operator_instructions.append(workspace.instructions())
    if config.access_docs:
        try:
            from agno.tools.mcp import MCPTools
        except ImportError:
            from agno.utils.log import log_warning

            log_warning("Agno docs access is unavailable: install agno[mcp] to enable it.")
        else:
            # MCPTools.connect logs connection failures and cleans up partial sessions.
            # Unavailable MCP tools are skipped during runs, leaving platform tools usable.
            operator_tools.append(MCPTools(url="https://docs.agno.com/mcp"))

    operator = Agent(
        id=OPERATOR_ID,
        metadata={"_agno": {"internal": True, "id": OPERATOR_ID}},
        name="Platform Manager",
        model=model,
        db=db,
        offload_tool_results=config.offload_tool_results,
        tools=operator_tools,
        instructions=operator_instructions,
        add_datetime_to_context=True,
        add_history_to_context=True,
        num_history_runs=5,
    )

    members: List[Any] = [builder, operator]
    instructions: List[str] = [MANAGER_INSTRUCTIONS]
    if config.instructions:
        instructions.append(config.instructions)
    team = Team(
        id=config.id,
        metadata={"_agno": {"internal": True, "id": config.id}},
        name=config.name,
        model=model,
        db=db,
        offload_tool_results=config.offload_tool_results,
        learning=config.learning,
        knowledge=config.knowledge,
        tools=[
            *config.tools,
            # The manager can run served components, including itself once.
            StudioRunnerTools(
                registry=registry,
                db=db,
                include_agents=LiveSequence(lambda: agent_os._agents),
                include_teams=LiveSequence(lambda: agent_os._teams),
                include_workflows=LiveSequence(lambda: agent_os._workflows),
                include_all_components=True,
                self_dispatch="once",
            ),
            platform_context(),
        ],
        members=members,
        instructions=instructions,
        # Fill the page context placeholders in MANAGER_INSTRUCTIONS when the UI
        # sends none; its run dependencies override these.
        dependencies={"page_context": "not provided", "context_refs": "none"},
        search_past_sessions=True,
        add_datetime_to_context=True,
        add_history_to_context=True,
        num_history_runs=config.num_history_runs,
    )
    registry.reserve_component_ids(RESERVED_MEMBER_IDS | {config.id})
    registry.exclude_components([team, *members])
    return _Manager(config=config, team=team, builder=builder, operator=operator)
