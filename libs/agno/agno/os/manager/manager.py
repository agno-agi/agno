"""Create Super Agent and Platform Builder."""

import asyncio
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

from agno.agent import Agent
from agno.agents.base import BaseExternalAgent
from agno.os.manager.config import OSManager
from agno.os.manager.prompts import (
    BUILDER_INSTRUCTIONS,
    COMPANY_FILES_INSTRUCTIONS,
    COMPANY_INSTRUCTIONS,
    DOCS_INSTRUCTIONS,
    FOCUSED_EXECUTION_INSTRUCTIONS,
    MANAGER_INSTRUCTIONS,
    NO_PRIVATE_PLACE_INSTRUCTIONS,
    NOTES_INSTRUCTIONS,
    PRIVATE_MEMORY_INSTRUCTIONS,
    SOURCE_INSTRUCTIONS,
)
from agno.registry._reserved import BUILDER_ID, RESERVED_MANAGER_IDS, RESERVED_MEMBER_IDS, _listed
from agno.run.authorization import _caller_authorization, requires_permission
from agno.team import Team

if TYPE_CHECKING:
    from agno.os.app import AgentOS


@dataclass
class _Manager:
    """Super Agent, its configuration and Platform Builder."""

    config: OSManager
    team: Team
    builder: Agent

    @property
    def components(self) -> List[Any]:
        return [self.team, self.builder]

    def owns(self, component: Any) -> bool:
        """Check whether this object is the manager team or one of its members."""
        return any(component is owned for owned in self.components)

    def manifest(self) -> Dict[str, Any]:
        """Default description and prompts for the public manager team."""
        from agno.os.config import Manifest

        entries = {
            self.config.id: Manifest(
                description="Runs your agents, keeps company work on record, builds components and checks the AgentOS.",
                quick_prompts=[
                    "What can you help me do?",
                    "What agents and workflows can I run?",
                    "Run diagnostics and explain any issues",
                ],
            ),
        }
        return entries


_CATALOG_LIMIT = 20


def _remembers_people(learning: Any) -> bool:
    """Whether Super Agent keeps a memory of each person: learning with a user profile or a user memory."""
    if learning is True:
        return True
    return bool(getattr(learning, "user_profile", False) or getattr(learning, "user_memory", False))


class _ManagerInstructions:
    """Super Agent's instructions for one run: the fixed text, the company details and the components
    the caller can run."""

    def __init__(self, base: List[str], runner: Any, company_db: Any = None):
        from agno.company.details import _company_instructions

        self.base = base
        self.runner = runner
        self.company: Any = _company_instructions(company_db, base) if company_db is not None else None

    def __copy__(self) -> "_ManagerInstructions":
        # Holds no run state. A run copy of the team keeps this object, so the copy is
        # recognized as the same component.
        return self

    def _kind_rows(self, kind: str, run_context: Any) -> Tuple[List[Dict[str, Any]], bool]:
        """Published components of one kind that the runner admits, without the framework's own.

        The second value is True when the stored query returned a full page. Drafts and permissions are
        filtered after the query, so a full page can hide published components behind it.
        """
        actor = getattr(run_context, "user_id", None)
        stored, _ = self.runner._list_db_component_rows(kind, limit=_CATALOG_LIMIT + 1, user_id=actor)
        rows: List[Dict[str, Any]] = []
        seen: set = set()
        for row in [*self.runner._admitted_code_components(kind), *stored]:
            component_id = row.get("id")
            if component_id in seen or component_id in RESERVED_MANAGER_IDS or row.get("status") == "draft":
                continue
            seen.add(component_id)
            rows.append({**row, "kind": kind})
        return rows, len(stored) > _CATALOG_LIMIT

    @staticmethod
    def _read_check(authority: Any, row: Dict[str, Any]) -> Any:
        return replace(authority.context, resource_type=row["kind"] + "s", resource_id=row["id"], action="read")

    @staticmethod
    def _catalog(rows: List[Dict[str, Any]], more: bool = False) -> List[str]:
        lines = []
        for row in rows[:_CATALOG_LIMIT]:
            description = (row.get("description") or "").strip().split("\n")[0][:120]
            name = row.get("name") or row["id"]
            lines.append(f"- {name} ({row['kind']}, id {row['id']})" + (f": {description}" if description else ""))
        if more or len(rows) > _CATALOG_LIMIT:
            lines.append("More exist: call list_agents, list_teams or list_workflows.")
        return ["Components you can run:\n" + "\n".join(lines)] if lines else []

    def __call__(self, run_context: Any = None) -> List[str]:
        base = self.company(run_context) if self.company is not None else list(self.base)
        authority = _caller_authorization(run_context)
        # One entry past the limit shows that more exist. Nothing after it is listed or checked.
        rows: List[Dict[str, Any]] = []
        more = False
        try:
            for kind in ("agent", "team", "workflow"):
                if len(rows) > _CATALOG_LIMIT:
                    break
                found, full_page = self._kind_rows(kind, run_context)
                more = more or full_page
                for row in found:
                    if authority is None or authority.provider.check(self._read_check(authority, row)):
                        rows.append(row)
                    if len(rows) > _CATALOG_LIMIT:
                        break
        except Exception as exc:
            from agno.utils.log import log_warning

            log_warning(f"Component catalog unavailable for this run: {exc}")
            return base
        return [*base, *self._catalog(rows, more)]

    async def __acall__(self, run_context: Any = None) -> List[str]:
        base = await self.company.__acall__(run_context) if self.company is not None else list(self.base)
        authority = _caller_authorization(run_context)
        rows: List[Dict[str, Any]] = []
        more = False
        try:
            for kind in ("agent", "team", "workflow"):
                if len(rows) > _CATALOG_LIMIT:
                    break
                found, full_page = await asyncio.to_thread(self._kind_rows, kind, run_context)
                more = more or full_page
                for row in found:
                    if authority is None or await authority.provider.acheck(self._read_check(authority, row)):
                        rows.append(row)
                    if len(rows) > _CATALOG_LIMIT:
                        break
        except Exception as exc:
            from agno.utils.log import log_warning

            log_warning(f"Component catalog unavailable for this run: {exc}")
            return base
        return [*base, *self._catalog(rows, more)]


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
        # Default exclusions block environment and credential files.
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


_SOURCE_TOOL_NAMES = frozenset({"list_files", "read_file", "search_content"})


def _raise_if_source_tool_names_taken(tools: Sequence[Any]) -> None:
    """Refuse application tools that would replace the source file tools on Super Agent."""
    taken: set = set()
    for tool in tools:
        names = getattr(tool, "functions", None)
        taken |= set(names) if names else {getattr(tool, "name", None) or getattr(tool, "__name__", None)}
    clash = sorted(str(name) for name in taken & _SOURCE_TOOL_NAMES)
    if clash:
        raise ValueError(
            f"OSManager.tools defines {', '.join(clash)}, which OSManager.root also adds to Super Agent. "
            "Rename the tool or remove root."
        )


def _holds_files(db: Any) -> bool:
    """Whether the database can hold a FileSystem namespace: SQLite and PostgreSQL can."""
    from agno.fs import FileSystem

    try:
        FileSystem(db, namespace="company/notes", user_scoped=False)
    except (TypeError, ValueError):
        return False
    return True


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
    from agno.company.routines import _RoutineBoundary
    from agno.db.base import AsyncBaseDb, BaseDb
    from agno.tools.agentos import AgentOSTools
    from agno.tools.studio import StudioTools
    from agno.tools.studio_runner import StudioRunnerTools
    from agno.utils.live_sequence import LiveSequence

    db = agent_os.db
    if db is None:
        raise ValueError("The manager needs AgentOS(db=...): its conversations, builds and diagnostics live there")
    if isinstance(db, AsyncBaseDb) or not isinstance(db, BaseDb):
        raise ValueError("The manager needs a synchronous OS database; the Studio tools write the component catalog")
    from agno.registry._reserved import _check_manager_catalog

    _check_manager_catalog(agent_os, db)
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
    if workspace is not None:
        _raise_if_source_tool_names_taken(config.tools)

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
        instructions=[BUILDER_INSTRUCTIONS, FOCUSED_EXECUTION_INSTRUCTIONS],
        tool_call_limit=config.member_tool_call_limit,
        add_datetime_to_context=True,
        add_history_to_context=True,
        num_history_runs=5,
    )

    def manifest_description(component_id: str) -> Optional[str]:
        # Read live configuration: manager defaults are merged after this team is built,
        # and run copies must see the same descriptions as the served OS.
        manifest = agent_os.config.manifest if agent_os.config is not None else None
        entry = manifest.get(component_id) if manifest else None
        return entry.description if entry is not None else None

    # The manager can run served components, including itself once.
    runner = StudioRunnerTools(
        registry=registry,
        db=db,
        include_agents=LiveSequence(
            lambda: [a for a in _listed(agent_os.agents) if isinstance(a, (Agent, BaseExternalAgent))]
        ),
        include_teams=LiveSequence(lambda: agent_os._teams),
        include_workflows=LiveSequence(lambda: agent_os._workflows),
        include_all_components=True,
        self_dispatch="once",
        description_fallback=manifest_description,
    )
    tools: List[Any] = [
        *config.tools,
        runner,
        AgentOSTools(db=db, include_tools=["get_run_activity", "list_schedules"], add_instructions=False),
        _diagnostics_tool(agent_os, config.required_env),
    ]
    instructions: List[str] = [MANAGER_INSTRUCTIONS]
    if config.access_docs:
        try:
            from agno.tools.mcp import MCPTools
        except ImportError:
            from agno.utils.log import log_warning

            log_warning("Agno docs access is unavailable: install agno[mcp] to enable it.")
        else:
            # MCPTools.connect logs connection failures and cleans up partial sessions.
            # Unavailable MCP tools are skipped during runs, leaving the other tools usable.
            tools.append(MCPTools(url="https://docs.agno.com/mcp"))
            instructions.append(DOCS_INSTRUCTIONS)
    if workspace is not None:
        tools.extend(workspace.get_tools())
        instructions.append(SOURCE_INSTRUCTIONS)
    company_db = agent_os._company_db
    if company_db is not None:
        from agno.os.manager.company_tasks import CompanyTaskTools
        from agno.tools.company import CompanyTools

        tools.append(
            # The file tree tools below read and write the wiki and every Product's pages.
            CompanyTools(
                company_db,
                summary_tools=False,
                refresh_tools=False,
                wiki_tools=False,
                decision_tools=False,
                agent_id=config.id,
            )
        )
        tools.append(CompanyTaskTools(agent_os))
        instructions.append(COMPANY_INSTRUCTIONS)
    # notes/ lives in the OS database with Super Agent's conversations, with or without Company.
    notes_db = db if _holds_files(db) else None
    if company_db is not None or notes_db is not None:
        from agno.os.manager.company_tasks import _user_isolation
        from agno.tools.company_files import CompanyFileTools

        tools.append(CompanyFileTools(company_db, notes_db=notes_db, user_isolation=_user_isolation(agent_os)))
        instructions.append(COMPANY_FILES_INSTRUCTIONS if company_db is not None else NOTES_INSTRUCTIONS)
        if notes_db is not None:
            instructions.append(
                PRIVATE_MEMORY_INSTRUCTIONS if _remembers_people(config.learning) else NO_PRIVATE_PLACE_INSTRUCTIONS
            )
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
        tools=tools,
        members=[builder],
        instructions=_ManagerInstructions(instructions, runner, company_db),
        # Super Agent can edit the platform, so a Company Routine never runs on it.
        pre_hooks=[_RoutineBoundary(routine=False)],
        tool_call_limit=config.tool_call_limit,
        search_past_sessions=True,
        read_chat_history=True,
        add_datetime_to_context=True,
        add_history_to_context=True,
        num_history_runs=config.num_history_runs,
    )
    registry.reserve_component_ids(RESERVED_MEMBER_IDS | {config.id})
    registry.exclude_components([team, builder])
    return _Manager(config=config, team=team, builder=builder)
