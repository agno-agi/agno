"""Typed, authorization-gated Studio control-plane tools.

``StudioTools`` lets an administrator compose versioned agents, teams, and
workflows from the live AgentOS registry.  The 2.9 API is intentionally
breaking: requests and responses are typed, one catalog database is fixed at
construction time, creates are draft-first, edits use optimistic concurrency,
and destructive lifecycle operations archive rather than hard-delete.

The data-plane ``run_*`` behavior remains owned by :class:`StudioRunnerTools`.
Studio wraps that runner so authorization is applied consistently without
duplicating its resolution, rehydration, identity, or pause/resume semantics.
"""

from __future__ import annotations

import asyncio
import inspect
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Sequence, Union, cast

from agno.db.schemas.scheduler import (
    STUDIO_SCHEDULE_MANAGED_BY,
    Schedule,
    ScheduleNameConflictError,
    is_valid_studio_schedule_actor_id,
)
from agno.run import RunContext
from agno.tools.function import Function
from agno.tools.studio_runner import StudioRunnerTools, _slugify
from agno.tools.studio_schema import (
    AgentCreate,
    AgentPatch,
    AgentView,
    AgentWorkflowStep,
    ComponentActionView,
    ComponentRef,
    ComponentSummary,
    ComponentView,
    ContextPolicy,
    FunctionRef,
    FunctionWorkflowStep,
    ModelRef,
    ScheduleActionView,
    ScheduleCreate,
    ScheduleRunView,
    ScheduleView,
    StudioError,
    StudioResult,
    TeamCreate,
    TeamPatch,
    TeamView,
    TeamWorkflowStep,
    ToolRef,
    VersionSummary,
    WorkflowCreate,
    WorkflowPatch,
    WorkflowStep,
    WorkflowView,
)
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, logger

if TYPE_CHECKING:
    from agno.agent.agent import Agent
    from agno.db.base import BaseDb, ComponentProjection, ComponentType
    from agno.db.schemas.scheduler import ScheduleRun
    from agno.models.base import Model
    from agno.registry.registry import Registry
    from agno.scheduler.manager import ScheduleManager
    from agno.team.team import Team
    from agno.tools.scheduler import SchedulerTools
    from agno.workflow.workflow import Workflow

Component = Union["Agent", "Team", "Workflow"]
TeamMember = Union["Agent", "Team"]
SaveStage = Literal["draft", "published"]
IfExists = Literal["error", "return_existing"]
StudioAccess = Literal["read", "mutate"]
StudioAction = Literal[
    "list_models",
    "list_tools",
    "list_functions",
    "list_agents",
    "list_teams",
    "list_workflows",
    "get_agent",
    "get_team",
    "get_workflow",
    "list_versions",
    "get_version",
    "create_agent",
    "create_team",
    "create_workflow",
    "edit_agent",
    "edit_team",
    "edit_workflow",
    "publish_component",
    "set_current_version",
    "delete_version",
    "archive_agent",
    "archive_team",
    "archive_workflow",
    "run_agent",
    "run_team",
    "run_workflow",
    "create_schedule",
    "list_schedules",
    "get_schedule",
    "get_schedule_runs",
    "trigger_schedule",
    "enable_schedule",
    "disable_schedule",
    "delete_schedule",
]
StudioAuthorizer = Callable[[RunContext, StudioAccess, StudioAction], bool]

_STUDIO_CONFIG_KEY = "_agno_studio"
_STUDIO_SCHEMA_VERSION = 2
_SCHEDULE_TARGET_TYPES = ("agent", "team", "workflow")


@dataclass(frozen=True)
class _ResolvedRef:
    component: Component
    ref: ComponentRef
    link: Optional[Dict[str, Any]]
    code_defined: bool


class _StudioRequestError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.retryable = retryable


class StudioTools(Toolkit):
    """Administrative tools for composing and versioning Studio components.

    Args:
        registry: Live registry that supplies exact models, tools, functions,
            and code-defined component references.
        db: The single catalog database used for every Studio lifecycle call.
        authorize: Required synchronous policy callback. It receives the
            framework-injected ``RunContext``, access kind, and exact action.
            Returning false rejects the call before any registry or DB access.
        agents_list: Optional live code-defined agents used for discovery and
            draft composition.
        teams_list: Optional live code-defined teams used for discovery and
            draft composition.
        workflows_list: Optional live code-defined workflows used for discovery.
        default_model: Exact registry reference used when a create/patch model
            is null. No implicit first-registry-model fallback is used.
        default_context: Resolved context policy used when a create request's
            context is null.
        agents: Expose agent operations (default true).
        teams: Expose team operations. Supplying ``agents_list`` or
            ``teams_list`` auto-enables this unless explicitly overridden.
        workflows: Expose workflow operations. Supplying an agents, teams, or
            workflows list auto-enables this unless explicitly overridden.
        schedules: Expose authorization-wrapped schedule operations.
        list_limit: Maximum DB rows returned per component list.
    """

    def __init__(
        self,
        registry: "Registry",
        db: "BaseDb",
        authorize: StudioAuthorizer,
        *,
        agents_list: Optional[List["Agent"]] = None,
        teams_list: Optional[List["Team"]] = None,
        workflows_list: Optional[List["Workflow"]] = None,
        default_model: Optional[ModelRef] = None,
        default_context: Optional[ContextPolicy] = None,
        agents: Optional[bool] = None,
        teams: Optional[bool] = None,
        workflows: Optional[bool] = None,
        schedules: bool = False,
        list_limit: int = 100,
        **kwargs: Any,
    ) -> None:
        if db is None:
            raise ValueError("StudioTools requires one fixed catalog db")
        if not getattr(db, "supports_component_persistence", False):
            raise ValueError(
                "StudioTools requires a synchronous catalog db with atomic component persistence; "
                "use SqliteDb or PostgresDb."
            )
        if not callable(authorize):
            raise TypeError("StudioTools authorize must be callable")
        if inspect.iscoroutinefunction(authorize):
            raise TypeError("StudioTools authorize must be synchronous")
        if list_limit < 1:
            raise ValueError("list_limit must be at least 1")

        self.registry = registry
        self.db = db
        self.authorize = authorize
        self.agents_list = agents_list
        self.teams_list = teams_list
        self.workflows_list = workflows_list
        self.default_model = default_model
        self.default_context = default_context or ContextPolicy()
        self.list_limit = list_limit

        self.enable_agents, self.enable_teams, self.enable_workflows = _resolve_flags(
            agents=agents,
            teams=teams,
            workflows=workflows,
            has_agents_list=agents_list is not None,
            has_teams_list=teams_list is not None,
            has_workflows_list=workflows_list is not None,
        )
        self.enable_schedules = schedules

        if self.enable_workflows:
            self._validate_workflow_function_catalog()

        self._runner_tools = StudioRunnerTools(
            registry=registry,
            db=db,
            agents_list=agents_list,
            teams_list=teams_list,
            workflows_list=workflows_list,
            include_all_components=True,
            list_limit=list_limit,
        )

        self._scheduler_tools: Optional["SchedulerTools"] = None
        if schedules:
            from agno.tools.scheduler import SchedulerTools

            self._scheduler_tools = SchedulerTools(db=db)

        tools: List[Callable[..., Any]] = [
            self.list_models,
            self.list_tools,
            self.list_functions,
        ]
        async_tools: List[tuple[Callable[..., Any], str]] = [
            (self.alist_models, "list_models"),
            (self.alist_tools, "list_tools"),
            (self.alist_functions, "list_functions"),
        ]

        if self.enable_agents or self.enable_teams or self.enable_workflows:
            tools.extend(
                [
                    self.list_versions,
                    self.get_version,
                    self.publish_component,
                    self.set_current_version,
                    self.delete_version,
                ]
            )
            async_tools.extend(
                [
                    (self.alist_versions, "list_versions"),
                    (self.aget_version, "get_version"),
                    (self.apublish_component, "publish_component"),
                    (self.aset_current_version, "set_current_version"),
                    (self.adelete_version, "delete_version"),
                ]
            )

        if self.enable_agents:
            tools.extend(
                [
                    self.list_agents,
                    self.get_agent,
                    self.create_agent,
                    self.edit_agent,
                    self.archive_agent,
                    self.run_agent,
                ]
            )
            async_tools.extend(
                [
                    (self.alist_agents, "list_agents"),
                    (self.aget_agent, "get_agent"),
                    (self.acreate_agent, "create_agent"),
                    (self.aedit_agent, "edit_agent"),
                    (self.aarchive_agent, "archive_agent"),
                    (self.arun_agent, "run_agent"),
                ]
            )
        if self.enable_teams:
            tools.extend(
                [
                    self.list_teams,
                    self.get_team,
                    self.create_team,
                    self.edit_team,
                    self.archive_team,
                    self.run_team,
                ]
            )
            async_tools.extend(
                [
                    (self.alist_teams, "list_teams"),
                    (self.aget_team, "get_team"),
                    (self.acreate_team, "create_team"),
                    (self.aedit_team, "edit_team"),
                    (self.aarchive_team, "archive_team"),
                    (self.arun_team, "run_team"),
                ]
            )
        if self.enable_workflows:
            tools.extend(
                [
                    self.list_workflows,
                    self.get_workflow,
                    self.create_workflow,
                    self.edit_workflow,
                    self.archive_workflow,
                    self.run_workflow,
                ]
            )
            async_tools.extend(
                [
                    (self.alist_workflows, "list_workflows"),
                    (self.aget_workflow, "get_workflow"),
                    (self.acreate_workflow, "create_workflow"),
                    (self.aedit_workflow, "edit_workflow"),
                    (self.aarchive_workflow, "archive_workflow"),
                    (self.arun_workflow, "run_workflow"),
                ]
            )
        if schedules:
            tools.extend(
                [
                    self.create_schedule,
                    self.list_schedules,
                    self.get_schedule,
                    self.get_schedule_runs,
                    self.trigger_schedule,
                    self.enable_schedule,
                    self.disable_schedule,
                    self.delete_schedule,
                ]
            )
            async_tools.extend(
                [
                    (self.acreate_schedule, "create_schedule"),
                    (self.alist_schedules, "list_schedules"),
                    (self.aget_schedule, "get_schedule"),
                    (self.aget_schedule_runs, "get_schedule_runs"),
                    (self.atrigger_schedule, "trigger_schedule"),
                    (self.aenable_schedule, "enable_schedule"),
                    (self.adisable_schedule, "disable_schedule"),
                    (self.adelete_schedule, "delete_schedule"),
                ]
            )

        instruction_lines = [
            "Use Studio as an administrative control plane for versioned agents, teams, and workflows.",
            "Call list_models/list_tools/list_functions and copy their exact typed references; never guess names.",
            "Create calls take one typed request object and save a draft by default. Component ids are stable; an omitted id is the deterministic slug of the name.",
            "A component id conflict never creates a suffixed id. Use if_exists='return_existing' only to retry an identical request.",
            "Edits take one typed patch plus expected_version. A version conflict means you must read the latest version and intentionally retry.",
            "Publish is explicit. Code-defined composite references may be explored in drafts but must be persisted and pinned before publication.",
            "Create and edit calls require confirmation even for drafts because either call can publish via save_as.",
            "get_version returns a safe typed view, never the raw persisted configuration.",
            "Archive requires an exact component id and refuses components or versions that active configs depend on.",
            "Run calls use the current published version; a draft is never dispatched as current.",
        ]
        if self.enable_teams:
            instruction_lines.append("Team members are typed ComponentRef values, including their component type.")
        if self.enable_workflows:
            instruction_lines.append("Workflow steps are discriminated by kind: agent, team, or function.")
        if schedules:
            instruction_lines.append("Every schedule operation is authorization-gated like component operations.")

        # Confirmation is currently configured per tool, not per invocation.
        # Since every create/edit tool accepts save_as="published", the only
        # truthful way to guarantee confirmation for all publication paths is
        # to confirm draft calls too.
        confirmation_actions = {
            "create_agent",
            "create_team",
            "create_workflow",
            "edit_agent",
            "edit_team",
            "edit_workflow",
            "publish_component",
            "set_current_version",
            "delete_version",
            "archive_agent",
            "archive_team",
            "archive_workflow",
            "create_schedule",
            "trigger_schedule",
            "enable_schedule",
            "disable_schedule",
            "delete_schedule",
        }
        available_tool_names = {tool.__name__ for tool in tools}
        configured_confirmations = set(kwargs.pop("requires_confirmation_tools", []) or [])
        kwargs["requires_confirmation_tools"] = sorted(
            configured_confirmations | (confirmation_actions & available_tool_names)
        )
        kwargs.setdefault("add_instructions", True)
        super().__init__(
            name="studio",
            tools=tools,
            async_tools=async_tools,
            instructions="\n".join(instruction_lines),
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Result and authorization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _success(status: str, data: Any, warnings: Optional[List[str]] = None) -> StudioResult[Any]:
        return StudioResult[Any](ok=True, status=status, data=data, warnings=warnings or [])

    @staticmethod
    def _failure(
        code: str,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = False,
    ) -> StudioResult[Any]:
        return StudioResult[Any](
            ok=False,
            status="error",
            error=StudioError(code=code, message=message, details=details or {}, retryable=retryable),
        )

    def _authorize(
        self,
        action: StudioAction,
        access: StudioAccess,
        run_context: Optional[RunContext],
    ) -> Optional[StudioResult[Any]]:
        if not isinstance(run_context, RunContext):
            return self._failure(
                "auth_context_required",
                "Studio requires a framework-injected RunContext.",
            )
        if not run_context.user_id:
            return self._failure("unauthenticated", "Studio requires an authenticated actor.")
        try:
            allowed = self.authorize(run_context, access, action)
        except Exception:
            logger.error("Studio authorization callback failed for action=%s", action)
            return self._failure("authorization_failed", "Studio authorization failed.")
        if not isinstance(allowed, bool):
            logger.error("Studio authorization callback returned a non-boolean value for action=%s", action)
            return self._failure("authorization_failed", "Studio authorization failed.")
        if not allowed:
            return self._failure("forbidden", "The actor is not allowed to perform this Studio action.")
        return None

    @staticmethod
    def _request_failure(error: _StudioRequestError) -> StudioResult[Any]:
        return StudioTools._failure(
            error.code,
            error.message,
            details=error.details,
            retryable=error.retryable,
        )

    @staticmethod
    def _internal_failure(action: str) -> StudioResult[Any]:
        # Backend exceptions can contain DSNs, credentials, or private payloads.
        # Keep the operator signal while leaving exception details to the caller's
        # explicit diagnostics boundary.
        logger.error("Studio %s failed", action)
        return StudioTools._failure("internal_error", f"Studio could not {action}.", retryable=True)

    @staticmethod
    def _validate_save_as(save_as: Any) -> SaveStage:
        if save_as not in ("draft", "published"):
            raise _StudioRequestError(
                "invalid_save_stage",
                "save_as must be either 'draft' or 'published'.",
                details={"allowed": ["draft", "published"]},
            )
        return cast(SaveStage, save_as)

    @staticmethod
    def _validate_if_exists(if_exists: Any) -> IfExists:
        if if_exists not in ("error", "return_existing"):
            raise _StudioRequestError(
                "invalid_if_exists",
                "if_exists must be either 'error' or 'return_existing'.",
                details={"allowed": ["error", "return_existing"]},
            )
        return cast(IfExists, if_exists)

    @staticmethod
    def _validate_component_id(component_id: Any) -> str:
        if (
            not isinstance(component_id, str)
            or not component_id
            or not component_id[0].isascii()
            or not component_id[0].isalnum()
            or any(
                not character.isascii() or not (character.isalnum() or character in "._-") for character in component_id
            )
        ):
            raise _StudioRequestError(
                "invalid_component_id",
                "component_id must start with an ASCII letter or number and contain only letters, numbers, '.', '_', or '-'.",
            )
        return component_id

    def _ensure_component_type_enabled(self, component_type: str) -> None:
        enabled = {
            "agent": self.enable_agents,
            "team": self.enable_teams,
            "workflow": self.enable_workflows,
        }.get(component_type)
        if enabled is None:
            raise _StudioRequestError("invalid_component_type", "The component type is invalid.")
        if not enabled:
            raise _StudioRequestError(
                "component_type_disabled",
                f"StudioTools was created with {component_type}s=False.",
                details={"component_type": component_type},
            )

    def _validate_workflow_function_catalog(self) -> None:
        names = [
            name
            for function in self.registry.functions
            if isinstance((name := getattr(function, "__name__", None)), str) and name
        ]
        duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
        if duplicates:
            raise ValueError(
                "StudioTools workflows require unique registered function names; duplicates: " + ", ".join(duplicates)
            )

    def _ensure_no_source_collision(self, component_id: str, component_type: Optional[str] = None) -> None:
        self._validate_component_id(component_id)
        stored = self.db.get_component(component_id, include_deleted=True)
        if stored is None:
            return
        code_types = [
            component_type
            for component_type, candidates in (
                ("agent", self._iter_agents()),
                ("team", self._iter_teams()),
                ("workflow", self._iter_workflows()),
            )
            if any(getattr(candidate, "id", None) == component_id for candidate in candidates)
        ]
        if component_type is not None and (
            stored.get("component_type") != component_type or component_type not in code_types
        ):
            return
        if code_types:
            raise _StudioRequestError(
                "component_source_collision",
                f"Component id '{component_id}' exists in both code and Studio; rename one source before continuing.",
                details={
                    "component_id": component_id,
                    "studio_component_type": stored.get("component_type"),
                    "code_component_types": code_types,
                },
            )

    @staticmethod
    def _safe_dependents(dependents: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        safe: List[Dict[str, Any]] = []
        for dependent in dependents:
            parent_id = dependent.get("parent_component_id")
            parent_version = dependent.get("parent_version")
            if not isinstance(parent_id, str) or not isinstance(parent_version, int):
                continue
            item = {"component_id": parent_id, "version": parent_version}
            if item not in safe:
                safe.append(item)
        return safe

    # ------------------------------------------------------------------
    # Registry and default resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _model_ref(model: Optional["Model"]) -> Optional[ModelRef]:
        if model is None or not getattr(model, "id", None):
            return None
        return ModelRef(
            id=cast(str, model.id),
            provider=getattr(model, "provider", None),
            name=getattr(model, "name", None),
        )

    def _resolve_model(self, model_ref: Optional[ModelRef]) -> tuple["Model", ModelRef]:
        requested = model_ref or self.default_model
        if requested is None:
            raise _StudioRequestError(
                "model_required",
                "No model was supplied and Studio has no default_model configured.",
            )
        matches = [
            model
            for model in self.registry.models
            if getattr(model, "id", None) == requested.id
            and (requested.provider is None or getattr(model, "provider", None) == requested.provider)
            and (requested.name is None or getattr(model, "name", None) == requested.name)
        ]
        if not matches:
            raise _StudioRequestError(
                "model_not_found",
                "The exact model reference is not registered.",
                details={"model": requested.model_dump(exclude_none=True)},
            )
        if len(matches) > 1:
            raise _StudioRequestError(
                "ambiguous_model",
                "The model reference matches multiple registry entries; include provider and name.",
                details={
                    "model": requested.model_dump(exclude_none=True),
                    "matches": [
                        ref.model_dump(exclude_none=True)
                        for model in matches
                        if (ref := self._model_ref(model)) is not None
                    ],
                },
            )
        model = matches[0]
        resolved = self._model_ref(model)
        if resolved is None:
            raise _StudioRequestError("invalid_model", "The registered model has no id.")
        return model, resolved

    def _resolve_context(self, context: Optional[ContextPolicy]) -> ContextPolicy:
        requested = context or self.default_context
        history_runs = requested.history_runs
        if history_runs is None and requested.include_history:
            history_runs = self.default_context.history_runs
        return ContextPolicy(
            include_history=requested.include_history,
            history_runs=history_runs if requested.include_history else None,
            include_datetime=requested.include_datetime,
        )

    def _tool_catalog(self) -> List[tuple[ToolRef, Any]]:
        catalog: List[tuple[ToolRef, Any]] = []
        for tool in self.registry.tools:
            if isinstance(tool, Toolkit):
                catalog.append((ToolRef(kind="toolkit", name=tool.name), tool))
                for function_name, function in tool.get_functions().items():
                    catalog.append((ToolRef(kind="function", name=function_name, toolkit=tool.name), function))
            elif isinstance(tool, Function):
                catalog.append((ToolRef(kind="function", name=tool.name), tool))
            elif callable(tool):
                name = getattr(tool, "__name__", None)
                if isinstance(name, str) and name:
                    catalog.append((ToolRef(kind="function", name=name), tool))
        return catalog

    def _resolve_tools(self, refs: Sequence[ToolRef]) -> List[Any]:
        catalog = self._tool_catalog()
        resolved: List[Any] = []
        claimed_names: Dict[str, ToolRef] = {}
        for ref in refs:
            matches = [tool for candidate, tool in catalog if candidate == ref]
            if not matches:
                raise _StudioRequestError(
                    "tool_not_found",
                    "The exact tool reference is not registered.",
                    details={"tool": ref.model_dump(exclude_none=True)},
                )
            if len(matches) > 1:
                raise _StudioRequestError(
                    "ambiguous_tool",
                    "The tool reference matches multiple registry entries.",
                    details={"tool": ref.model_dump(exclude_none=True)},
                )
            tool = matches[0]
            if ref.kind == "function" and ref.toolkit is None:
                flat_sources: List[Any] = []
                for registered in self.registry.tools:
                    if isinstance(registered, Toolkit):
                        source = registered.get_functions().get(ref.name)
                        if source is not None:
                            flat_sources.append(source)
                    elif isinstance(registered, Function) and registered.name == ref.name:
                        flat_sources.append(registered)
                    elif callable(registered) and getattr(registered, "__name__", None) == ref.name:
                        flat_sources.append(registered)
                entrypoint_ids = {
                    id(source.entrypoint if isinstance(source, Function) and source.entrypoint is not None else source)
                    for source in flat_sources
                }
                if len(entrypoint_ids) > 1:
                    raise _StudioRequestError(
                        "ambiguous_tool_binding",
                        f"Unqualified function '{ref.name}' has multiple live registry entrypoints; qualify the "
                        "toolkit or give the functions distinct names.",
                        details={"tool": ref.model_dump(exclude_none=True)},
                    )
            if isinstance(tool, Toolkit) and not tool.functions:
                raise _StudioRequestError(
                    "toolkit_not_ready",
                    f"Toolkit '{tool.name}' has no connected functions and cannot be persisted.",
                )
            functions = list(tool.get_functions().values()) if isinstance(tool, Toolkit) else [tool]
            unavailable_functions = sorted(
                function.name
                for function in functions
                if isinstance(function, Function) and function.entrypoint is None and not function.external_execution
            )
            if unavailable_functions:
                raise _StudioRequestError(
                    "tool_not_ready",
                    "The selected tool reference contains functions without live entrypoints.",
                    details={
                        "tool": ref.model_dump(exclude_none=True),
                        "functions": unavailable_functions,
                    },
                )
            if isinstance(tool, Function) and ref.toolkit:
                tool.owning_toolkit = ref.toolkit
            exposed_names = list(tool.get_functions()) if isinstance(tool, Toolkit) else [ref.name]
            for function_name in exposed_names:
                previous = claimed_names.get(function_name)
                if previous is not None:
                    raise _StudioRequestError(
                        "duplicate_tool_name",
                        f"Selected tool references both expose function name '{function_name}', which Agent would "
                        "otherwise resolve by registration order.",
                        details={
                            "function_name": function_name,
                            "first": previous.model_dump(exclude_none=True),
                            "second": ref.model_dump(exclude_none=True),
                        },
                    )
                claimed_names[function_name] = ref
            resolved.append(tool)
        return resolved

    def _iter_agents(self) -> List["Agent"]:
        return self._runner_tools._iter_agents()

    def _iter_teams(self) -> List["Team"]:
        return self._runner_tools._iter_teams()

    def _iter_workflows(self) -> List["Workflow"]:
        return self._runner_tools._iter_workflows()

    def _code_component(self, component_type: str, component_id: str) -> Optional[Component]:
        candidates: Sequence[Component]
        if component_type == "agent":
            candidates = self._iter_agents()
        elif component_type == "team":
            candidates = self._iter_teams()
        else:
            candidates = self._iter_workflows()
        matches = [candidate for candidate in candidates if getattr(candidate, "id", None) == component_id]
        if len(matches) > 1:
            raise _StudioRequestError(
                "ambiguous_component",
                f"Multiple code-defined {component_type}s use component_id '{component_id}'.",
            )
        return matches[0] if matches else None

    def _db_component(self, component_type: str, component_id: str) -> Optional[Dict[str, Any]]:
        from agno.db.base import ComponentType

        return self.db.get_component(component_id, component_type=ComponentType(component_type))

    def _load_db_component(
        self,
        component_type: str,
        component_id: str,
        version: Optional[int],
        *,
        for_dispatch: bool = False,
    ) -> Optional[Component]:
        if component_type == "agent":
            return self._runner_tools._load_agent_from_db(
                component_id,
                version=version,
                for_dispatch=for_dispatch,
            )
        if component_type == "team":
            return self._runner_tools._load_team_from_db(
                component_id,
                version=version,
                for_dispatch=for_dispatch,
            )
        return self._runner_tools._load_workflow_from_db(
            component_id,
            version=version,
            for_dispatch=for_dispatch,
        )

    def _resolve_component_ref(
        self,
        ref: ComponentRef,
        *,
        link_kind: str,
        link_key: str,
        position: int,
    ) -> _ResolvedRef:
        self._ensure_no_source_collision(ref.component_id, ref.component_type)
        row = self._db_component(ref.component_type, ref.component_id)
        if row is not None:
            version = ref.version if ref.version is not None else row.get("current_version")
            if version is None:
                raise _StudioRequestError(
                    "published_version_required",
                    f"Component '{ref.component_id}' has no current published version; publish it first.",
                )
            config = self.db.get_config(ref.component_id, version=version)
            if config is None:
                raise _StudioRequestError(
                    "version_not_found",
                    f"Version {version} was not found for component '{ref.component_id}'.",
                )
            if config.get("stage") != "published":
                raise _StudioRequestError(
                    "published_version_required",
                    f"Component '{ref.component_id}' v{version} is a draft; publish it before referencing it.",
                )
            component = self._load_db_component(ref.component_type, ref.component_id, version)
            if component is None:
                raise _StudioRequestError(
                    "component_rehydration_failed",
                    f"Component '{ref.component_id}' v{version} could not be faithfully rehydrated.",
                )
            pinned_ref = ComponentRef(
                component_type=ref.component_type,
                component_id=ref.component_id,
                version=version,
            )
            return _ResolvedRef(
                component=component,
                ref=pinned_ref,
                link={
                    "link_kind": link_kind,
                    "link_key": link_key,
                    "child_component_id": ref.component_id,
                    "child_version": version,
                    "position": position,
                    "meta": {"type": ref.component_type},
                },
                code_defined=False,
            )

        if ref.version is not None:
            raise _StudioRequestError(
                "component_not_found",
                f"Stored {ref.component_type} '{ref.component_id}' was not found for pinned version {ref.version}.",
            )
        component = self._code_component(ref.component_type, ref.component_id)
        if component is None:
            raise _StudioRequestError(
                "component_not_found",
                f"{ref.component_type.capitalize()} '{ref.component_id}' was not found.",
            )
        return _ResolvedRef(component=component, ref=ref, link=None, code_defined=True)

    def _assert_no_cycle(self, parent_component_id: str, links: Sequence[Dict[str, Any]]) -> None:
        pending = [
            (link.get("child_component_id"), link.get("child_version"))
            for link in links
            if link.get("child_component_id")
        ]
        seen: set[tuple[str, Optional[int]]] = set()
        while pending:
            child_id, child_version = pending.pop()
            key = (cast(str, child_id), cast(Optional[int], child_version))
            if key in seen:
                continue
            seen.add(key)
            if child_id == parent_component_id:
                raise _StudioRequestError(
                    "component_cycle",
                    f"Saving '{parent_component_id}' would create a component dependency cycle.",
                )
            if child_version is None:
                continue
            for child_link in self.db.get_links(cast(str, child_id), cast(int, child_version)):
                nested_id = child_link.get("child_component_id")
                if nested_id:
                    pending.append((nested_id, child_link.get("child_version")))

    @staticmethod
    def _ensure_publishable_refs(refs: Sequence[_ResolvedRef]) -> None:
        code_refs = [resolved.ref.component_id for resolved in refs if resolved.code_defined]
        if code_refs:
            raise _StudioRequestError(
                "code_reference_not_publishable",
                "Published composites require stored, version-pinned child components.",
                details={"code_defined_component_ids": code_refs},
            )

    @staticmethod
    def _actor_metadata(
        existing: Optional[Dict[str, Any]],
        run_context: RunContext,
        action: StudioAction,
    ) -> Dict[str, Any]:
        metadata = dict(existing or {})
        agno_metadata = dict(metadata.get("_agno") or {})
        studio_metadata = dict(agno_metadata.get("studio") or {})
        studio_metadata.setdefault("created_by", run_context.user_id)
        studio_metadata.setdefault("created_run_id", run_context.run_id)
        studio_metadata.setdefault("created_session_id", run_context.session_id)
        studio_metadata.update(
            {
                "last_actor_id": run_context.user_id,
                "last_action": action,
                "last_run_id": run_context.run_id,
                "last_session_id": run_context.session_id,
            }
        )
        agno_metadata["studio"] = studio_metadata
        metadata["_agno"] = agno_metadata
        return metadata

    @staticmethod
    def _manifest(request: Any) -> Dict[str, Any]:
        return {
            "schema_version": _STUDIO_SCHEMA_VERSION,
            "request": request.model_dump(mode="json"),
        }

    @staticmethod
    def _attach_manifest(config: Dict[str, Any], request: Any) -> Dict[str, Any]:
        result = dict(config)
        result[_STUDIO_CONFIG_KEY] = StudioTools._manifest(request)
        return result

    @staticmethod
    def _serialize_component(component: Component, request: Any) -> Dict[str, Any]:
        """Serialize only the top-level component and remove its catalog DB.

        Persisting ``db`` leaks connection configuration and can make a later
        runner reconstruct a second catalog.  The fixed runner DB is the only
        fallback Studio components need.
        """
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
        config.pop("db", None)
        return StudioTools._attach_manifest(config, request)

    @staticmethod
    def _component_type(component: Component) -> "ComponentType":
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

    @staticmethod
    def _manifest_request(config: Dict[str, Any]) -> Dict[str, Any]:
        manifest = config.get(_STUDIO_CONFIG_KEY)
        if not isinstance(manifest, dict) or manifest.get("schema_version") != _STUDIO_SCHEMA_VERSION:
            raise _StudioRequestError(
                "unsupported_component_config",
                "This component was not created with the typed Studio 2.9 contract and cannot be edited safely.",
            )
        request = manifest.get("request")
        if not isinstance(request, dict):
            raise _StudioRequestError("invalid_component_config", "The Studio request manifest is invalid.")
        return request

    @staticmethod
    def _projection(request: Any, metadata: Dict[str, Any]) -> "ComponentProjection":
        return cast(
            "ComponentProjection",
            {
                "name": request.name,
                "description": request.description,
                "metadata": metadata,
            },
        )

    @staticmethod
    def _projected_component_state(
        component: Dict[str, Any],
        request: Any,
        metadata: Dict[str, Any],
        *,
        current_version: int,
    ) -> Dict[str, Any]:
        """Return the component row state committed with a pointer mutation.

        The database mutation already applied these projection values in one
        transaction. Building the response from that committed input avoids a
        public re-read that could observe a later archive and falsely report
        that the successful mutation failed.
        """
        projected = dict(component)
        projected.update(
            {
                "name": request.name,
                "description": request.description,
                "metadata": metadata,
                "current_version": current_version,
            }
        )
        return projected

    def _build_agent(
        self,
        request: AgentCreate,
        metadata: Dict[str, Any],
    ) -> tuple["Agent", AgentCreate]:
        from agno.agent.agent import Agent

        if request.component_id is None:
            raise _StudioRequestError("component_id_required", "The effective agent request has no component_id.")
        model, model_ref = self._resolve_model(request.model)
        context = self._resolve_context(request.context)
        tools = self._resolve_tools(request.tools)
        effective = request.model_copy(
            update={
                "component_id": request.component_id,
                "model": model_ref,
                "context": context,
            }
        )
        agent = Agent(
            id=request.component_id,
            name=request.name,
            instructions=request.instructions,
            description=request.description,
            model=model,
            tools=tools or None,
            db=self.db,
            metadata=metadata,
            add_history_to_context=context.include_history,
            num_history_runs=context.history_runs,
            add_datetime_to_context=context.include_datetime,
        )
        return agent, effective

    def _build_team(
        self,
        request: TeamCreate,
        metadata: Dict[str, Any],
    ) -> tuple["Team", TeamCreate, List[Dict[str, Any]], List[str], List[_ResolvedRef]]:
        from agno.team.team import Team

        if request.component_id is None:
            raise _StudioRequestError("component_id_required", "The effective team request has no component_id.")
        model, model_ref = self._resolve_model(request.model)
        context = self._resolve_context(request.context)
        resolved_refs = [
            self._resolve_component_ref(
                ref,
                link_kind="member",
                link_key=f"member_{position}",
                position=position,
            )
            for position, ref in enumerate(request.members)
        ]
        links = [cast(Dict[str, Any], resolved.link) for resolved in resolved_refs if resolved.link is not None]
        self._assert_no_cycle(request.component_id, links)
        warnings = [
            f"Draft references code-defined component '{resolved.ref.component_id}'; persist and pin it before publication."
            for resolved in resolved_refs
            if resolved.code_defined
        ]
        effective = request.model_copy(
            update={
                "component_id": request.component_id,
                "model": model_ref,
                "context": context,
                "members": [resolved.ref for resolved in resolved_refs],
            }
        )
        team = Team(
            id=request.component_id,
            name=request.name,
            instructions=request.instructions,
            description=request.description,
            model=model,
            members=[cast(TeamMember, resolved.component) for resolved in resolved_refs],
            db=self.db,
            metadata=metadata,
            add_history_to_context=context.include_history,
            num_history_runs=context.history_runs,
            add_datetime_to_context=context.include_datetime,
        )
        return team, effective, links, warnings, resolved_refs

    def _build_workflow(
        self,
        request: WorkflowCreate,
        metadata: Dict[str, Any],
    ) -> tuple["Workflow", WorkflowCreate, List[Dict[str, Any]], List[str], List[_ResolvedRef]]:
        from agno.workflow.step import Step
        from agno.workflow.workflow import Workflow

        if request.component_id is None:
            raise _StudioRequestError("component_id_required", "The effective workflow request has no component_id.")
        steps: List[Step] = []
        effective_steps: List[WorkflowStep] = []
        links: List[Dict[str, Any]] = []
        warnings: List[str] = []
        component_refs: List[_ResolvedRef] = []
        seen_step_ids: set[str] = set()

        for position, spec in enumerate(request.steps):
            step_id = spec.step_id or f"{_slugify(spec.name)}-{position + 1}"
            if step_id in seen_step_ids:
                raise _StudioRequestError("duplicate_step_id", f"Workflow step_id '{step_id}' is duplicated.")
            seen_step_ids.add(step_id)

            if isinstance(spec, AgentWorkflowStep):
                resolved = self._resolve_component_ref(
                    ComponentRef(component_type="agent", component_id=spec.component_id, version=spec.version),
                    link_kind="step_agent",
                    link_key=step_id,
                    position=position,
                )
                step = Step(
                    name=spec.name,
                    step_id=step_id,
                    agent=cast("Agent", resolved.component),
                    description=spec.description,
                )
                effective_spec: WorkflowStep = spec.model_copy(
                    update={"step_id": step_id, "version": resolved.ref.version}
                )
                component_refs.append(resolved)
            elif isinstance(spec, TeamWorkflowStep):
                resolved = self._resolve_component_ref(
                    ComponentRef(component_type="team", component_id=spec.component_id, version=spec.version),
                    link_kind="step_team",
                    link_key=step_id,
                    position=position,
                )
                step = Step(
                    name=spec.name,
                    step_id=step_id,
                    team=cast("Team", resolved.component),
                    description=spec.description,
                )
                effective_spec = spec.model_copy(update={"step_id": step_id, "version": resolved.ref.version})
                component_refs.append(resolved)
            elif isinstance(spec, FunctionWorkflowStep):
                matches = [
                    function
                    for function in self.registry.functions
                    if getattr(function, "__name__", None) == spec.function_name
                ]
                if not matches:
                    raise _StudioRequestError(
                        "function_not_found",
                        f"Workflow function '{spec.function_name}' is not registered.",
                    )
                if len(matches) > 1:
                    raise _StudioRequestError(
                        "ambiguous_function",
                        f"Multiple workflow functions are named '{spec.function_name}'.",
                    )
                step = Step(
                    name=spec.name,
                    step_id=step_id,
                    executor=matches[0],
                    description=spec.description,
                )
                effective_spec = spec.model_copy(update={"step_id": step_id})
            else:  # pragma: no cover - Pydantic's discriminator makes this unreachable
                raise _StudioRequestError("invalid_workflow_step", "Unsupported workflow step kind.")

            if (
                component_refs
                and component_refs[-1].link is not None
                and isinstance(spec, (AgentWorkflowStep, TeamWorkflowStep))
            ):
                links.append(cast(Dict[str, Any], component_refs[-1].link))
            if (
                component_refs
                and component_refs[-1].code_defined
                and isinstance(spec, (AgentWorkflowStep, TeamWorkflowStep))
            ):
                warnings.append(
                    f"Draft references code-defined component '{component_refs[-1].ref.component_id}'; persist and pin it before publication."
                )
            steps.append(step)
            effective_steps.append(effective_spec)

        self._assert_no_cycle(request.component_id, links)
        effective = request.model_copy(update={"component_id": request.component_id, "steps": effective_steps})
        workflow = Workflow(
            id=request.component_id,
            name=request.name,
            description=request.description,
            steps=cast(Any, steps),
            db=self.db,
            metadata=metadata,
        )
        return workflow, effective, links, warnings, component_refs

    @staticmethod
    def _normalized_request(request: Any) -> Dict[str, Any]:
        return request.model_dump(mode="json")

    def _latest_config(self, component_id: str) -> Optional[Dict[str, Any]]:
        configs = self.db.list_configs(component_id, include_config=True)
        return max(configs, key=lambda config: config.get("version", 0)) if configs else None

    def _existing_create_result(
        self,
        component_type: str,
        request: Any,
        save_as: SaveStage,
        if_exists: IfExists,
    ) -> Optional[StudioResult[Any]]:
        from agno.db.base import ComponentType

        code_component_types = [
            candidate_type
            for candidate_type, candidates in (
                ("agent", self._iter_agents()),
                ("team", self._iter_teams()),
                ("workflow", self._iter_workflows()),
            )
            if any(getattr(candidate, "id", None) == request.component_id for candidate in candidates)
        ]
        if code_component_types:
            raise _StudioRequestError(
                "component_conflict",
                f"Component id '{request.component_id}' is reserved by a code-defined component.",
                details={"code_component_types": code_component_types},
            )

        row = self.db.get_component(
            request.component_id,
            component_type=ComponentType(component_type),
            include_deleted=True,
        )
        if row is None:
            # An id occupied by another type must still conflict because the DB
            # component namespace is global.
            other = self.db.get_component(request.component_id, include_deleted=True)
            if other is None:
                return None
            raise _StudioRequestError(
                "component_conflict",
                f"Component id '{request.component_id}' is already used by a {other.get('component_type')}.",
            )
        if row.get("deleted_at") is not None:
            raise _StudioRequestError(
                "component_archived",
                f"Component id '{request.component_id}' is archived and remains reserved.",
            )
        if if_exists == "error":
            raise _StudioRequestError(
                "component_conflict",
                f"Component id '{request.component_id}' already exists.",
            )
        latest = self._latest_config(request.component_id)
        if latest is None or latest.get("stage") != save_as:
            raise _StudioRequestError(
                "component_conflict",
                "The existing component does not have the requested lifecycle stage.",
            )
        config = latest.get("config")
        if not isinstance(config, dict):
            raise _StudioRequestError("invalid_component_config", "The existing component config is invalid.")
        stored = self._manifest_request(config)
        if stored != self._normalized_request(request):
            raise _StudioRequestError(
                "component_conflict",
                "The existing component has a different effective configuration.",
            )
        if save_as == "published":
            if row.get("current_version") != latest.get("version"):
                raise _StudioRequestError(
                    "component_conflict",
                    "The identical published configuration exists but is not the current version.",
                )
            existing_request = self._request_from_config_row(component_type, latest)
            self._validate_publishability(
                component_type,
                cast(str, request.component_id),
                cast(int, latest["version"]),
                existing_request,
            )
        return self._success("existing", self._view_from_record(row, latest))

    def _create_component(
        self,
        component: Component,
        request: Any,
        save_as: SaveStage,
        links: Sequence[Dict[str, Any]],
        warnings: List[str],
        resolved_refs: Sequence[_ResolvedRef],
        if_exists: IfExists,
    ) -> StudioResult[Any]:
        from agno.db.base import ComponentAlreadyExistsError

        if save_as == "published":
            self._validate_immediate_publishability(
                self._component_type(component).value,
                request,
                resolved_refs,
            )
        existing = self._existing_create_result(
            self._component_type(component).value,
            request,
            save_as,
            if_exists,
        )
        if existing is not None:
            return existing

        config = self._serialize_component(component, request)
        try:
            row, config_row = self.db.create_component_with_config(
                component_id=request.component_id,
                component_type=self._component_type(component),
                name=request.name,
                description=request.description,
                metadata=getattr(component, "metadata", None),
                config=config,
                stage=save_as,
                links=list(links) or None,
            )
        except ComponentAlreadyExistsError:
            # The losing side of a concurrent retry re-runs the exact same
            # typed comparison; a different request remains a conflict.
            existing = self._existing_create_result(
                self._component_type(component).value,
                request,
                save_as,
                if_exists,
            )
            if existing is not None:
                return existing
            raise
        return self._success("created", self._view_from_record(row, config_row), warnings)

    # ------------------------------------------------------------------
    # Safe typed projections
    # ------------------------------------------------------------------

    def _view_from_record(self, component: Dict[str, Any], config_row: Dict[str, Any]) -> ComponentView:
        config = config_row.get("config")
        if not isinstance(config, dict):
            raise _StudioRequestError("invalid_component_config", "The stored component config is invalid.")
        request_data = self._manifest_request(config)
        component_type = component.get("component_type")
        version = config_row.get("version")
        stage = cast(Literal["draft", "published"], config_row.get("stage"))
        is_current = component.get("current_version") == version

        if component_type == "agent":
            agent_request = AgentCreate.model_validate(request_data)
            if agent_request.model is None or agent_request.context is None:
                raise _StudioRequestError("invalid_component_config", "The stored agent manifest is unresolved.")
            return AgentView(
                component_id=cast(str, agent_request.component_id),
                name=agent_request.name,
                instructions=agent_request.instructions,
                description=agent_request.description,
                model=agent_request.model,
                tools=agent_request.tools,
                context=agent_request.context,
                version=version,
                stage=stage,
                is_current=is_current,
                source="studio",
            )
        if component_type == "team":
            team_request = TeamCreate.model_validate(request_data)
            if team_request.model is None or team_request.context is None:
                raise _StudioRequestError("invalid_component_config", "The stored team manifest is unresolved.")
            return TeamView(
                component_id=cast(str, team_request.component_id),
                name=team_request.name,
                instructions=team_request.instructions,
                description=team_request.description,
                model=team_request.model,
                members=team_request.members,
                context=team_request.context,
                version=version,
                stage=stage,
                is_current=is_current,
                source="studio",
            )
        if component_type == "workflow":
            workflow_request = WorkflowCreate.model_validate(request_data)
            return WorkflowView(
                component_id=cast(str, workflow_request.component_id),
                name=workflow_request.name,
                description=workflow_request.description,
                steps=workflow_request.steps,
                version=version,
                stage=stage,
                is_current=is_current,
                source="studio",
            )
        raise _StudioRequestError("invalid_component_type", "The stored component type is invalid.")

    def _view_for_version(self, component_id: str, version: Optional[int]) -> ComponentView:
        component = self.db.get_component(component_id)
        if component is None:
            raise _StudioRequestError("component_not_found", f"Component '{component_id}' was not found.")
        self._ensure_component_type_enabled(cast(str, component.get("component_type")))
        config = self.db.get_config(component_id, version=version)
        if config is None:
            if version is None:
                raise _StudioRequestError(
                    "published_version_not_found",
                    f"Component '{component_id}' has no current published version.",
                )
            raise _StudioRequestError(
                "version_not_found",
                f"Version {version} was not found for component '{component_id}'.",
            )
        return self._view_from_record(component, config)

    def _summary_from_db_row(self, row: Dict[str, Any]) -> ComponentSummary:
        component_id = cast(str, row["component_id"])
        component_type = cast(Literal["agent", "team", "workflow"], row.get("component_type"))
        latest = self._latest_config(component_id)
        if latest is None:
            raise _StudioRequestError(
                "invalid_component_config",
                f"Component '{component_id}' has no stored configuration.",
            )
        latest_version = latest.get("version")
        latest_stage = latest.get("stage")
        if not isinstance(latest_version, int) or latest_stage not in ("draft", "published"):
            raise _StudioRequestError(
                "invalid_component_config",
                f"Component '{component_id}' has invalid latest-version metadata.",
            )
        latest_request = self._request_from_config_row(component_type, latest)
        return ComponentSummary(
            component_id=component_id,
            component_type=component_type,
            # Discovery follows the editable head. ``current_version`` is
            # reported separately, so a draft rename must not be hidden behind
            # the older published projection stored on the catalog row.
            name=latest_request.name,
            source="studio",
            latest_version=latest_version,
            latest_stage=cast(Literal["draft", "published"], latest_stage),
            current_version=cast(Optional[int], row.get("current_version")),
        )

    @staticmethod
    def _summary_from_code(component_type: str, component: Component) -> ComponentSummary:
        return ComponentSummary(
            component_id=getattr(component, "id", None),
            component_type=cast(Literal["agent", "team", "workflow"], component_type),
            name=getattr(component, "name", None) or getattr(component, "id", None) or "Unnamed component",
            source="code",
            latest_version=None,
            latest_stage="code",
            current_version=None,
        )

    @staticmethod
    def _tool_refs_from_component(tools: Any) -> List[ToolRef]:
        if not tools or callable(tools):
            return []
        refs: List[ToolRef] = []
        for tool in tools:
            if isinstance(tool, Toolkit):
                refs.append(ToolRef(kind="toolkit", name=tool.name))
            elif isinstance(tool, Function):
                toolkit = getattr(tool, "owning_toolkit", None)
                refs.append(ToolRef(kind="function", name=tool.name, toolkit=toolkit))
            elif callable(tool):
                name = getattr(tool, "__name__", None)
                if isinstance(name, str) and name:
                    refs.append(ToolRef(kind="function", name=name))
        return refs

    @staticmethod
    def _static_instructions(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return "\n".join(value)
        return "Instructions are resolved dynamically at runtime."

    def _code_agent_view(self, agent: "Agent") -> AgentView:
        model = self._model_ref(getattr(agent, "model", None))
        if model is None:
            raise _StudioRequestError("model_not_found", "The code-defined agent has no inspectable model.")
        return AgentView(
            component_id=cast(str, agent.id),
            name=agent.name or cast(str, agent.id),
            instructions=self._static_instructions(agent.instructions),
            description=agent.description,
            model=model,
            tools=self._tool_refs_from_component(agent.tools),
            context=ContextPolicy(
                include_history=bool(agent.add_history_to_context),
                history_runs=agent.num_history_runs if agent.add_history_to_context else None,
                include_datetime=bool(agent.add_datetime_to_context),
            ),
            version=None,
            stage="code",
            is_current=True,
            source="code",
        )

    def _code_team_view(self, team: "Team") -> TeamView:
        model = self._model_ref(getattr(team, "model", None))
        if model is None:
            raise _StudioRequestError("model_not_found", "The code-defined team has no inspectable model.")
        members = team.members if isinstance(team.members, list) else []
        refs: List[ComponentRef] = []
        from agno.agent.agent import Agent

        for member in members:
            member_id = getattr(member, "id", None)
            if not member_id:
                continue
            refs.append(
                ComponentRef(
                    component_type="agent" if isinstance(member, Agent) else "team",
                    component_id=member_id,
                )
            )
        return TeamView(
            component_id=cast(str, team.id),
            name=team.name or cast(str, team.id),
            instructions=self._static_instructions(team.instructions),
            description=team.description,
            model=model,
            members=refs,
            context=ContextPolicy(
                include_history=bool(team.add_history_to_context),
                history_runs=team.num_history_runs if team.add_history_to_context else None,
                include_datetime=bool(team.add_datetime_to_context),
            ),
            version=None,
            stage="code",
            is_current=True,
            source="code",
        )

    def _code_workflow_view(self, workflow: "Workflow") -> WorkflowView:
        steps: List[WorkflowStep] = []
        for position, step in enumerate(workflow.steps if isinstance(workflow.steps, list) else []):
            step_name = getattr(step, "name", None) or f"Step {position + 1}"
            step_id = getattr(step, "step_id", None)
            description = getattr(step, "description", None)
            agent = getattr(step, "agent", None)
            team = getattr(step, "team", None)
            executor = getattr(step, "executor", None)
            if agent is not None and getattr(agent, "id", None):
                steps.append(
                    AgentWorkflowStep(
                        kind="agent",
                        name=step_name,
                        step_id=step_id,
                        component_id=agent.id,
                        description=description,
                    )
                )
            elif team is not None and getattr(team, "id", None):
                steps.append(
                    TeamWorkflowStep(
                        kind="team",
                        name=step_name,
                        step_id=step_id,
                        component_id=team.id,
                        description=description,
                    )
                )
            elif executor is not None and (getattr(executor, "__name__", None) or getattr(executor, "name", None)):
                steps.append(
                    FunctionWorkflowStep(
                        kind="function",
                        name=step_name,
                        step_id=step_id,
                        function_name=getattr(executor, "__name__", None) or executor.name,
                        description=description,
                    )
                )
        return WorkflowView(
            component_id=cast(str, workflow.id),
            name=workflow.name or cast(str, workflow.id),
            description=workflow.description,
            steps=steps,
            version=None,
            stage="code",
            is_current=True,
            source="code",
        )

    @staticmethod
    def _storage_failure(error: Exception) -> Optional[StudioResult[Any]]:
        from agno.db.base import (
            ComponentAlreadyExistsError,
            ComponentCycleError,
            ComponentDependencyError,
            ComponentDraftRequiredError,
            ComponentLastConfigError,
            ComponentVersionConflictError,
        )

        if isinstance(error, ComponentAlreadyExistsError):
            return StudioTools._failure("component_conflict", str(error))
        if isinstance(error, ComponentCycleError):
            return StudioTools._failure(
                "component_cycle",
                str(error),
                details={"component_id": error.component_id, "cycle_path": error.cycle_path},
            )
        if isinstance(error, ComponentVersionConflictError):
            return StudioTools._failure(
                "version_conflict",
                str(error),
                details={"expected": error.expected, "actual": error.actual},
                retryable=True,
            )
        if isinstance(error, ComponentDependencyError):
            return StudioTools._failure(
                "component_has_dependents",
                str(error),
                details={"dependents": StudioTools._safe_dependents(error.dependents)},
            )
        if isinstance(error, ComponentDraftRequiredError):
            return StudioTools._failure(
                "draft_required",
                str(error),
                details={"component_id": error.component_id, "version": error.version},
            )
        if isinstance(error, ComponentLastConfigError):
            return StudioTools._failure(
                "last_config_required",
                str(error),
                details={"component_id": error.component_id, "version": error.version},
            )
        return None

    # ------------------------------------------------------------------
    # Typed discovery and reads
    # ------------------------------------------------------------------

    def list_models(self, _agno_run_context: Optional[RunContext] = None) -> StudioResult[List[ModelRef]]:
        """List exact model references available for Studio requests."""
        denied = self._authorize("list_models", "read", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[List[ModelRef]], denied)
        try:
            refs = [ref for model in self.registry.models if (ref := self._model_ref(model)) is not None]
            return StudioResult[List[ModelRef]](ok=True, status="listed", data=refs)
        except Exception:
            return cast(StudioResult[List[ModelRef]], self._internal_failure("list models"))

    def list_tools(self, _agno_run_context: Optional[RunContext] = None) -> StudioResult[List[ToolRef]]:
        """List copyable toolkit and function references available for agents."""
        denied = self._authorize("list_tools", "read", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[List[ToolRef]], denied)
        try:
            return StudioResult[List[ToolRef]](
                ok=True,
                status="listed",
                data=[ref for ref, _ in self._tool_catalog()],
            )
        except Exception:
            return cast(StudioResult[List[ToolRef]], self._internal_failure("list tools"))

    def list_functions(self, _agno_run_context: Optional[RunContext] = None) -> StudioResult[List[FunctionRef]]:
        """List exact registered functions available for workflow steps."""
        denied = self._authorize("list_functions", "read", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[List[FunctionRef]], denied)
        try:
            refs = [
                FunctionRef(
                    name=getattr(function, "__name__", "anonymous"),
                    description=inspect.getdoc(function),
                )
                for function in self.registry.functions
            ]
            return StudioResult[List[FunctionRef]](ok=True, status="listed", data=refs)
        except Exception:
            return cast(StudioResult[List[FunctionRef]], self._internal_failure("list functions"))

    def _list_components(
        self,
        component_type: Literal["agent", "team", "workflow"],
        code_components: Sequence[Component],
    ) -> List[ComponentSummary]:
        from agno.db.base import ComponentType

        code_ids = {
            cast(str, component_id)
            for component in code_components
            if (component_id := getattr(component, "id", None)) is not None
        }
        for component_id in code_ids:
            self._ensure_no_source_collision(component_id, component_type)
        result = [self._summary_from_code(component_type, component) for component in code_components]
        rows, _ = self.db.list_components(
            component_type=ComponentType(component_type),
            limit=self.list_limit,
        )
        result.extend(self._summary_from_db_row(row) for row in rows)
        return result

    def list_agents(self, _agno_run_context: Optional[RunContext] = None) -> StudioResult[List[ComponentSummary]]:
        """List code-defined and Studio-created agent summaries."""
        denied = self._authorize("list_agents", "read", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[List[ComponentSummary]], denied)
        try:
            self._ensure_component_type_enabled("agent")
            return StudioResult[List[ComponentSummary]](
                ok=True,
                status="listed",
                data=self._list_components("agent", self._iter_agents()),
            )
        except _StudioRequestError as error:
            return cast(StudioResult[List[ComponentSummary]], self._request_failure(error))
        except Exception:
            return cast(StudioResult[List[ComponentSummary]], self._internal_failure("list agents"))

    def list_teams(self, _agno_run_context: Optional[RunContext] = None) -> StudioResult[List[ComponentSummary]]:
        """List code-defined and Studio-created team summaries."""
        denied = self._authorize("list_teams", "read", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[List[ComponentSummary]], denied)
        try:
            self._ensure_component_type_enabled("team")
            return StudioResult[List[ComponentSummary]](
                ok=True,
                status="listed",
                data=self._list_components("team", self._iter_teams()),
            )
        except _StudioRequestError as error:
            return cast(StudioResult[List[ComponentSummary]], self._request_failure(error))
        except Exception:
            return cast(StudioResult[List[ComponentSummary]], self._internal_failure("list teams"))

    def list_workflows(self, _agno_run_context: Optional[RunContext] = None) -> StudioResult[List[ComponentSummary]]:
        """List code-defined and Studio-created workflow summaries."""
        denied = self._authorize("list_workflows", "read", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[List[ComponentSummary]], denied)
        try:
            self._ensure_component_type_enabled("workflow")
            return StudioResult[List[ComponentSummary]](
                ok=True,
                status="listed",
                data=self._list_components("workflow", self._iter_workflows()),
            )
        except _StudioRequestError as error:
            return cast(StudioResult[List[ComponentSummary]], self._request_failure(error))
        except Exception:
            return cast(StudioResult[List[ComponentSummary]], self._internal_failure("list workflows"))

    def get_agent(
        self,
        component_id: str,
        version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[AgentView]:
        """Get an agent by exact component id and optional config version.

        Args:
            component_id: Exact agent id returned by Studio discovery.
            version: Exact stored version, or omit to read the current
                published version (or the live code-defined agent).
        """
        denied = self._authorize("get_agent", "read", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[AgentView], denied)
        try:
            self._ensure_component_type_enabled("agent")
            self._ensure_no_source_collision(component_id, "agent")
            if self._db_component("agent", component_id) is not None:
                view = self._view_for_version(component_id, version)
                if not isinstance(view, AgentView):
                    raise _StudioRequestError("component_type_mismatch", "The component is not an agent.")
                return StudioResult[AgentView](ok=True, status="found", data=view)
            if version is not None:
                raise _StudioRequestError("component_not_found", f"Agent '{component_id}' was not found.")
            code = self._code_component("agent", component_id)
            if code is None:
                raise _StudioRequestError("component_not_found", f"Agent '{component_id}' was not found.")
            return StudioResult[AgentView](ok=True, status="found", data=self._code_agent_view(cast("Agent", code)))
        except _StudioRequestError as error:
            return cast(StudioResult[AgentView], self._request_failure(error))
        except Exception:
            return cast(StudioResult[AgentView], self._internal_failure("get agent"))

    def get_team(
        self,
        component_id: str,
        version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[TeamView]:
        """Get a team by exact component id and optional config version.

        Args:
            component_id: Exact team id returned by Studio discovery.
            version: Exact stored version, or omit to read the current
                published version (or the live code-defined team).
        """
        denied = self._authorize("get_team", "read", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[TeamView], denied)
        try:
            self._ensure_component_type_enabled("team")
            self._ensure_no_source_collision(component_id, "team")
            if self._db_component("team", component_id) is not None:
                view = self._view_for_version(component_id, version)
                if not isinstance(view, TeamView):
                    raise _StudioRequestError("component_type_mismatch", "The component is not a team.")
                return StudioResult[TeamView](ok=True, status="found", data=view)
            if version is not None:
                raise _StudioRequestError("component_not_found", f"Team '{component_id}' was not found.")
            code = self._code_component("team", component_id)
            if code is None:
                raise _StudioRequestError("component_not_found", f"Team '{component_id}' was not found.")
            return StudioResult[TeamView](ok=True, status="found", data=self._code_team_view(cast("Team", code)))
        except _StudioRequestError as error:
            return cast(StudioResult[TeamView], self._request_failure(error))
        except Exception:
            return cast(StudioResult[TeamView], self._internal_failure("get team"))

    def get_workflow(
        self,
        component_id: str,
        version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[WorkflowView]:
        """Get a workflow by exact component id and optional config version.

        Args:
            component_id: Exact workflow id returned by Studio discovery.
            version: Exact stored version, or omit to read the current
                published version (or the live code-defined workflow).
        """
        denied = self._authorize("get_workflow", "read", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[WorkflowView], denied)
        try:
            self._ensure_component_type_enabled("workflow")
            self._ensure_no_source_collision(component_id, "workflow")
            if self._db_component("workflow", component_id) is not None:
                view = self._view_for_version(component_id, version)
                if not isinstance(view, WorkflowView):
                    raise _StudioRequestError("component_type_mismatch", "The component is not a workflow.")
                return StudioResult[WorkflowView](ok=True, status="found", data=view)
            if version is not None:
                raise _StudioRequestError("component_not_found", f"Workflow '{component_id}' was not found.")
            code = self._code_component("workflow", component_id)
            if code is None:
                raise _StudioRequestError("component_not_found", f"Workflow '{component_id}' was not found.")
            return StudioResult[WorkflowView](
                ok=True,
                status="found",
                data=self._code_workflow_view(cast("Workflow", code)),
            )
        except _StudioRequestError as error:
            return cast(StudioResult[WorkflowView], self._request_failure(error))
        except Exception:
            return cast(StudioResult[WorkflowView], self._internal_failure("get workflow"))

    def list_versions(
        self,
        component_id: str,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[List[VersionSummary]]:
        """List safe lifecycle metadata for every config version.

        Args:
            component_id: Exact Studio component id.
        """
        denied = self._authorize("list_versions", "read", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[List[VersionSummary]], denied)
        try:
            self._ensure_no_source_collision(component_id)
            component = self.db.get_component(component_id)
            if component is None:
                raise _StudioRequestError("component_not_found", f"Component '{component_id}' was not found.")
            self._ensure_component_type_enabled(cast(str, component.get("component_type")))
            current = component.get("current_version")
            versions = [
                VersionSummary(
                    version=config["version"],
                    stage=config["stage"],
                    label=config.get("label"),
                    is_current=config.get("version") == current,
                    created_at=config.get("created_at"),
                    updated_at=config.get("updated_at"),
                )
                for config in self.db.list_configs(component_id, include_config=False)
            ]
            return StudioResult[List[VersionSummary]](ok=True, status="listed", data=versions)
        except _StudioRequestError as error:
            return cast(StudioResult[List[VersionSummary]], self._request_failure(error))
        except Exception:
            return cast(StudioResult[List[VersionSummary]], self._internal_failure("list versions"))

    def get_version(
        self,
        component_id: str,
        version: int,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ComponentView]:
        """Get a safe typed component view for one exact version.

        Persisted config blobs are never returned by this API.

        Args:
            component_id: Exact Studio component id.
            version: Exact stored version to inspect.
        """
        denied = self._authorize("get_version", "read", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[ComponentView], denied)
        try:
            self._ensure_no_source_collision(component_id)
            return StudioResult[ComponentView](
                ok=True,
                status="found",
                data=self._view_for_version(component_id, version),
            )
        except _StudioRequestError as error:
            return cast(StudioResult[ComponentView], self._request_failure(error))
        except Exception:
            return cast(StudioResult[ComponentView], self._internal_failure("get version"))

    # ------------------------------------------------------------------
    # Atomic, deterministic creates
    # ------------------------------------------------------------------

    @staticmethod
    def _effective_component_id(component_id: Optional[str], name: str) -> str:
        if component_id is not None:
            return StudioTools._validate_component_id(component_id)
        ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
        if not any(character.isalnum() for character in ascii_name):
            raise _StudioRequestError(
                "component_id_required",
                "component_id could not be derived from the name; supply it explicitly.",
            )
        resolved = _slugify(ascii_name)
        if not resolved:
            raise _StudioRequestError(
                "component_id_required",
                "component_id could not be derived from the name; supply it explicitly.",
            )
        return StudioTools._validate_component_id(resolved)

    def create_agent(
        self,
        request: AgentCreate,
        save_as: SaveStage = "draft",
        if_exists: IfExists = "error",
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[AgentView]:
        """Create an agent from one typed request.

        Args:
            request: Complete declarative agent configuration.
            save_as: Save as a draft by default or publish immediately.
            if_exists: Return an existing component only when its type,
                lifecycle stage, and normalized effective request are identical.
        """
        denied = self._authorize("create_agent", "mutate", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[AgentView], denied)
        try:
            assert _agno_run_context is not None
            self._ensure_component_type_enabled("agent")
            save_as = self._validate_save_as(save_as)
            if_exists = self._validate_if_exists(if_exists)
            effective_id = self._effective_component_id(request.component_id, request.name)
            request = request.model_copy(update={"component_id": effective_id})
            metadata = self._actor_metadata(None, _agno_run_context, "create_agent")
            agent, effective = self._build_agent(request, metadata)
            result = self._create_component(agent, effective, save_as, [], [], [], if_exists)
            log_debug(f"Studio created agent component_id={effective_id} stage={save_as}")
            return cast(StudioResult[AgentView], result)
        except _StudioRequestError as error:
            return cast(StudioResult[AgentView], self._request_failure(error))
        except Exception as error:
            known = self._storage_failure(error)
            if known is not None:
                return cast(StudioResult[AgentView], known)
            return cast(StudioResult[AgentView], self._internal_failure("create agent"))

    def create_team(
        self,
        request: TeamCreate,
        save_as: SaveStage = "draft",
        if_exists: IfExists = "error",
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[TeamView]:
        """Create a team from typed, version-aware member references.

        Args:
            request: Complete declarative team configuration.
            save_as: Save as a draft by default or publish immediately.
            if_exists: Return only an identical existing request and stage.
        """
        denied = self._authorize("create_team", "mutate", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[TeamView], denied)
        try:
            assert _agno_run_context is not None
            self._ensure_component_type_enabled("team")
            save_as = self._validate_save_as(save_as)
            if_exists = self._validate_if_exists(if_exists)
            effective_id = self._effective_component_id(request.component_id, request.name)
            request = request.model_copy(update={"component_id": effective_id})
            metadata = self._actor_metadata(None, _agno_run_context, "create_team")
            team, effective, links, warnings, resolved = self._build_team(request, metadata)
            result = self._create_component(team, effective, save_as, links, warnings, resolved, if_exists)
            log_debug(f"Studio created team component_id={effective_id} stage={save_as}")
            return cast(StudioResult[TeamView], result)
        except _StudioRequestError as error:
            return cast(StudioResult[TeamView], self._request_failure(error))
        except Exception as error:
            known = self._storage_failure(error)
            if known is not None:
                return cast(StudioResult[TeamView], known)
            return cast(StudioResult[TeamView], self._internal_failure("create team"))

    def create_workflow(
        self,
        request: WorkflowCreate,
        save_as: SaveStage = "draft",
        if_exists: IfExists = "error",
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[WorkflowView]:
        """Create a workflow from discriminated typed steps.

        Args:
            request: Complete declarative workflow configuration.
            save_as: Save as a draft by default or publish immediately.
            if_exists: Return only an identical existing request and stage.
        """
        denied = self._authorize("create_workflow", "mutate", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[WorkflowView], denied)
        try:
            assert _agno_run_context is not None
            self._ensure_component_type_enabled("workflow")
            save_as = self._validate_save_as(save_as)
            if_exists = self._validate_if_exists(if_exists)
            effective_id = self._effective_component_id(request.component_id, request.name)
            request = request.model_copy(update={"component_id": effective_id})
            metadata = self._actor_metadata(None, _agno_run_context, "create_workflow")
            workflow, effective, links, warnings, resolved = self._build_workflow(request, metadata)
            result = self._create_component(workflow, effective, save_as, links, warnings, resolved, if_exists)
            log_debug(f"Studio created workflow component_id={effective_id} stage={save_as}")
            return cast(StudioResult[WorkflowView], result)
        except _StudioRequestError as error:
            return cast(StudioResult[WorkflowView], self._request_failure(error))
        except Exception as error:
            known = self._storage_failure(error)
            if known is not None:
                return cast(StudioResult[WorkflowView], known)
            return cast(StudioResult[WorkflowView], self._internal_failure("create workflow"))

    # ------------------------------------------------------------------
    # Omission-aware CAS edits
    # ------------------------------------------------------------------

    def _edit_base(
        self,
        component_type: str,
        component_id: str,
        expected_version: int,
    ) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        from agno.db.base import ComponentType

        self._ensure_no_source_collision(component_id, component_type)
        component = self.db.get_component(component_id, component_type=ComponentType(component_type))
        if component is None:
            if self._code_component(component_type, component_id) is not None:
                raise _StudioRequestError(
                    "code_component_read_only",
                    "Code-defined components cannot be edited by Studio.",
                )
            raise _StudioRequestError(
                "component_not_found",
                f"{component_type.capitalize()} '{component_id}' was not found.",
            )
        config_row = self.db.get_config(component_id, version=expected_version)
        if config_row is None:
            raise _StudioRequestError(
                "version_not_found",
                f"Version {expected_version} was not found for component '{component_id}'.",
            )
        config = config_row.get("config")
        if not isinstance(config, dict):
            raise _StudioRequestError("invalid_component_config", "The stored component config is invalid.")
        return component, config_row, self._manifest_request(config)

    def _patched_context(self, current: Optional[ContextPolicy], patch: Any) -> Optional[ContextPolicy]:
        if patch is None:
            return current
        base = current or self.default_context
        values = base.model_dump()
        for field, value in patch.model_dump(exclude_unset=True).items():
            if field == "history_runs" and value is None:
                values[field] = self.default_context.history_runs
            else:
                values[field] = value
        if (
            values.get("include_history") is False
            and "history_runs" in patch.model_fields_set
            and patch.history_runs is not None
        ):
            raise _StudioRequestError(
                "invalid_context_policy",
                "history_runs cannot be set while history context is disabled; enable include_history in the same patch.",
            )
        if values.get("include_history") is False:
            values["history_runs"] = None
        elif values.get("history_runs") is None:
            values["history_runs"] = self.default_context.history_runs
        return ContextPolicy.model_validate(values)

    def _apply_agent_patch(self, current: AgentCreate, patch: AgentPatch) -> AgentCreate:
        updates = {field: getattr(patch, field) for field in patch.model_fields_set}
        if "context" in patch.model_fields_set:
            updates["context"] = self._patched_context(current.context, patch.context)
        return current.model_copy(update=updates)

    def _apply_team_patch(self, current: TeamCreate, patch: TeamPatch) -> TeamCreate:
        updates = {field: getattr(patch, field) for field in patch.model_fields_set}
        if "context" in patch.model_fields_set:
            updates["context"] = self._patched_context(current.context, patch.context)
        return current.model_copy(update=updates)

    @staticmethod
    def _apply_workflow_patch(current: WorkflowCreate, patch: WorkflowPatch) -> WorkflowCreate:
        return current.model_copy(update={field: getattr(patch, field) for field in patch.model_fields_set})

    def _append_edit(
        self,
        catalog_row: Dict[str, Any],
        component: Component,
        request: Any,
        expected_version: int,
        save_as: SaveStage,
        links: Sequence[Dict[str, Any]],
        warnings: List[str],
        resolved_refs: Sequence[_ResolvedRef],
    ) -> StudioResult[Any]:
        from agno.db.base import ComponentVersionGuard

        if save_as == "published":
            self._validate_immediate_publishability(
                self._component_type(component).value,
                request,
                resolved_refs,
            )
        component_id = cast(str, request.component_id)
        guard = ComponentVersionGuard(
            latest_version=expected_version,
            current_version=catalog_row.get("current_version"),
        )
        config = self._serialize_component(component, request)
        config_row = self.db.upsert_config(
            component_id=component_id,
            config=config,
            stage=save_as,
            links=list(links),
            guard=guard,
            projection=(
                self._projection(request, cast(Dict[str, Any], getattr(component, "metadata", None) or {}))
                if save_as == "published"
                else None
            ),
        )
        response_component = catalog_row
        if save_as == "published":
            response_component = self._projected_component_state(
                catalog_row,
                request,
                cast(Dict[str, Any], getattr(component, "metadata", None) or {}),
                current_version=cast(int, config_row["version"]),
            )
        return self._success("edited", self._view_from_record(response_component, config_row), warnings)

    def edit_agent(
        self,
        component_id: str,
        patch: AgentPatch,
        expected_version: int,
        save_as: SaveStage = "draft",
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[AgentView]:
        """Append an omission-aware agent version with optimistic concurrency.

        Args:
            component_id: Exact Studio agent id.
            patch: Typed changes to apply; omitted fields stay unchanged.
            expected_version: Latest version observed by the caller.
            save_as: Save the new version as a draft by default or publish it
                immediately.
        """
        denied = self._authorize("edit_agent", "mutate", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[AgentView], denied)
        try:
            assert _agno_run_context is not None
            self._ensure_component_type_enabled("agent")
            save_as = self._validate_save_as(save_as)
            row, _, request_data = self._edit_base("agent", component_id, expected_version)
            current = AgentCreate.model_validate(request_data)
            requested = self._apply_agent_patch(current, patch)
            metadata = self._actor_metadata(row.get("metadata"), _agno_run_context, "edit_agent")
            agent, effective = self._build_agent(requested, metadata)
            return cast(
                StudioResult[AgentView],
                self._append_edit(row, agent, effective, expected_version, save_as, [], [], []),
            )
        except _StudioRequestError as error:
            return cast(StudioResult[AgentView], self._request_failure(error))
        except Exception as error:
            known = self._storage_failure(error)
            if known is not None:
                return cast(StudioResult[AgentView], known)
            return cast(StudioResult[AgentView], self._internal_failure("edit agent"))

    def edit_team(
        self,
        component_id: str,
        patch: TeamPatch,
        expected_version: int,
        save_as: SaveStage = "draft",
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[TeamView]:
        """Append an omission-aware team version with optimistic concurrency.

        Args:
            component_id: Exact Studio team id.
            patch: Typed changes to apply; omitted fields stay unchanged.
            expected_version: Latest version observed by the caller.
            save_as: Save the new version as a draft by default or publish it
                immediately.
        """
        denied = self._authorize("edit_team", "mutate", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[TeamView], denied)
        try:
            assert _agno_run_context is not None
            self._ensure_component_type_enabled("team")
            save_as = self._validate_save_as(save_as)
            row, _, request_data = self._edit_base("team", component_id, expected_version)
            current = TeamCreate.model_validate(request_data)
            requested = self._apply_team_patch(current, patch)
            metadata = self._actor_metadata(row.get("metadata"), _agno_run_context, "edit_team")
            team, effective, links, warnings, resolved = self._build_team(requested, metadata)
            return cast(
                StudioResult[TeamView],
                self._append_edit(row, team, effective, expected_version, save_as, links, warnings, resolved),
            )
        except _StudioRequestError as error:
            return cast(StudioResult[TeamView], self._request_failure(error))
        except Exception as error:
            known = self._storage_failure(error)
            if known is not None:
                return cast(StudioResult[TeamView], known)
            return cast(StudioResult[TeamView], self._internal_failure("edit team"))

    def edit_workflow(
        self,
        component_id: str,
        patch: WorkflowPatch,
        expected_version: int,
        save_as: SaveStage = "draft",
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[WorkflowView]:
        """Append an omission-aware workflow version with optimistic concurrency.

        Args:
            component_id: Exact Studio workflow id.
            patch: Typed changes to apply; omitted fields stay unchanged.
            expected_version: Latest version observed by the caller.
            save_as: Save the new version as a draft by default or publish it
                immediately.
        """
        denied = self._authorize("edit_workflow", "mutate", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[WorkflowView], denied)
        try:
            assert _agno_run_context is not None
            self._ensure_component_type_enabled("workflow")
            save_as = self._validate_save_as(save_as)
            row, _, request_data = self._edit_base("workflow", component_id, expected_version)
            current = WorkflowCreate.model_validate(request_data)
            requested = self._apply_workflow_patch(current, patch)
            metadata = self._actor_metadata(row.get("metadata"), _agno_run_context, "edit_workflow")
            workflow, effective, links, warnings, resolved = self._build_workflow(requested, metadata)
            return cast(
                StudioResult[WorkflowView],
                self._append_edit(row, workflow, effective, expected_version, save_as, links, warnings, resolved),
            )
        except _StudioRequestError as error:
            return cast(StudioResult[WorkflowView], self._request_failure(error))
        except Exception as error:
            known = self._storage_failure(error)
            if known is not None:
                return cast(StudioResult[WorkflowView], known)
            return cast(StudioResult[WorkflowView], self._internal_failure("edit workflow"))

    # ------------------------------------------------------------------
    # Atomic publish, rollback, draft deletion, and archive
    # ------------------------------------------------------------------

    @staticmethod
    def _request_for_component_type(component_type: str, request_data: Dict[str, Any]) -> Any:
        if component_type == "agent":
            return AgentCreate.model_validate(request_data)
        if component_type == "team":
            return TeamCreate.model_validate(request_data)
        if component_type == "workflow":
            return WorkflowCreate.model_validate(request_data)
        raise _StudioRequestError("invalid_component_type", "The stored component type is invalid.")

    def _request_from_config_row(self, component_type: str, config_row: Dict[str, Any]) -> Any:
        config = config_row.get("config")
        if not isinstance(config, dict):
            raise _StudioRequestError("invalid_component_config", "The stored component config is invalid.")
        return self._request_for_component_type(component_type, self._manifest_request(config))

    def _require_published_pins(
        self,
        component_type: str,
        component_id: str,
        version: int,
        request: Any,
    ) -> None:
        expected: List[tuple[str, int, str, str]] = []
        if component_type == "team":
            for position, ref in enumerate(cast(TeamCreate, request).members):
                if ref.version is None:
                    raise _StudioRequestError(
                        "code_reference_not_publishable",
                        "Published teams require version-pinned stored members.",
                        details={"component_id": ref.component_id},
                    )
                expected.append((ref.component_id, ref.version, "member", f"member_{position}"))
        elif component_type == "workflow":
            for spec in cast(WorkflowCreate, request).steps:
                if isinstance(spec, AgentWorkflowStep):
                    if spec.version is None:
                        raise _StudioRequestError(
                            "code_reference_not_publishable",
                            "Published workflows require version-pinned stored step components.",
                            details={"component_id": spec.component_id},
                        )
                    expected.append((spec.component_id, spec.version, "step_agent", cast(str, spec.step_id)))
                elif isinstance(spec, TeamWorkflowStep):
                    if spec.version is None:
                        raise _StudioRequestError(
                            "code_reference_not_publishable",
                            "Published workflows require version-pinned stored step components.",
                            details={"component_id": spec.component_id},
                        )
                    expected.append((spec.component_id, spec.version, "step_team", cast(str, spec.step_id)))

        actual = {
            (
                link.get("child_component_id"),
                link.get("child_version"),
                link.get("link_kind"),
                link.get("link_key"),
            )
            for link in self.db.get_links(component_id, version)
        }
        missing_links: List[Dict[str, Any]] = []
        for child_id, child_version, link_kind, link_key in expected:
            if (child_id, child_version, link_kind, link_key) not in actual:
                missing_links.append(
                    {
                        "component_id": child_id,
                        "version": child_version,
                        "link_kind": link_kind,
                        "link_key": link_key,
                    }
                )
                continue
            child = self.db.get_component(child_id)
            child_config = self.db.get_config(child_id, version=child_version) if child is not None else None
            if child is None or child_config is None or child_config.get("stage") != "published":
                raise _StudioRequestError(
                    "unpublished_dependency",
                    f"Dependency '{child_id}' v{child_version} is not an active published component.",
                )
        if missing_links:
            raise _StudioRequestError(
                "missing_component_links",
                "The draft is missing durable links for one or more component references.",
                details={"missing": missing_links},
            )

    def _validate_published_ref_tree(
        self,
        resolved_refs: Sequence[_ResolvedRef],
        seen: set[tuple[str, str, int]],
    ) -> None:
        """Revalidate every durable child before a parent can become current."""
        self._ensure_publishable_refs(resolved_refs)
        for resolved in resolved_refs:
            ref = resolved.ref
            if resolved.code_defined or ref.version is None:
                raise _StudioRequestError(
                    "code_reference_not_publishable",
                    "Published composites require stored, version-pinned child components.",
                    details={"component_id": ref.component_id},
                )
            child = self._db_component(ref.component_type, ref.component_id)
            child_config = self.db.get_config(ref.component_id, version=ref.version) if child is not None else None
            if child is None or child_config is None or child_config.get("stage") != "published":
                raise _StudioRequestError(
                    "unpublished_dependency",
                    f"Dependency '{ref.component_id}' v{ref.version} is not an active published component.",
                )
            child_request = self._request_from_config_row(ref.component_type, child_config)
            self._validate_publishability(
                ref.component_type,
                ref.component_id,
                ref.version,
                child_request,
                seen,
            )

    def _validate_immediate_publishability(
        self,
        component_type: str,
        request: Any,
        resolved_refs: Sequence[_ResolvedRef],
    ) -> None:
        """Preflight a freshly built runtime before atomically storing it live.

        The top-level runtime was just built from exact registry objects. Its
        durable children, however, may have become non-dispatchable since they
        were published, so validate their complete pinned trees as strictly as
        the explicit publish and rollback paths do.
        """
        if request.component_id is None:
            raise _StudioRequestError("component_id_required", "Published components require a component_id.")
        if component_type not in ("agent", "team", "workflow"):
            raise _StudioRequestError("invalid_component_type", "The component type is invalid.")
        self._validate_published_ref_tree(resolved_refs, set())

    @staticmethod
    def _normalize_runtime_fidelity_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """Ignore deterministic strict-schema decoration in fidelity checks.

        Rehydration processes Function entrypoints and adds
        ``additionalProperties: false`` recursively. A freshly registered
        Toolkit may not have been processed yet, so that generated decoration
        can differ even though both runtimes hold the same exact registry
        functions. Typed ToolRefs make the registry identity authoritative;
        normalize only this generated false marker while retaining every tool,
        parameter, description, and runtime field.
        """

        def strip_generated_strictness(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    strip_generated_strictness(item)
                return
            if not isinstance(value, dict):
                return
            if value.get("additionalProperties") is False:
                value.pop("additionalProperties")
            for item in value.values():
                strip_generated_strictness(item)

        tools = config.get("tools")
        if isinstance(tools, list):
            for tool in tools:
                if isinstance(tool, dict):
                    strip_generated_strictness(tool.get("parameters"))
        return config

    def _validate_publishability(
        self,
        component_type: str,
        component_id: str,
        version: int,
        request: Any,
        seen: Optional[set[tuple[str, str, int]]] = None,
    ) -> None:
        if seen is None:
            seen = set()
        identity = (component_type, component_id, version)
        if identity in seen:
            return
        seen.add(identity)
        if request.component_id != component_id:
            raise _StudioRequestError(
                "invalid_component_config",
                "The stored request component_id does not match its catalog id.",
            )

        metadata: Dict[str, Any] = {}
        resolved_refs: Sequence[_ResolvedRef] = []
        built: Component
        effective: Union[AgentCreate, TeamCreate, WorkflowCreate]
        if component_type == "agent":
            built, effective = self._build_agent(cast(AgentCreate, request), metadata)
        elif component_type == "team":
            built, effective, _, _, resolved_refs = self._build_team(cast(TeamCreate, request), metadata)
        elif component_type == "workflow":
            built, effective, _, _, resolved_refs = self._build_workflow(cast(WorkflowCreate, request), metadata)
        else:
            raise _StudioRequestError("invalid_component_type", "The stored component type is invalid.")

        if self._normalized_request(effective) != self._normalized_request(request):
            raise _StudioRequestError(
                "component_not_publishable",
                "The stored request contains unresolved defaults or references; edit and save a fresh draft first.",
            )
        self._ensure_publishable_refs(resolved_refs)
        self._validate_published_ref_tree(resolved_refs, seen)
        self._require_published_pins(component_type, component_id, version, request)

        try:
            rebuilt = self._load_db_component(
                component_type,
                component_id,
                version,
                for_dispatch=True,
            )
        except Exception as error:
            raise _StudioRequestError(
                "component_not_publishable",
                "The component cannot be faithfully rehydrated for dispatch; repair its registry dependencies first.",
                details={
                    "component_id": component_id,
                    "component_type": component_type,
                    "version": version,
                    "reason": type(error).__name__,
                },
            ) from error
        if rebuilt is None:
            raise _StudioRequestError(
                "component_not_publishable",
                "The component cannot be faithfully rehydrated for dispatch.",
                details={
                    "component_id": component_id,
                    "component_type": component_type,
                    "version": version,
                },
            )

        expected_config = self._normalize_runtime_fidelity_config(self._serialize_component(built, request))
        rebuilt_config = self._normalize_runtime_fidelity_config(self._serialize_component(rebuilt, request))
        # Actor metadata is a component projection and can legitimately be
        # newer than an immutable config version. Everything else must match
        # the typed request's fresh rebuild before that version can go live.
        expected_config.pop("metadata", None)
        rebuilt_config.pop("metadata", None)
        if expected_config != rebuilt_config:
            raise _StudioRequestError(
                "component_not_publishable",
                "The persisted runtime config diverges from its typed Studio request; save a fresh draft first.",
                details={
                    "component_id": component_id,
                    "component_type": component_type,
                    "version": version,
                },
            )

    def publish_component(
        self,
        component_id: str,
        version: int,
        expected_current_version: int | None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ComponentView]:
        """Publish the latest draft using a current-version CAS guard.

        Args:
            component_id: Exact Studio component id.
            version: Latest draft version to publish.
            expected_current_version: Current published version observed by
                the caller, or null when the component has never been
                published.
        """
        denied = self._authorize("publish_component", "mutate", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[ComponentView], denied)
        try:
            assert _agno_run_context is not None
            from agno.db.base import ComponentVersionGuard

            self._ensure_no_source_collision(component_id)
            component = self.db.get_component(component_id)
            if component is None:
                raise _StudioRequestError("component_not_found", f"Component '{component_id}' was not found.")
            self._ensure_component_type_enabled(cast(str, component.get("component_type")))
            config_row = self.db.get_config(component_id, version=version)
            if config_row is None:
                raise _StudioRequestError("version_not_found", f"Version {version} was not found.")
            component_type = cast(str, component["component_type"])
            request = self._request_from_config_row(component_type, config_row)
            if config_row.get("stage") == "published" and component.get("current_version") == version:
                self._validate_publishability(component_type, component_id, version, request)
                return StudioResult[ComponentView](
                    ok=True,
                    status="already_published",
                    data=self._view_from_record(component, config_row),
                )
            if config_row.get("stage") != "draft":
                raise _StudioRequestError(
                    "draft_required",
                    "Only a draft can be published; use set_current_version for an older published version.",
                )
            self._validate_publishability(component_type, component_id, version, request)
            metadata = self._actor_metadata(component.get("metadata"), _agno_run_context, "publish_component")
            result = self.db.upsert_config(
                component_id=component_id,
                version=version,
                stage="published",
                guard=ComponentVersionGuard(
                    latest_version=version,
                    current_version=expected_current_version,
                ),
                projection=self._projection(request, metadata),
            )
            response_component = self._projected_component_state(
                component,
                request,
                metadata,
                current_version=version,
            )
            return StudioResult[ComponentView](
                ok=True,
                status="published",
                data=self._view_from_record(response_component, result),
            )
        except _StudioRequestError as error:
            return cast(StudioResult[ComponentView], self._request_failure(error))
        except Exception as error:
            known = self._storage_failure(error)
            if known is not None:
                return cast(StudioResult[ComponentView], known)
            return cast(StudioResult[ComponentView], self._internal_failure("publish component"))

    def set_current_version(
        self,
        component_id: str,
        version: int,
        expected_current_version: int | None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ComponentView]:
        """Make an immutable published version current using CAS.

        Args:
            component_id: Exact Studio component id.
            version: Published version to make current.
            expected_current_version: Current published version observed by
                the caller, or null when no version is currently published.
        """
        denied = self._authorize("set_current_version", "mutate", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[ComponentView], denied)
        try:
            assert _agno_run_context is not None
            from agno.db.base import ComponentVersionGuard

            self._ensure_no_source_collision(component_id)
            component = self.db.get_component(component_id)
            if component is None:
                raise _StudioRequestError("component_not_found", f"Component '{component_id}' was not found.")
            self._ensure_component_type_enabled(cast(str, component.get("component_type")))
            config_row = self.db.get_config(component_id, version=version)
            if config_row is None:
                raise _StudioRequestError("version_not_found", f"Version {version} was not found.")
            if config_row.get("stage") != "published":
                raise _StudioRequestError("published_version_required", "Only a published version can be current.")
            component_type = cast(str, component["component_type"])
            request = self._request_from_config_row(component_type, config_row)
            self._validate_publishability(component_type, component_id, version, request)
            if component.get("current_version") == version:
                return StudioResult[ComponentView](
                    ok=True,
                    status="already_current",
                    data=self._view_from_record(component, config_row),
                )
            metadata = self._actor_metadata(component.get("metadata"), _agno_run_context, "set_current_version")
            configs = self.db.list_configs(component_id, include_config=False)
            latest = max((config["version"] for config in configs), default=None)
            ok = self.db.set_current_version(
                component_id,
                version,
                guard=ComponentVersionGuard(
                    latest_version=latest,
                    current_version=expected_current_version,
                ),
                projection=self._projection(request, metadata),
            )
            if not ok:
                raise _StudioRequestError("version_not_found", f"Version {version} was not found.")
            response_component = self._projected_component_state(
                component,
                request,
                metadata,
                current_version=version,
            )
            return StudioResult[ComponentView](
                ok=True,
                status="current_version_set",
                data=self._view_from_record(response_component, config_row),
            )
        except _StudioRequestError as error:
            return cast(StudioResult[ComponentView], self._request_failure(error))
        except Exception as error:
            known = self._storage_failure(error)
            if known is not None:
                return cast(StudioResult[ComponentView], known)
            return cast(StudioResult[ComponentView], self._internal_failure("set current version"))

    def delete_version(
        self,
        component_id: str,
        version: int,
        expected_latest_version: int,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ComponentActionView]:
        """Delete one unreferenced draft version using a latest-version guard.

        Args:
            component_id: Exact Studio component id.
            version: Draft version to delete.
            expected_latest_version: Latest version observed by the caller.
        """
        denied = self._authorize("delete_version", "mutate", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[ComponentActionView], denied)
        try:
            assert _agno_run_context is not None
            from agno.db.base import ComponentVersionGuard

            self._ensure_no_source_collision(component_id)
            component = self.db.get_component(component_id)
            if component is None:
                raise _StudioRequestError("component_not_found", f"Component '{component_id}' was not found.")
            self._ensure_component_type_enabled(cast(str, component.get("component_type")))
            metadata = self._actor_metadata(component.get("metadata"), _agno_run_context, "delete_version")
            deleted = self.db.delete_config(
                component_id,
                version,
                guard=ComponentVersionGuard(
                    latest_version=expected_latest_version,
                    current_version=component.get("current_version"),
                ),
                projection=cast("ComponentProjection", {"metadata": metadata}),
            )
            if not deleted:
                raise _StudioRequestError("version_not_found", f"Version {version} was not found.")
            return StudioResult[ComponentActionView](
                ok=True,
                status="draft_deleted",
                data=ComponentActionView(
                    component_id=component_id,
                    component_type=component["component_type"],
                    version=version,
                ),
            )
        except _StudioRequestError as error:
            return cast(StudioResult[ComponentActionView], self._request_failure(error))
        except Exception as error:
            known = self._storage_failure(error)
            if known is not None:
                return cast(StudioResult[ComponentActionView], known)
            return cast(StudioResult[ComponentActionView], self._internal_failure("delete draft version"))

    def _archive_component(
        self,
        component_type: Literal["agent", "team", "workflow"],
        component_id: str,
        expected_current_version: int | None,
        run_context: RunContext,
        action: StudioAction,
    ) -> StudioResult[ComponentActionView]:
        from agno.db.base import ComponentType, ComponentVersionGuard

        self._ensure_component_type_enabled(component_type)
        self._ensure_no_source_collision(component_id, component_type)
        component = self.db.get_component(
            component_id,
            component_type=ComponentType(component_type),
            include_deleted=True,
        )
        if component is None:
            raise _StudioRequestError(
                "component_not_found",
                f"{component_type.capitalize()} '{component_id}' was not found.",
            )
        if component.get("deleted_at") is not None:
            return StudioResult[ComponentActionView](
                ok=True,
                status="already_archived",
                data=ComponentActionView(
                    component_id=component_id,
                    component_type=component_type,
                    version=component.get("current_version"),
                ),
                warnings=self._schedule_cleanup_warnings(component_type, component_id),
            )
        configs = self.db.list_configs(component_id, include_config=False)
        latest = max((config["version"] for config in configs), default=None)
        metadata = self._actor_metadata(component.get("metadata"), run_context, action)
        archive_projection = cast(
            "ComponentProjection",
            {
                "name": component.get("name"),
                "description": component.get("description"),
                "metadata": metadata,
            },
        )
        archived = self.db.delete_component(
            component_id,
            hard_delete=False,
            guard=ComponentVersionGuard(
                latest_version=latest,
                current_version=expected_current_version,
            ),
            require_no_dependents=True,
            projection=archive_projection,
        )
        if not archived:
            raise _StudioRequestError("component_not_found", f"Component '{component_id}' was not found.")
        return StudioResult[ComponentActionView](
            ok=True,
            status="archived",
            data=ComponentActionView(
                component_id=component_id,
                component_type=component_type,
                version=component.get("current_version"),
            ),
            warnings=self._schedule_cleanup_warnings(component_type, component_id),
        )

    def archive_agent(
        self,
        component_id: str,
        expected_current_version: int | None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ComponentActionView]:
        """Archive an agent if no active component depends on it.

        Args:
            component_id: Exact Studio agent id.
            expected_current_version: Current published version observed by
                the caller, or null when the agent is draft-only.
        """
        denied = self._authorize("archive_agent", "mutate", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[ComponentActionView], denied)
        try:
            assert _agno_run_context is not None
            return self._archive_component(
                "agent", component_id, expected_current_version, _agno_run_context, "archive_agent"
            )
        except _StudioRequestError as error:
            return cast(StudioResult[ComponentActionView], self._request_failure(error))
        except Exception as error:
            known = self._storage_failure(error)
            if known is not None:
                return cast(StudioResult[ComponentActionView], known)
            return cast(StudioResult[ComponentActionView], self._internal_failure("archive agent"))

    def archive_team(
        self,
        component_id: str,
        expected_current_version: int | None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ComponentActionView]:
        """Archive a team if no active component depends on it.

        Args:
            component_id: Exact Studio team id.
            expected_current_version: Current published version observed by
                the caller, or null when the team is draft-only.
        """
        denied = self._authorize("archive_team", "mutate", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[ComponentActionView], denied)
        try:
            assert _agno_run_context is not None
            return self._archive_component(
                "team", component_id, expected_current_version, _agno_run_context, "archive_team"
            )
        except _StudioRequestError as error:
            return cast(StudioResult[ComponentActionView], self._request_failure(error))
        except Exception as error:
            known = self._storage_failure(error)
            if known is not None:
                return cast(StudioResult[ComponentActionView], known)
            return cast(StudioResult[ComponentActionView], self._internal_failure("archive team"))

    def archive_workflow(
        self,
        component_id: str,
        expected_current_version: int | None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ComponentActionView]:
        """Archive a workflow if no active component depends on it.

        Args:
            component_id: Exact Studio workflow id.
            expected_current_version: Current published version observed by
                the caller, or null when the workflow is draft-only.
        """
        denied = self._authorize("archive_workflow", "mutate", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[ComponentActionView], denied)
        try:
            assert _agno_run_context is not None
            return self._archive_component(
                "workflow", component_id, expected_current_version, _agno_run_context, "archive_workflow"
            )
        except _StudioRequestError as error:
            return cast(StudioResult[ComponentActionView], self._request_failure(error))
        except Exception as error:
            known = self._storage_failure(error)
            if known is not None:
                return cast(StudioResult[ComponentActionView], known)
            return cast(StudioResult[ComponentActionView], self._internal_failure("archive workflow"))

    # ------------------------------------------------------------------
    # Authorization-wrapped data-plane dispatch
    # ------------------------------------------------------------------

    def run_agent(
        self,
        agent_id: str,
        message: str,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Run an agent through StudioRunnerTools as the authenticated actor.

        Args:
            agent_id: Exact agent id whose current published version should run.
            message: Input message sent to the agent.
        """
        denied = self._authorize("run_agent", "mutate", _agno_run_context)
        if denied is not None:
            return str(denied)
        try:
            self._ensure_component_type_enabled("agent")
            self._ensure_no_source_collision(agent_id, "agent")
            return self._runner_tools.run_agent(agent_id, message, _agno_run_context)
        except _StudioRequestError as error:
            return str(self._request_failure(error))
        except Exception:
            return str(self._internal_failure("run agent"))

    def run_team(
        self,
        team_id: str,
        message: str,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Run a team through StudioRunnerTools as the authenticated actor.

        Args:
            team_id: Exact team id whose current published version should run.
            message: Input message sent to the team.
        """
        denied = self._authorize("run_team", "mutate", _agno_run_context)
        if denied is not None:
            return str(denied)
        try:
            self._ensure_component_type_enabled("team")
            self._ensure_no_source_collision(team_id, "team")
            return self._runner_tools.run_team(team_id, message, _agno_run_context)
        except _StudioRequestError as error:
            return str(self._request_failure(error))
        except Exception:
            return str(self._internal_failure("run team"))

    def run_workflow(
        self,
        workflow_id: str,
        message: str,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        """Run a workflow through StudioRunnerTools as the authenticated actor.

        Args:
            workflow_id: Exact workflow id whose current published version should run.
            message: Input message sent to the workflow.
        """
        denied = self._authorize("run_workflow", "mutate", _agno_run_context)
        if denied is not None:
            return str(denied)
        try:
            self._ensure_component_type_enabled("workflow")
            self._ensure_no_source_collision(workflow_id, "workflow")
            return self._runner_tools.run_workflow(workflow_id, message, _agno_run_context)
        except _StudioRequestError as error:
            return str(self._request_failure(error))
        except Exception:
            return str(self._internal_failure("run workflow"))

    # ------------------------------------------------------------------
    # Authorization-wrapped schedules
    # ------------------------------------------------------------------

    def _schedule_manager(self) -> "ScheduleManager":
        if self._scheduler_tools is None:
            raise _StudioRequestError("schedules_disabled", "StudioTools was created with schedules=False.")
        return self._scheduler_tools.manager

    def _catalog_schedule_manager(self) -> "ScheduleManager":
        """Return a manager for lifecycle cleanup even when schedule tools are hidden."""
        if self._scheduler_tools is not None:
            return self._scheduler_tools.manager
        from agno.scheduler.manager import ScheduleManager

        return ScheduleManager(db=self.db)

    @staticmethod
    def _scan_schedules(
        manager: "ScheduleManager",
        *,
        enabled: Optional[bool] = None,
    ) -> List["Schedule"]:
        """Read every schedule page without looping forever on a broken adapter."""
        page_size = 100
        page = 1
        seen_ids: set[str] = set()
        schedules: List["Schedule"] = []
        while True:
            batch = manager.list(enabled=enabled, limit=page_size, page=page)
            fresh = [schedule for schedule in batch if schedule.id not in seen_ids]
            if not fresh:
                break
            schedules.extend(fresh)
            seen_ids.update(schedule.id for schedule in fresh)
            if len(batch) < page_size:
                break
            page += 1
        return schedules

    @staticmethod
    def _studio_schedule_metadata(schedule: "Schedule") -> Optional[Dict[str, Any]]:
        """Return server-owned Studio provenance only when the record is coherent."""
        if schedule.managed_by != STUDIO_SCHEDULE_MANAGED_BY:
            return None
        owner_actor_id = schedule.owner_actor_id
        target_type = schedule.target_type
        target_id = schedule.target_id
        if not is_valid_studio_schedule_actor_id(owner_actor_id):
            return None
        assert isinstance(owner_actor_id, str)
        if target_type not in _SCHEDULE_TARGET_TYPES:
            return None
        try:
            target_id = StudioTools._validate_component_id(target_id)
        except _StudioRequestError:
            return None
        if schedule.method.upper() != "POST" or schedule.endpoint != f"/{target_type}s/{target_id}/runs":
            return None
        return {
            "owner_actor_id": owner_actor_id,
            "target_type": target_type,
            "target_id": target_id,
            "created_by_run_id": schedule.created_by_run_id,
            "created_by_session_id": schedule.created_by_session_id,
            "updated_by_run_id": schedule.updated_by_run_id,
            "updated_by_session_id": schedule.updated_by_session_id,
        }

    @staticmethod
    def _schedule_payload(request: ScheduleCreate) -> Dict[str, Any]:
        """Build the private dispatch payload without ownership metadata."""
        return {"message": request.message}

    def _create_studio_schedule_record(
        self,
        request: ScheduleCreate,
        target_id: str,
        run_context: RunContext,
    ) -> "Schedule":
        """Atomically insert a schedule carrying server-owned Studio provenance."""
        import time
        from uuid import uuid4

        from agno.scheduler.cron import compute_next_run

        assert run_context.user_id is not None
        schedule = Schedule(
            id=str(uuid4()),
            name=request.name,
            cron_expr=request.cron,
            endpoint=f"/{request.target_type}s/{target_id}/runs",
            method="POST",
            description=request.description,
            payload=self._schedule_payload(request),
            timezone=request.timezone,
            managed_by=STUDIO_SCHEDULE_MANAGED_BY,
            owner_actor_id=run_context.user_id,
            target_type=request.target_type,
            target_id=target_id,
            created_by_run_id=run_context.run_id,
            created_by_session_id=run_context.session_id,
            updated_by_run_id=run_context.run_id,
            updated_by_session_id=run_context.session_id,
            enabled=True,
            next_run_at=compute_next_run(request.cron, request.timezone),
            created_at=int(time.time()),
        )
        stored = self.db.create_schedule(schedule.to_dict())
        return Schedule.from_dict(stored)

    @staticmethod
    def _schedule_view(schedule: "Schedule", metadata: Dict[str, Any]) -> ScheduleView:
        return ScheduleView(
            schedule_id=schedule.id,
            name=schedule.name,
            description=schedule.description,
            cron=schedule.cron_expr,
            target_type=cast(Literal["agent", "team", "workflow"], metadata["target_type"]),
            target_id=metadata["target_id"],
            timezone=schedule.timezone,
            enabled=schedule.enabled,
            next_run_at=schedule.next_run_at,
            owner_actor_id=metadata["owner_actor_id"],
            created_at=schedule.created_at,
            updated_at=schedule.updated_at,
        )

    @staticmethod
    def _schedule_action_view(schedule: "Schedule", metadata: Dict[str, Any]) -> ScheduleActionView:
        return ScheduleActionView(
            schedule_id=schedule.id,
            name=schedule.name,
            target_type=cast(Literal["agent", "team", "workflow"], metadata["target_type"]),
            target_id=metadata["target_id"],
            enabled=schedule.enabled,
        )

    @staticmethod
    def _schedule_run_view(run: "ScheduleRun") -> ScheduleRunView:
        return ScheduleRunView(
            schedule_run_id=run.id,
            schedule_id=run.schedule_id,
            attempt=run.attempt,
            status=run.status,
            triggered_at=run.triggered_at,
            completed_at=run.completed_at,
            status_code=run.status_code,
            component_run_id=run.run_id,
            session_id=run.session_id,
            has_error=run.error is not None,
            has_requirements=bool(run.requirements),
            created_at=run.created_at,
        )

    def _owned_schedule(self, schedule_id: str, run_context: RunContext) -> tuple["Schedule", Dict[str, Any]]:
        schedule = self._schedule_manager().get(schedule_id)
        if schedule is None:
            raise _StudioRequestError("schedule_not_found", f"Schedule '{schedule_id}' was not found.")
        metadata = self._studio_schedule_metadata(schedule)
        if metadata is None or metadata["owner_actor_id"] != run_context.user_id:
            # Do not disclose whether the id belongs to another actor or to a
            # non-Studio scheduler record in the shared table.
            raise _StudioRequestError("schedule_not_found", f"Schedule '{schedule_id}' was not found.")
        return schedule, metadata

    @staticmethod
    def _validate_schedule_cadence(request: ScheduleCreate) -> None:
        from agno.scheduler.cron import validate_cron_expr, validate_timezone

        if not validate_cron_expr(request.cron):
            raise _StudioRequestError("invalid_cron", "Schedule cron must be a valid five-field expression.")
        if not validate_timezone(request.timezone):
            raise _StudioRequestError("invalid_timezone", "Schedule timezone must be a valid IANA timezone.")

    def _disable_studio_schedules_for_target(self, component_type: str, component_id: str) -> int:
        """Disable every coherently Studio-owned schedule for an archived target.

        This deliberately scans all actors because archiving a shared component
        invalidates every schedule that can dispatch it. The ownership payload
        and derived endpoint must both match, so unrelated scheduler records are
        never modified.
        """
        manager = self._catalog_schedule_manager()
        disabled = 0
        for schedule in self._scan_schedules(manager, enabled=True):
            metadata = self._studio_schedule_metadata(schedule)
            if (
                metadata is not None
                and metadata["target_type"] == component_type
                and metadata["target_id"] == component_id
            ):
                if manager.disable(schedule.id) is None:
                    raise RuntimeError(f"Failed to disable Studio schedule '{schedule.id}'")
                disabled += 1
        return disabled

    def _schedule_cleanup_warnings(self, component_type: str, component_id: str) -> List[str]:
        """Disable archived-target schedules and project any backend failure safely."""
        try:
            self._disable_studio_schedules_for_target(component_type, component_id)
        except Exception:
            # Archival is already committed (or was committed by an earlier
            # attempt). Report it truthfully rather than returning a failure
            # for a mutation that happened. A retry gets another cleanup pass.
            logger.error(
                "Studio archived %s '%s' but could not disable all of its schedules",
                component_type,
                component_id,
            )
            return [
                "The component was archived, but one or more schedules could not be disabled; inspect the scheduler."
            ]
        return []

    def _resolve_schedule_target(self, target_type: str, target_id: str) -> str:
        if target_type not in _SCHEDULE_TARGET_TYPES:
            raise _StudioRequestError(
                "invalid_target_type",
                f"target_type must be one of {list(_SCHEDULE_TARGET_TYPES)}.",
            )
        self._ensure_component_type_enabled(target_type)
        self._ensure_no_source_collision(target_id, target_type)
        code = self._code_component(target_type, target_id)
        if code is not None:
            return target_id
        row = self._db_component(target_type, target_id)
        if row is None or row.get("current_version") is None:
            raise _StudioRequestError(
                "published_target_not_found",
                f"Published {target_type} '{target_id}' was not found.",
            )
        return target_id

    def _revalidate_schedule_target_after_write(
        self,
        schedule: "Schedule",
        target_type: str,
        target_id: str,
        *,
        delete_on_failure: bool = False,
    ) -> "Schedule":
        """Close the monotonic archive race around schedule writes.

        Archive commits and then disables every schedule it can see. A create or
        enable that lands after that scan must perform the other half of the
        protocol: re-read the target and synchronously disable its own record
        before returning an error. If the write lands first, archive's scan sees
        it; if archive lands first, this check sees the archived target.
        """
        try:
            self._resolve_schedule_target(target_type, target_id)
        except _StudioRequestError as target_error:
            manager = self._catalog_schedule_manager()
            if delete_on_failure:
                cleaned_up = manager.delete(schedule.id) is True
            else:
                disabled = manager.disable(schedule.id)
                cleaned_up = disabled is not None and not disabled.enabled
            if not cleaned_up:
                raise RuntimeError(
                    f"Schedule '{schedule.id}' targeted an archived component and could not be cleaned up"
                ) from target_error
            raise
        return schedule

    def create_schedule(
        self,
        request: ScheduleCreate,
        if_exists: Literal["error", "update"] = "error",
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ScheduleView]:
        """Create an actor-owned schedule from one typed request.

        Args:
            request: Typed cadence, target, and prompt for the component schedule.
            if_exists: Refuse a name conflict by default, or update a schedule
                with the same name owned by the authenticated actor.
        """
        denied = self._authorize("create_schedule", "mutate", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[ScheduleView], denied)
        try:
            assert _agno_run_context is not None
            if not is_valid_studio_schedule_actor_id(_agno_run_context.user_id):
                raise _StudioRequestError(
                    "invalid_schedule_actor",
                    "The authenticated actor identifier cannot be delegated to a scheduled run.",
                )
            if if_exists not in ("error", "update"):
                raise _StudioRequestError(
                    "invalid_if_exists",
                    "if_exists must be either 'error' or 'update'.",
                    details={"allowed": ["error", "update"]},
                )
            self._validate_schedule_cadence(request)
            component_id = self._resolve_schedule_target(request.target_type, request.target_id)
            manager = self._schedule_manager()
            matches = [schedule for schedule in self._scan_schedules(manager) if schedule.name == request.name]
            if len(matches) > 1:
                raise _StudioRequestError(
                    "schedule_name_conflict",
                    "Multiple scheduler records already use that name; choose a different schedule name.",
                )

            existing = matches[0] if matches else None
            existing_metadata = self._studio_schedule_metadata(existing) if existing is not None else None
            if existing is not None and (
                existing_metadata is None or existing_metadata["owner_actor_id"] != _agno_run_context.user_id
            ):
                raise _StudioRequestError(
                    "schedule_name_conflict",
                    "A scheduler record outside this actor's Studio scope already uses that name.",
                )
            if existing is not None and if_exists == "error":
                raise _StudioRequestError("schedule_conflict", "A Studio schedule with that name already exists.")

            if existing is None:
                try:
                    schedule = self._create_studio_schedule_record(request, component_id, _agno_run_context)
                except ScheduleNameConflictError:
                    raise _StudioRequestError(
                        "schedule_name_conflict",
                        "A scheduler record with that name was created concurrently.",
                    ) from None
                except Exception as error:
                    # Legacy/custom adapters may still expose a backend-specific
                    # exception, so retain the post-write read as a fallback.
                    if self.db.get_schedule_by_name(request.name) is None:
                        raise
                    raise _StudioRequestError(
                        "schedule_name_conflict",
                        "A scheduler record with that name was created concurrently.",
                    ) from error
                status = "created"
            else:
                from agno.scheduler.cron import compute_next_run

                updated = manager._update_studio(
                    existing.id,
                    cron_expr=request.cron,
                    endpoint=f"/{request.target_type}s/{component_id}/runs",
                    method="POST",
                    description=request.description,
                    payload=self._schedule_payload(request),
                    timezone=request.timezone,
                    next_run_at=compute_next_run(request.cron, request.timezone),
                    target_type=request.target_type,
                    target_id=component_id,
                    updated_by_run_id=_agno_run_context.run_id,
                    updated_by_session_id=_agno_run_context.session_id,
                )
                if updated is None:
                    raise _StudioRequestError("schedule_not_found", "The schedule no longer exists.", retryable=True)
                schedule = updated
                status = "updated"

            schedule = self._revalidate_schedule_target_after_write(
                schedule,
                request.target_type,
                component_id,
                delete_on_failure=status == "created",
            )

            metadata = self._studio_schedule_metadata(schedule)
            if metadata is None:
                raise RuntimeError("Studio schedule provenance was not persisted faithfully")
            return StudioResult[ScheduleView](ok=True, status=status, data=self._schedule_view(schedule, metadata))
        except _StudioRequestError as error:
            return cast(StudioResult[ScheduleView], self._request_failure(error))
        except Exception:
            return cast(StudioResult[ScheduleView], self._internal_failure("create schedule"))

    def list_schedules(
        self,
        enabled_only: bool = False,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[List[ScheduleView]]:
        """List schedules owned by the authenticated actor.

        Args:
            enabled_only: Return only schedules currently enabled for execution.
        """
        denied = self._authorize("list_schedules", "read", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[List[ScheduleView]], denied)
        try:
            assert _agno_run_context is not None
            if not isinstance(enabled_only, bool):
                raise _StudioRequestError("invalid_enabled_filter", "enabled_only must be a boolean.")
            views: List[ScheduleView] = []
            for schedule in self._scan_schedules(self._schedule_manager(), enabled=True if enabled_only else None):
                metadata = self._studio_schedule_metadata(schedule)
                if metadata is not None and metadata["owner_actor_id"] == _agno_run_context.user_id:
                    views.append(self._schedule_view(schedule, metadata))
                    if len(views) >= self.list_limit:
                        break
            return StudioResult[List[ScheduleView]](ok=True, status="listed", data=views)
        except _StudioRequestError as error:
            return cast(StudioResult[List[ScheduleView]], self._request_failure(error))
        except Exception:
            return cast(StudioResult[List[ScheduleView]], self._internal_failure("list schedules"))

    def get_schedule(
        self,
        schedule_id: str,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ScheduleView]:
        """Get one schedule owned by the authenticated actor.

        Args:
            schedule_id: Exact schedule id returned by list_schedules.
        """
        denied = self._authorize("get_schedule", "read", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[ScheduleView], denied)
        try:
            assert _agno_run_context is not None
            schedule, metadata = self._owned_schedule(schedule_id, _agno_run_context)
            return StudioResult[ScheduleView](ok=True, status="found", data=self._schedule_view(schedule, metadata))
        except _StudioRequestError as error:
            return cast(StudioResult[ScheduleView], self._request_failure(error))
        except Exception:
            return cast(StudioResult[ScheduleView], self._internal_failure("get schedule"))

    def get_schedule_runs(
        self,
        schedule_id: str,
        limit: int = 10,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[List[ScheduleRunView]]:
        """List safe run summaries for an actor-owned schedule.

        Args:
            schedule_id: Exact schedule id returned by list_schedules.
            limit: Maximum run summaries to return, from 1 through 100.
        """
        denied = self._authorize("get_schedule_runs", "read", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[List[ScheduleRunView]], denied)
        try:
            assert _agno_run_context is not None
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
                raise _StudioRequestError("invalid_schedule_run_limit", "limit must be an integer from 1 through 100.")
            self._owned_schedule(schedule_id, _agno_run_context)
            runs = self._schedule_manager().get_runs(schedule_id, limit=limit)
            return StudioResult[List[ScheduleRunView]](
                ok=True,
                status="listed",
                data=[self._schedule_run_view(run) for run in runs],
            )
        except _StudioRequestError as error:
            return cast(StudioResult[List[ScheduleRunView]], self._request_failure(error))
        except Exception:
            return cast(StudioResult[List[ScheduleRunView]], self._internal_failure("list schedule runs"))

    def trigger_schedule(
        self,
        schedule_id: str,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ScheduleActionView]:
        """Queue an enabled actor-owned schedule for its next poll interval.

        Args:
            schedule_id: Exact schedule id returned by list_schedules.
        """
        denied = self._authorize("trigger_schedule", "mutate", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[ScheduleActionView], denied)
        try:
            assert _agno_run_context is not None
            schedule, metadata = self._owned_schedule(schedule_id, _agno_run_context)
            if not schedule.enabled:
                raise _StudioRequestError(
                    "schedule_disabled",
                    "The schedule is disabled; enable it before triggering.",
                )
            self._resolve_schedule_target(metadata["target_type"], metadata["target_id"])
            import time

            updated = self._schedule_manager().update(schedule_id, next_run_at=int(time.time()))
            if updated is None:
                raise _StudioRequestError("schedule_not_found", "The schedule no longer exists.", retryable=True)
            return StudioResult[ScheduleActionView](
                ok=True,
                status="triggered",
                data=self._schedule_action_view(updated, metadata),
            )
        except _StudioRequestError as error:
            return cast(StudioResult[ScheduleActionView], self._request_failure(error))
        except Exception:
            return cast(StudioResult[ScheduleActionView], self._internal_failure("trigger schedule"))

    def enable_schedule(
        self,
        schedule_id: str,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ScheduleActionView]:
        """Enable an actor-owned schedule whose target remains publishable.

        Args:
            schedule_id: Exact schedule id returned by list_schedules.
        """
        denied = self._authorize("enable_schedule", "mutate", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[ScheduleActionView], denied)
        try:
            assert _agno_run_context is not None
            schedule, metadata = self._owned_schedule(schedule_id, _agno_run_context)
            self._resolve_schedule_target(metadata["target_type"], metadata["target_id"])
            if schedule.enabled:
                schedule = self._revalidate_schedule_target_after_write(
                    schedule,
                    metadata["target_type"],
                    metadata["target_id"],
                )
                return StudioResult[ScheduleActionView](
                    ok=True,
                    status="already_enabled",
                    data=self._schedule_action_view(schedule, metadata),
                )
            updated = self._schedule_manager().enable(schedule_id)
            if updated is None:
                raise _StudioRequestError("schedule_not_found", "The schedule no longer exists.", retryable=True)
            updated = self._revalidate_schedule_target_after_write(
                updated,
                metadata["target_type"],
                metadata["target_id"],
            )
            return StudioResult[ScheduleActionView](
                ok=True,
                status="enabled",
                data=self._schedule_action_view(updated, metadata),
            )
        except _StudioRequestError as error:
            return cast(StudioResult[ScheduleActionView], self._request_failure(error))
        except Exception:
            return cast(StudioResult[ScheduleActionView], self._internal_failure("enable schedule"))

    def disable_schedule(
        self,
        schedule_id: str,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ScheduleActionView]:
        """Disable an actor-owned schedule without dispatching it.

        Args:
            schedule_id: Exact schedule id returned by list_schedules.
        """
        denied = self._authorize("disable_schedule", "mutate", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[ScheduleActionView], denied)
        try:
            assert _agno_run_context is not None
            schedule, metadata = self._owned_schedule(schedule_id, _agno_run_context)
            if not schedule.enabled:
                return StudioResult[ScheduleActionView](
                    ok=True,
                    status="already_disabled",
                    data=self._schedule_action_view(schedule, metadata),
                )
            updated = self._schedule_manager().disable(schedule_id)
            if updated is None:
                raise _StudioRequestError("schedule_not_found", "The schedule no longer exists.", retryable=True)
            return StudioResult[ScheduleActionView](
                ok=True,
                status="disabled",
                data=self._schedule_action_view(updated, metadata),
            )
        except _StudioRequestError as error:
            return cast(StudioResult[ScheduleActionView], self._request_failure(error))
        except Exception:
            return cast(StudioResult[ScheduleActionView], self._internal_failure("disable schedule"))

    def delete_schedule(
        self,
        schedule_id: str,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ScheduleActionView]:
        """Delete an actor-owned schedule and its scheduler run history.

        Args:
            schedule_id: Exact schedule id returned by list_schedules.
        """
        denied = self._authorize("delete_schedule", "mutate", _agno_run_context)
        if denied is not None:
            return cast(StudioResult[ScheduleActionView], denied)
        try:
            assert _agno_run_context is not None
            schedule, metadata = self._owned_schedule(schedule_id, _agno_run_context)
            if not self._schedule_manager().delete(schedule_id):
                raise _StudioRequestError("schedule_not_found", "The schedule no longer exists.", retryable=True)
            return StudioResult[ScheduleActionView](
                ok=True,
                status="deleted",
                data=self._schedule_action_view(schedule, metadata),
            )
        except _StudioRequestError as error:
            return cast(StudioResult[ScheduleActionView], self._request_failure(error))
        except Exception:
            return cast(StudioResult[ScheduleActionView], self._internal_failure("delete schedule"))

    # ------------------------------------------------------------------
    # Async parity. Sync DB control-plane work runs in a worker thread;
    # runner dispatch uses its native async methods.
    # ------------------------------------------------------------------

    async def alist_models(self, _agno_run_context: Optional[RunContext] = None) -> StudioResult[List[ModelRef]]:
        return await asyncio.to_thread(self.list_models, _agno_run_context)

    async def alist_tools(self, _agno_run_context: Optional[RunContext] = None) -> StudioResult[List[ToolRef]]:
        return await asyncio.to_thread(self.list_tools, _agno_run_context)

    async def alist_functions(self, _agno_run_context: Optional[RunContext] = None) -> StudioResult[List[FunctionRef]]:
        return await asyncio.to_thread(self.list_functions, _agno_run_context)

    async def alist_agents(
        self, _agno_run_context: Optional[RunContext] = None
    ) -> StudioResult[List[ComponentSummary]]:
        return await asyncio.to_thread(self.list_agents, _agno_run_context)

    async def alist_teams(self, _agno_run_context: Optional[RunContext] = None) -> StudioResult[List[ComponentSummary]]:
        return await asyncio.to_thread(self.list_teams, _agno_run_context)

    async def alist_workflows(
        self, _agno_run_context: Optional[RunContext] = None
    ) -> StudioResult[List[ComponentSummary]]:
        return await asyncio.to_thread(self.list_workflows, _agno_run_context)

    async def aget_agent(
        self,
        component_id: str,
        version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[AgentView]:
        return await asyncio.to_thread(self.get_agent, component_id, version, _agno_run_context)

    async def aget_team(
        self,
        component_id: str,
        version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[TeamView]:
        return await asyncio.to_thread(self.get_team, component_id, version, _agno_run_context)

    async def aget_workflow(
        self,
        component_id: str,
        version: Optional[int] = None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[WorkflowView]:
        return await asyncio.to_thread(self.get_workflow, component_id, version, _agno_run_context)

    async def alist_versions(
        self,
        component_id: str,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[List[VersionSummary]]:
        return await asyncio.to_thread(self.list_versions, component_id, _agno_run_context)

    async def aget_version(
        self,
        component_id: str,
        version: int,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ComponentView]:
        return await asyncio.to_thread(self.get_version, component_id, version, _agno_run_context)

    async def acreate_agent(
        self,
        request: AgentCreate,
        save_as: SaveStage = "draft",
        if_exists: IfExists = "error",
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[AgentView]:
        return await asyncio.to_thread(self.create_agent, request, save_as, if_exists, _agno_run_context)

    async def acreate_team(
        self,
        request: TeamCreate,
        save_as: SaveStage = "draft",
        if_exists: IfExists = "error",
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[TeamView]:
        return await asyncio.to_thread(self.create_team, request, save_as, if_exists, _agno_run_context)

    async def acreate_workflow(
        self,
        request: WorkflowCreate,
        save_as: SaveStage = "draft",
        if_exists: IfExists = "error",
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[WorkflowView]:
        return await asyncio.to_thread(self.create_workflow, request, save_as, if_exists, _agno_run_context)

    async def aedit_agent(
        self,
        component_id: str,
        patch: AgentPatch,
        expected_version: int,
        save_as: SaveStage = "draft",
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[AgentView]:
        return await asyncio.to_thread(
            self.edit_agent,
            component_id,
            patch,
            expected_version,
            save_as,
            _agno_run_context,
        )

    async def aedit_team(
        self,
        component_id: str,
        patch: TeamPatch,
        expected_version: int,
        save_as: SaveStage = "draft",
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[TeamView]:
        return await asyncio.to_thread(
            self.edit_team,
            component_id,
            patch,
            expected_version,
            save_as,
            _agno_run_context,
        )

    async def aedit_workflow(
        self,
        component_id: str,
        patch: WorkflowPatch,
        expected_version: int,
        save_as: SaveStage = "draft",
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[WorkflowView]:
        return await asyncio.to_thread(
            self.edit_workflow,
            component_id,
            patch,
            expected_version,
            save_as,
            _agno_run_context,
        )

    async def apublish_component(
        self,
        component_id: str,
        version: int,
        expected_current_version: int | None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ComponentView]:
        return await asyncio.to_thread(
            self.publish_component,
            component_id,
            version,
            expected_current_version,
            _agno_run_context,
        )

    async def aset_current_version(
        self,
        component_id: str,
        version: int,
        expected_current_version: int | None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ComponentView]:
        return await asyncio.to_thread(
            self.set_current_version,
            component_id,
            version,
            expected_current_version,
            _agno_run_context,
        )

    async def adelete_version(
        self,
        component_id: str,
        version: int,
        expected_latest_version: int,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ComponentActionView]:
        return await asyncio.to_thread(
            self.delete_version,
            component_id,
            version,
            expected_latest_version,
            _agno_run_context,
        )

    async def aarchive_agent(
        self,
        component_id: str,
        expected_current_version: int | None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ComponentActionView]:
        return await asyncio.to_thread(
            self.archive_agent,
            component_id,
            expected_current_version,
            _agno_run_context,
        )

    async def aarchive_team(
        self,
        component_id: str,
        expected_current_version: int | None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ComponentActionView]:
        return await asyncio.to_thread(
            self.archive_team,
            component_id,
            expected_current_version,
            _agno_run_context,
        )

    async def aarchive_workflow(
        self,
        component_id: str,
        expected_current_version: int | None,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ComponentActionView]:
        return await asyncio.to_thread(
            self.archive_workflow,
            component_id,
            expected_current_version,
            _agno_run_context,
        )

    async def arun_agent(
        self,
        agent_id: str,
        message: str,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        denied = self._authorize("run_agent", "mutate", _agno_run_context)
        if denied is not None:
            return str(denied)
        try:
            self._ensure_component_type_enabled("agent")
            await asyncio.to_thread(self._ensure_no_source_collision, agent_id, "agent")
            return await self._runner_tools.arun_agent(agent_id, message, _agno_run_context)
        except _StudioRequestError as error:
            return str(self._request_failure(error))
        except Exception:
            return str(self._internal_failure("run agent"))

    async def arun_team(
        self,
        team_id: str,
        message: str,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        denied = self._authorize("run_team", "mutate", _agno_run_context)
        if denied is not None:
            return str(denied)
        try:
            self._ensure_component_type_enabled("team")
            await asyncio.to_thread(self._ensure_no_source_collision, team_id, "team")
            return await self._runner_tools.arun_team(team_id, message, _agno_run_context)
        except _StudioRequestError as error:
            return str(self._request_failure(error))
        except Exception:
            return str(self._internal_failure("run team"))

    async def arun_workflow(
        self,
        workflow_id: str,
        message: str,
        _agno_run_context: Optional[RunContext] = None,
    ) -> str:
        denied = self._authorize("run_workflow", "mutate", _agno_run_context)
        if denied is not None:
            return str(denied)
        try:
            self._ensure_component_type_enabled("workflow")
            await asyncio.to_thread(self._ensure_no_source_collision, workflow_id, "workflow")
            return await self._runner_tools.arun_workflow(workflow_id, message, _agno_run_context)
        except _StudioRequestError as error:
            return str(self._request_failure(error))
        except Exception:
            return str(self._internal_failure("run workflow"))

    async def acreate_schedule(
        self,
        request: ScheduleCreate,
        if_exists: Literal["error", "update"] = "error",
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ScheduleView]:
        return await asyncio.to_thread(
            self.create_schedule,
            request,
            if_exists,
            _agno_run_context,
        )

    async def alist_schedules(
        self,
        enabled_only: bool = False,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[List[ScheduleView]]:
        return await asyncio.to_thread(self.list_schedules, enabled_only, _agno_run_context)

    async def aget_schedule(
        self,
        schedule_id: str,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ScheduleView]:
        return await asyncio.to_thread(self.get_schedule, schedule_id, _agno_run_context)

    async def aget_schedule_runs(
        self,
        schedule_id: str,
        limit: int = 10,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[List[ScheduleRunView]]:
        return await asyncio.to_thread(self.get_schedule_runs, schedule_id, limit, _agno_run_context)

    async def atrigger_schedule(
        self,
        schedule_id: str,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ScheduleActionView]:
        return await asyncio.to_thread(self.trigger_schedule, schedule_id, _agno_run_context)

    async def aenable_schedule(
        self,
        schedule_id: str,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ScheduleActionView]:
        return await asyncio.to_thread(self.enable_schedule, schedule_id, _agno_run_context)

    async def adisable_schedule(
        self,
        schedule_id: str,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ScheduleActionView]:
        return await asyncio.to_thread(self.disable_schedule, schedule_id, _agno_run_context)

    async def adelete_schedule(
        self,
        schedule_id: str,
        _agno_run_context: Optional[RunContext] = None,
    ) -> StudioResult[ScheduleActionView]:
        return await asyncio.to_thread(self.delete_schedule, schedule_id, _agno_run_context)


def _resolve_flags(
    agents: Optional[bool],
    teams: Optional[bool],
    workflows: Optional[bool],
    has_agents_list: bool,
    has_teams_list: bool,
    has_workflows_list: bool,
) -> tuple[bool, bool, bool]:
    agent_enabled = bool(agents) if agents is not None else True
    team_enabled = bool(teams) if teams is not None else has_agents_list or has_teams_list
    workflow_enabled = (
        bool(workflows) if workflows is not None else has_agents_list or has_teams_list or has_workflows_list
    )
    return agent_enabled, team_enabled, workflow_enabled


# Async aliases must expose the canonical sync documentation. Toolkit schema
# processing reads each callable independently, so this keeps descriptions as
# well as signatures in lockstep instead of letting thin wrappers overwrite the
# model-facing contract.
for _sync_name, _async_name in (
    ("list_models", "alist_models"),
    ("list_tools", "alist_tools"),
    ("list_functions", "alist_functions"),
    ("list_agents", "alist_agents"),
    ("list_teams", "alist_teams"),
    ("list_workflows", "alist_workflows"),
    ("get_agent", "aget_agent"),
    ("get_team", "aget_team"),
    ("get_workflow", "aget_workflow"),
    ("list_versions", "alist_versions"),
    ("get_version", "aget_version"),
    ("create_agent", "acreate_agent"),
    ("create_team", "acreate_team"),
    ("create_workflow", "acreate_workflow"),
    ("edit_agent", "aedit_agent"),
    ("edit_team", "aedit_team"),
    ("edit_workflow", "aedit_workflow"),
    ("publish_component", "apublish_component"),
    ("set_current_version", "aset_current_version"),
    ("delete_version", "adelete_version"),
    ("archive_agent", "aarchive_agent"),
    ("archive_team", "aarchive_team"),
    ("archive_workflow", "aarchive_workflow"),
    ("run_agent", "arun_agent"),
    ("run_team", "arun_team"),
    ("run_workflow", "arun_workflow"),
    ("create_schedule", "acreate_schedule"),
    ("list_schedules", "alist_schedules"),
    ("get_schedule", "aget_schedule"),
    ("get_schedule_runs", "aget_schedule_runs"),
    ("trigger_schedule", "atrigger_schedule"),
    ("enable_schedule", "aenable_schedule"),
    ("disable_schedule", "adisable_schedule"),
    ("delete_schedule", "adelete_schedule"),
):
    getattr(StudioTools, _async_name).__doc__ = getattr(StudioTools, _sync_name).__doc__


__all__ = [
    "StudioAccess",
    "StudioAction",
    "StudioAuthorizer",
    "StudioTools",
]
