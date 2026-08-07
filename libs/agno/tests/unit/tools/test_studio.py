"""Contract tests for the typed StudioTools 2.9 control plane.

These tests deliberately exercise a real SQLite component catalog. Studio 2.9
is a breaking API: requests are typed, one database is fixed at construction,
authorization is mandatory, creates are draft-first, and lifecycle mutations
use compare-and-set guards.
"""

from __future__ import annotations

import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from typing import Any

import pytest

from agno.agent import Agent
from agno.db.base import ComponentType
from agno.db.schemas.scheduler import STUDIO_SCHEDULE_MANAGED_BY, ScheduleNameConflictError
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat, OpenAIResponses
from agno.registry import Registry
from agno.run import RunContext
from agno.scheduler.manager import ScheduleManager
from agno.tools.calculator import CalculatorTools
from agno.tools.function import Function
from agno.tools.studio import StudioTools
from agno.tools.studio_schema import (
    AgentCreate,
    AgentPatch,
    AgentView,
    AgentWorkflowStep,
    ComponentRef,
    ContextPolicy,
    ContextPolicyPatch,
    FunctionWorkflowStep,
    ModelRef,
    ScheduleActionView,
    ScheduleCreate,
    ScheduleRunView,
    ScheduleView,
    StudioResult,
    TeamCreate,
    TeamPatch,
    TeamView,
    TeamWorkflowStep,
    ToolRef,
    WorkflowCreate,
    WorkflowPatch,
    WorkflowView,
)
from agno.tools.toolkit import Toolkit

MODEL_ID = "gpt-5.4"
MODEL_PROVIDER = "OpenAI"
MODEL_NAME = "OpenAIResponses"
MODEL_BASE_URL_SECRET = "https://model-secret.invalid/v1"
MODEL_API_KEY_SECRET = "sk-studio-test-secret"


def _model_ref() -> ModelRef:
    return ModelRef(id=MODEL_ID, provider=MODEL_PROVIDER, name=MODEL_NAME)


def _allow(_context: RunContext, _access: str, _action: str) -> bool:
    return True


def _error_code(result: StudioResult[Any]) -> str:
    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    return result.error.code


@pytest.fixture
def run_context() -> RunContext:
    return RunContext(
        run_id="studio-run",
        session_id="studio-session",
        user_id="studio-admin",
    )


@pytest.fixture
def db(tmp_path) -> SqliteDb:
    return SqliteDb(
        id="fixed-studio-catalog",
        db_file=str(tmp_path / "private-catalog-location.sqlite"),
    )


@pytest.fixture
def registry(db: SqliteDb) -> Registry:
    model = OpenAIResponses(
        id=MODEL_ID,
        base_url=MODEL_BASE_URL_SECRET,
        api_key=MODEL_API_KEY_SECRET,
    )
    return Registry(
        name="Studio contract registry",
        tools=[CalculatorTools()],
        models=[model],
        dbs=[db],
    )


@pytest.fixture
def studio(registry: Registry, db: SqliteDb) -> StudioTools:
    return StudioTools(
        registry=registry,
        db=db,
        authorize=_allow,
        default_model=_model_ref(),
        default_context=ContextPolicy(history_runs=4),
    )


def _agent_request(
    *,
    component_id: str | None = None,
    name: str = "Research Agent",
    instructions: str = "Research the topic and cite sources.",
) -> AgentCreate:
    return AgentCreate(
        component_id=component_id,
        name=name,
        instructions=instructions,
    )


def _create_agent(
    studio: StudioTools,
    run_context: RunContext,
    *,
    component_id: str,
    save_as: str = "draft",
) -> StudioResult[AgentView]:
    return studio.create_agent(
        _agent_request(component_id=component_id, name=component_id),
        save_as=save_as,  # type: ignore[arg-type]
        _agno_run_context=run_context,
    )


class TestConstructionAndToolContract:
    def test_fixed_db_and_authorizer_are_required(self, registry: Registry, db: SqliteDb):
        async def async_authorize(_context: RunContext, _access: str, _action: str) -> bool:
            return True

        with pytest.raises(TypeError):
            StudioTools(registry=registry, authorize=_allow)  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            StudioTools(registry=registry, db=db)  # type: ignore[call-arg]
        with pytest.raises(ValueError, match="fixed catalog db"):
            StudioTools(registry=registry, db=None, authorize=_allow)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="authorize must be callable"):
            StudioTools(registry=registry, db=db, authorize=None)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="authorize must be synchronous"):
            StudioTools(registry=registry, db=db, authorize=async_authorize)
        with pytest.raises(ValueError, match="synchronous catalog db with atomic component persistence"):
            StudioTools(
                registry=registry,
                db=SimpleNamespace(supports_component_persistence=False),  # type: ignore[arg-type]
                authorize=_allow,
            )

    def test_explicit_catalog_is_used_instead_of_a_registry_db(self, tmp_path):
        registry_db = SqliteDb(id="registry-db", db_file=str(tmp_path / "registry.sqlite"))
        fixed_db = SqliteDb(id="fixed-db", db_file=str(tmp_path / "fixed.sqlite"))
        registry = Registry(
            name="Two DB registry",
            models=[OpenAIResponses(id=MODEL_ID)],
            dbs=[registry_db],
        )
        tool = StudioTools(
            registry=registry,
            db=fixed_db,
            authorize=_allow,
            default_model=_model_ref(),
        )
        context = RunContext(run_id="r", session_id="s", user_id="u")

        result = tool.create_agent(_agent_request(component_id="fixed"), _agno_run_context=context)

        assert result.ok is True
        assert tool.db is fixed_db
        assert tool._runner_tools.db is fixed_db
        assert fixed_db.get_component("fixed") is not None
        assert registry_db.get_component("fixed") is None
        assert "list_dbs" not in tool.functions

    @pytest.mark.parametrize(
        ("list_argument", "expected_flags"),
        [
            ("agents_list", (True, True, True)),
            ("teams_list", (True, True, True)),
            ("workflows_list", (True, False, True)),
        ],
    )
    def test_component_lists_auto_enable_their_own_and_downstream_surfaces(
        self,
        registry: Registry,
        db: SqliteDb,
        list_argument: str,
        expected_flags: tuple[bool, bool, bool],
    ):
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=_model_ref(),
            **{list_argument: []},
        )

        assert (tool.enable_agents, tool.enable_teams, tool.enable_workflows) == expected_flags
        surfaces = {
            "agent": {"list_agents", "get_agent", "create_agent", "edit_agent", "archive_agent", "run_agent"},
            "team": {"list_teams", "get_team", "create_team", "edit_team", "archive_team", "run_team"},
            "workflow": {
                "list_workflows",
                "get_workflow",
                "create_workflow",
                "edit_workflow",
                "archive_workflow",
                "run_workflow",
            },
        }
        for enabled, surface in zip(expected_flags, surfaces.values()):
            if enabled:
                assert surface <= set(tool.functions)
                assert surface <= set(tool.async_functions)
            else:
                assert surface.isdisjoint(tool.functions)
                assert surface.isdisjoint(tool.async_functions)

    @pytest.mark.parametrize(
        ("list_argument", "flag_argument", "surface"),
        [
            ("agents_list", "agents", {"list_agents", "create_agent", "run_agent"}),
            ("teams_list", "teams", {"list_teams", "create_team", "run_team"}),
            ("workflows_list", "workflows", {"list_workflows", "create_workflow", "run_workflow"}),
        ],
    )
    def test_explicit_false_overrides_list_auto_enablement(
        self,
        registry: Registry,
        db: SqliteDb,
        list_argument: str,
        flag_argument: str,
        surface: set[str],
    ):
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=_model_ref(),
            **{list_argument: [], flag_argument: False},
        )

        assert surface.isdisjoint(tool.functions)
        assert surface.isdisjoint(tool.async_functions)

    @pytest.mark.parametrize(
        "method",
        [StudioTools.create_agent, StudioTools.create_team, StudioTools.create_workflow],
    )
    def test_create_python_signatures_are_the_typed_breaking_api(self, method: Any):
        parameters = inspect.signature(method).parameters

        assert list(parameters) == ["self", "request", "save_as", "if_exists", "_agno_run_context"]
        legacy_names = {
            "name",
            "instructions",
            "model_id",
            "tool_names",
            "agent_ids",
            "team_ids",
            "step_specs",
            "db_id",
        }
        assert not legacy_names & set(parameters)

    def test_workflows_reject_duplicate_registered_function_names_at_construction(
        self,
        registry: Registry,
        db: SqliteDb,
    ):
        def first(value: str) -> str:
            return value

        def second(value: str) -> str:
            return value

        second.__name__ = first.__name__
        registry.functions.extend([first, second])

        with pytest.raises(ValueError, match="unique registered function names.*first"):
            StudioTools(
                registry=registry,
                db=db,
                authorize=_allow,
                default_model=_model_ref(),
                workflows=True,
            )

    def test_agent_facing_create_schema_is_typed_and_hides_run_context(self, studio: StudioTools):
        function = studio.functions["create_agent"]
        function.process_entrypoint()
        schema = function.parameters
        properties = schema["properties"]

        assert set(properties) == {"request", "save_as", "if_exists"}
        assert schema["required"] == ["request"]
        assert properties["request"]["additionalProperties"] is False
        assert properties["request"]["required"] == ["name", "instructions"]
        assert set(properties["save_as"]["enum"]) == {"draft", "published"}
        assert set(properties["if_exists"]["enum"]) == {"error", "return_existing"}
        assert "_agno_run_context" not in properties
        assert "db_id" not in properties

    def test_sync_and_async_registered_tool_schemas_match(self, studio: StudioTools):
        assert set(studio.functions) == set(studio.async_functions)
        for name, sync_function in studio.functions.items():
            async_function = studio.async_functions[name]
            sync_function.process_entrypoint()
            async_function.process_entrypoint()
            assert async_function.parameters == sync_function.parameters, name
            assert async_function.description == sync_function.description, name

    def test_required_nullable_lifecycle_guards_accept_null_in_tool_schema(self, studio: StudioTools):
        for name in ("publish_component", "set_current_version", "archive_agent"):
            function = studio.functions[name]
            function.process_entrypoint()
            schema = function.parameters
            guard = schema["properties"]["expected_current_version"]

            assert "expected_current_version" in schema["required"]
            assert {branch.get("type") for branch in guard["anyOf"]} == {"integer", "null"}
            assert guard["description"]

    def test_every_publish_capable_or_destructive_tool_requires_framework_confirmation(self, studio: StudioTools):
        for name in (
            "create_agent",
            "edit_agent",
            "publish_component",
            "set_current_version",
            "delete_version",
            "archive_agent",
        ):
            assert studio.functions[name].requires_confirmation is True
            assert studio.async_functions[name].requires_confirmation is True
        for name in ("run_agent", "get_agent"):
            assert studio.functions[name].requires_confirmation is not True

        assert "require confirmation even for drafts" in studio.instructions

    def test_team_and_workflow_create_edit_confirmation_is_symmetric(
        self,
        registry: Registry,
        db: SqliteDb,
    ):
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=_model_ref(),
            teams=True,
            workflows=True,
        )

        for name in (
            "create_agent",
            "edit_agent",
            "create_team",
            "edit_team",
            "create_workflow",
            "edit_workflow",
        ):
            assert tool.functions[name].requires_confirmation is True
            assert tool.async_functions[name].requires_confirmation is True

    def test_all_enabled_tool_schemas_are_complete_and_match_async(
        self,
        registry: Registry,
        db: SqliteDb,
    ):
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=_model_ref(),
            teams=True,
            workflows=True,
        )
        missing: list[str] = []
        unresolved_refs: list[str] = []

        def collect_missing(value: Any, path: str) -> None:
            if isinstance(value, dict):
                for unsupported_key in ("$defs", "$ref"):
                    if unsupported_key in value:
                        unresolved_refs.append(f"{path}/{unsupported_key}")
                properties = value.get("properties")
                if isinstance(properties, dict):
                    for field_name, field_schema in properties.items():
                        if not isinstance(field_schema, dict) or not field_schema.get("description"):
                            missing.append(f"{path}/{field_name}")
                for key, nested in value.items():
                    collect_missing(nested, f"{path}/{key}")
            elif isinstance(value, list):
                for index, nested in enumerate(value):
                    collect_missing(nested, f"{path}/{index}")

        for name, function in tool.functions.items():
            async_function = tool.async_functions[name]
            function.process_entrypoint()
            async_function.process_entrypoint()
            collect_missing(function.parameters, name)
            assert async_function.parameters == function.parameters, name
            assert async_function.description == function.description, name

        assert missing == []
        assert unresolved_refs == []

    def test_schedule_mutations_require_framework_confirmation(self, registry: Registry, db: SqliteDb):
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=_model_ref(),
            schedules=True,
        )

        for name in (
            "create_schedule",
            "trigger_schedule",
            "enable_schedule",
            "disable_schedule",
            "delete_schedule",
        ):
            assert tool.functions[name].requires_confirmation is True
            assert tool.async_functions[name].requires_confirmation is True


class TestAuthorization:
    @pytest.mark.parametrize(
        ("context", "expected_code"),
        [
            (None, "auth_context_required"),
            (RunContext(run_id="r", session_id="s"), "unauthenticated"),
        ],
    )
    def test_missing_framework_context_or_actor_fails_closed(
        self,
        studio: StudioTools,
        context: RunContext | None,
        expected_code: str,
    ):
        result = studio.list_models(_agno_run_context=context)

        assert _error_code(result) == expected_code

    def test_context_lookalike_cannot_spoof_framework_injection(self, studio: StudioTools):
        spoof = SimpleNamespace(
            run_id="spoofed-run",
            session_id="spoofed-session",
            user_id="admin",
        )

        result = studio.list_models(_agno_run_context=spoof)  # type: ignore[arg-type]

        assert _error_code(result) == "auth_context_required"

    def test_denial_happens_before_component_or_model_lookup(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
        monkeypatch: pytest.MonkeyPatch,
    ):
        calls: list[tuple[str, str, str]] = []

        def deny(context: RunContext, access: str, action: str) -> bool:
            calls.append((context.user_id or "", access, action))
            return False

        tool = StudioTools(registry=registry, db=db, authorize=deny, default_model=_model_ref())

        def unexpected_lookup(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("authorization must run before lookup")

        monkeypatch.setattr(db, "get_component", unexpected_lookup)
        monkeypatch.setattr(registry, "get_model", unexpected_lookup)

        read = tool.get_agent("possibly-secret", _agno_run_context=run_context)
        mutate = tool.create_agent(_agent_request(component_id="blocked"), _agno_run_context=run_context)

        assert _error_code(read) == "forbidden"
        assert _error_code(mutate) == "forbidden"
        assert calls == [
            ("studio-admin", "read", "get_agent"),
            ("studio-admin", "mutate", "create_agent"),
        ]

    def test_denial_does_not_disclose_component_existence(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
    ):
        allowed = StudioTools(registry=registry, db=db, authorize=_allow, default_model=_model_ref())
        assert _create_agent(allowed, run_context, component_id="exists").ok is True
        denied = StudioTools(
            registry=registry,
            db=db,
            authorize=lambda _context, _access, _action: False,
            default_model=_model_ref(),
        )

        existing = denied.get_agent("exists", _agno_run_context=run_context)
        missing = denied.get_agent("missing", _agno_run_context=run_context)

        assert existing.model_dump() == missing.model_dump()
        assert _error_code(existing) == "forbidden"

    def test_authorizer_exception_is_closed_and_sanitized(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
        caplog: pytest.LogCaptureFixture,
    ):
        def broken(_context: RunContext, _access: str, _action: str) -> bool:
            raise RuntimeError("policy backend at postgres://private-policy-db")

        tool = StudioTools(registry=registry, db=db, authorize=broken, default_model=_model_ref())

        result = tool.list_agents(_agno_run_context=run_context)

        assert _error_code(result) == "authorization_failed"
        assert result.error is not None
        assert "postgres://" not in result.error.message
        assert "private-policy-db" not in caplog.text

    def test_non_boolean_authorizer_result_fails_closed(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
    ):
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=lambda _context, _access, _action: "allow",  # type: ignore[arg-type,return-value]
            default_model=_model_ref(),
        )

        result = tool.list_models(_agno_run_context=run_context)

        assert _error_code(result) == "authorization_failed"

    def test_run_is_denied_before_runner_dispatch(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
        monkeypatch: pytest.MonkeyPatch,
    ):
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=lambda _context, _access, _action: False,
            default_model=_model_ref(),
        )

        def unexpected_dispatch(*_args: Any, **_kwargs: Any) -> str:
            raise AssertionError("denied calls must not reach the runner")

        monkeypatch.setattr(tool._runner_tools, "run_agent", unexpected_dispatch)

        payload = json.loads(tool.run_agent("hidden", "hello", _agno_run_context=run_context))

        assert payload["ok"] is False
        assert payload["error"]["code"] == "forbidden"

    @pytest.mark.asyncio
    async def test_async_calls_use_the_same_fail_closed_authorization(self, studio: StudioTools):
        result = await studio.alist_models()

        assert _error_code(result) == "auth_context_required"

    @pytest.mark.asyncio
    async def test_async_run_methods_honor_disabled_component_flags(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
        monkeypatch: pytest.MonkeyPatch,
    ):
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=_model_ref(),
            agents=False,
            teams=False,
            workflows=False,
        )
        dispatched: list[str] = []

        async def unexpected_dispatch(*_args: Any, **_kwargs: Any) -> str:
            dispatched.append("called")
            return "{}"

        for runner_method in ("arun_agent", "arun_team", "arun_workflow"):
            monkeypatch.setattr(tool._runner_tools, runner_method, unexpected_dispatch)

        for method_name, component_type in (
            ("arun_agent", "agent"),
            ("arun_team", "team"),
            ("arun_workflow", "workflow"),
        ):
            payload = json.loads(await getattr(tool, method_name)("hidden", "hello", _agno_run_context=run_context))
            assert payload["error"]["code"] == "component_type_disabled"
            assert payload["error"]["details"] == {"component_type": component_type}

        assert dispatched == []

    def test_schedule_is_denied_before_target_or_manager_access(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
        monkeypatch: pytest.MonkeyPatch,
    ):
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=lambda _context, _access, _action: False,
            default_model=_model_ref(),
            schedules=True,
        )

        def unexpected_lookup(*_args: Any, **_kwargs: Any) -> str:
            raise AssertionError("denied schedule calls must not resolve targets")

        monkeypatch.setattr(tool, "_resolve_schedule_target", unexpected_lookup)

        result = tool.create_schedule(
            ScheduleCreate(
                name="blocked",
                cron="0 9 * * *",
                target_type="agent",
                target_id="hidden",
                message="hello",
            ),
            _agno_run_context=run_context,
        )

        assert _error_code(result) == "forbidden"


class TestTypedDiscoveryAndCreate:
    def test_discovery_returns_copyable_exact_model_and_tool_refs(
        self,
        studio: StudioTools,
        run_context: RunContext,
    ):
        model_result = studio.list_models(_agno_run_context=run_context)
        tool_result = studio.list_tools(_agno_run_context=run_context)

        assert model_result.ok is True
        assert model_result.data == [_model_ref()]
        assert tool_result.ok is True
        assert tool_result.data is not None
        assert ToolRef(kind="toolkit", name="calculator") in tool_result.data
        assert ToolRef(kind="function", name="add", toolkit="calculator") in tool_result.data

    def test_agent_create_returns_resolved_safe_view_and_persists_draft(
        self,
        studio: StudioTools,
        db: SqliteDb,
        run_context: RunContext,
    ):
        request = AgentCreate(
            component_id="news-scout",
            name="News Scout",
            instructions="Summarize technology news.",
            description="A concise research agent.",
            tools=[ToolRef(kind="toolkit", name="calculator")],
        )

        result = studio.create_agent(request, _agno_run_context=run_context)

        assert result.ok is True
        assert result.status == "created"
        assert isinstance(result.data, AgentView)
        assert result.data.component_id == "news-scout"
        assert result.data.model == _model_ref()
        assert result.data.tools == request.tools
        assert result.data.context == ContextPolicy(history_runs=4)
        assert result.data.version == 1
        assert result.data.stage == "draft"
        assert result.data.is_current is False
        assert result.data.source == "studio"

        component = db.get_component("news-scout", component_type=ComponentType.AGENT)
        config = db.get_config("news-scout", version=1)
        assert component is not None
        assert component["current_version"] is None
        assert config is not None
        assert config["stage"] == "draft"

    def test_exact_model_and_tool_refs_are_enforced(
        self,
        studio: StudioTools,
        run_context: RunContext,
    ):
        wrong_model = studio.create_agent(
            AgentCreate(
                component_id="wrong-model",
                name="Wrong model",
                instructions="Do work.",
                model=ModelRef(id=MODEL_ID, provider="Not OpenAI", name=MODEL_NAME),
            ),
            _agno_run_context=run_context,
        )
        unqualified_function = studio.create_agent(
            AgentCreate(
                component_id="wrong-tool",
                name="Wrong tool",
                instructions="Do work.",
                tools=[ToolRef(kind="function", name="add")],
            ),
            _agno_run_context=run_context,
        )
        exact_function = studio.create_agent(
            AgentCreate(
                component_id="exact-tool",
                name="Exact tool",
                instructions="Do work.",
                tools=[ToolRef(kind="function", name="add", toolkit="calculator")],
            ),
            _agno_run_context=run_context,
        )

        assert _error_code(wrong_model) == "model_not_found"
        assert _error_code(unqualified_function) == "tool_not_found"
        assert exact_function.ok is True
        assert exact_function.data is not None
        assert exact_function.data.tools == [ToolRef(kind="function", name="add", toolkit="calculator")]

    def test_ambiguous_model_id_requires_provider_and_name(
        self,
        db: SqliteDb,
        run_context: RunContext,
    ):
        registry = Registry(
            models=[OpenAIResponses(id=MODEL_ID), OpenAIChat(id=MODEL_ID)],
            dbs=[db],
        )
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=ModelRef(id=MODEL_ID),
        )

        ambiguous = tool.create_agent(
            _agent_request(component_id="ambiguous-model"),
            _agno_run_context=run_context,
        )
        exact = tool.create_agent(
            _agent_request(component_id="exact-model").model_copy(
                update={"model": ModelRef(id=MODEL_ID, provider=MODEL_PROVIDER, name=MODEL_NAME)}
            ),
            _agno_run_context=run_context,
        )

        assert _error_code(ambiguous) == "ambiguous_model"
        assert exact.ok is True

    def test_selected_tool_refs_cannot_expose_the_same_agent_function_name(
        self,
        db: SqliteDb,
        run_context: RunContext,
    ):
        def first_lookup(query: str) -> str:
            return f"first: {query}"

        def second_lookup(query: str) -> str:
            return f"second: {query}"

        first_lookup.__name__ = "lookup"
        second_lookup.__name__ = "lookup"
        registry = Registry(
            tools=[Toolkit(name="firstkit", tools=[first_lookup]), Toolkit(name="secondkit", tools=[second_lookup])],
            models=[OpenAIResponses(id=MODEL_ID)],
            dbs=[db],
        )
        tool = StudioTools(registry=registry, db=db, authorize=_allow, default_model=_model_ref())

        result = tool.create_agent(
            _agent_request(component_id="duplicate-tool-name").model_copy(
                update={
                    "tools": [
                        ToolRef(kind="function", name="lookup", toolkit="firstkit"),
                        ToolRef(kind="function", name="lookup", toolkit="secondkit"),
                    ]
                }
            ),
            _agno_run_context=run_context,
        )

        assert _error_code(result) == "duplicate_tool_name"
        assert db.get_component("duplicate-tool-name") is None

    def test_unqualified_function_ref_rejects_a_different_toolkit_entrypoint(
        self,
        db: SqliteDb,
        run_context: RunContext,
    ):
        def direct_lookup(query: str) -> str:
            return f"direct: {query}"

        def toolkit_lookup(query: str) -> str:
            return f"toolkit: {query}"

        direct_lookup.__name__ = "lookup"
        toolkit_lookup.__name__ = "lookup"
        registry = Registry(
            tools=[direct_lookup, Toolkit(name="shadowkit", tools=[toolkit_lookup])],
            models=[OpenAIResponses(id=MODEL_ID)],
            dbs=[db],
        )
        tool = StudioTools(registry=registry, db=db, authorize=_allow, default_model=_model_ref())

        result = tool.create_agent(
            _agent_request(component_id="ambiguous-flat-tool").model_copy(
                update={"tools": [ToolRef(kind="function", name="lookup")]}
            ),
            _agno_run_context=run_context,
        )

        assert _error_code(result) == "ambiguous_tool_binding"
        assert db.get_component("ambiguous-flat-tool") is None

    @pytest.mark.parametrize("select_toolkit", [False, True])
    def test_agent_create_rejects_functions_without_an_execution_path(
        self,
        db: SqliteDb,
        run_context: RunContext,
        select_toolkit: bool,
    ):
        broken = Function(name="broken", entrypoint=None)
        registered: Any
        ref: ToolRef
        if select_toolkit:
            registered = Toolkit(name="brokenkit")
            registered.functions[broken.name] = broken
            ref = ToolRef(kind="toolkit", name="brokenkit")
        else:
            registered = broken
            ref = ToolRef(kind="function", name="broken")
        registry = Registry(
            tools=[registered],
            models=[OpenAIResponses(id=MODEL_ID)],
            dbs=[db],
        )
        tool = StudioTools(registry=registry, db=db, authorize=_allow, default_model=_model_ref())

        result = tool.create_agent(
            _agent_request(component_id="broken-tool").model_copy(update={"tools": [ref]}),
            save_as="published",
            _agno_run_context=run_context,
        )

        assert _error_code(result) == "tool_not_ready"
        assert db.get_component("broken-tool", include_deleted=True) is None

    @pytest.mark.parametrize("select_toolkit", [False, True])
    def test_agent_create_allows_external_execution_without_a_local_entrypoint(
        self,
        db: SqliteDb,
        run_context: RunContext,
        select_toolkit: bool,
    ):
        external = Function(name="handoff", entrypoint=None, external_execution=True)
        registered: Any
        ref: ToolRef
        if select_toolkit:
            registered = Toolkit(name="external-kit")
            registered.functions[external.name] = external
            ref = ToolRef(kind="toolkit", name="external-kit")
        else:
            registered = external
            ref = ToolRef(kind="function", name="handoff")
        registry = Registry(
            tools=[registered],
            models=[OpenAIResponses(id=MODEL_ID)],
            dbs=[db],
        )
        tool = StudioTools(registry=registry, db=db, authorize=_allow, default_model=_model_ref())

        result = tool.create_agent(
            _agent_request(component_id="external-tool").model_copy(update={"tools": [ref]}),
            save_as="published",
            _agno_run_context=run_context,
        )

        assert result.ok is True
        assert result.data is not None
        assert result.data.stage == "published"
        assert result.data.is_current is True

    def test_code_defined_component_ids_are_reserved(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
    ):
        code_agent = Agent(id="reserved-id", name="Code agent", model=registry.models[0])
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=_model_ref(),
            agents_list=[code_agent],
        )

        result = tool.create_agent(
            _agent_request(component_id="reserved-id"),
            _agno_run_context=run_context,
        )

        assert _error_code(result) == "component_conflict"
        assert db.get_component("reserved-id", include_deleted=True) is None

    def test_existing_db_and_code_id_collision_fails_closed_for_list_get_and_run(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
    ):
        initial = StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=_model_ref(),
        )
        assert _create_agent(initial, run_context, component_id="collision", save_as="published").ok

        code_agent = Agent(
            id="collision",
            name="Code collision",
            instructions="This must never shadow the stored agent.",
            model=registry.models[0],
        )
        collided = StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=_model_ref(),
            agents_list=[code_agent],
        )

        listed = collided.list_agents(_agno_run_context=run_context)
        fetched = collided.get_agent("collision", _agno_run_context=run_context)
        run_payload = json.loads(collided.run_agent("collision", "hello", _agno_run_context=run_context))

        assert _error_code(listed) == "component_source_collision"
        assert _error_code(fetched) == "component_source_collision"
        assert run_payload["error"]["code"] == "component_source_collision"

    def test_runtime_create_and_edit_literals_are_validated(
        self,
        studio: StudioTools,
        db: SqliteDb,
        run_context: RunContext,
    ):
        assert _create_agent(studio, run_context, component_id="literal-guard").ok

        invalid_if_exists = studio.create_agent(
            _agent_request(component_id="literal-guard", name="literal-guard"),
            if_exists="bogus",  # type: ignore[arg-type]
            _agno_run_context=run_context,
        )
        invalid_create_stage = studio.create_agent(
            _agent_request(component_id="invalid-stage"),
            save_as="garbage",  # type: ignore[arg-type]
            _agno_run_context=run_context,
        )
        invalid_edit_stage = studio.edit_agent(
            "literal-guard",
            AgentPatch(description="Must not persist"),
            expected_version=1,
            save_as="garbage",  # type: ignore[arg-type]
            _agno_run_context=run_context,
        )

        assert _error_code(invalid_if_exists) == "invalid_if_exists"
        assert _error_code(invalid_create_stage) == "invalid_save_stage"
        assert _error_code(invalid_edit_stage) == "invalid_save_stage"
        assert db.get_component("invalid-stage") is None
        assert [row["version"] for row in db.list_configs("literal-guard")] == [1]

    def test_omitted_component_id_is_deterministic_and_retry_is_idempotent(
        self,
        studio: StudioTools,
        db: SqliteDb,
        run_context: RunContext,
    ):
        request = _agent_request(name="My GTM Agent")

        first = studio.create_agent(request, _agno_run_context=run_context)
        duplicate = studio.create_agent(request, _agno_run_context=run_context)
        retry = studio.create_agent(request, if_exists="return_existing", _agno_run_context=run_context)
        changed_retry = studio.create_agent(
            request.model_copy(update={"instructions": "Different instructions."}),
            if_exists="return_existing",
            _agno_run_context=run_context,
        )

        assert first.ok is True
        assert first.data is not None
        assert first.data.component_id == "my-gtm-agent"
        assert _error_code(duplicate) == "component_conflict"
        assert retry.ok is True
        assert retry.status == "existing"
        assert retry.data == first.data
        assert _error_code(changed_retry) == "component_conflict"
        assert len(db.list_configs("my-gtm-agent")) == 1
        assert db.get_component("my-gtm-agent-2") is None

    @pytest.mark.parametrize("name", ["研究助手", "🚀", "---"])
    def test_name_without_ascii_alphanumeric_slug_requires_explicit_component_id(
        self,
        studio: StudioTools,
        db: SqliteDb,
        run_context: RunContext,
        name: str,
    ):
        result = studio.create_agent(_agent_request(name=name), _agno_run_context=run_context)

        assert _error_code(result) == "component_id_required"
        assert db.get_component("component") is None

    def test_context_patch_rejects_history_runs_while_history_is_disabled(
        self,
        studio: StudioTools,
        db: SqliteDb,
        run_context: RunContext,
    ):
        created = studio.create_agent(
            AgentCreate(
                component_id="context-policy",
                name="Context policy",
                instructions="Keep the context contract explicit.",
                context=ContextPolicy(include_history=False),
            ),
            _agno_run_context=run_context,
        )
        assert created.ok

        rejected = studio.edit_agent(
            "context-policy",
            AgentPatch(context=ContextPolicyPatch(history_runs=7)),
            expected_version=1,
            _agno_run_context=run_context,
        )
        accepted = studio.edit_agent(
            "context-policy",
            AgentPatch(context=ContextPolicyPatch(include_history=True, history_runs=7)),
            expected_version=1,
            _agno_run_context=run_context,
        )

        assert _error_code(rejected) == "invalid_context_policy"
        assert accepted.ok
        assert accepted.data is not None
        assert accepted.data.context.include_history is True
        assert accepted.data.context.history_runs == 7
        assert sorted(row["version"] for row in db.list_configs("context-policy")) == [1, 2]

    def test_concurrent_first_create_is_atomic_and_idempotent(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
    ):
        ready = Barrier(2)

        def authorize(_context: RunContext, _access: str, action: str) -> bool:
            if action == "create_agent":
                ready.wait()
            return True

        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=authorize,
            default_model=_model_ref(),
        )
        request = _agent_request(component_id="concurrent-first-create")

        def create() -> str:
            result = tool.create_agent(
                request,
                if_exists="return_existing",
                _agno_run_context=run_context,
            )
            assert result.ok
            return result.status

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(lambda _index: create(), range(2)))

        assert sorted(statuses) == ["created", "existing"]
        assert [row["version"] for row in db.list_configs("concurrent-first-create")] == [1]

    @pytest.mark.asyncio
    async def test_async_create_uses_the_same_typed_result_contract(
        self,
        studio: StudioTools,
        run_context: RunContext,
    ):
        result = await studio.acreate_agent(
            _agent_request(component_id="async-agent"),
            _agno_run_context=run_context,
        )

        assert isinstance(result, StudioResult)
        assert result.ok is True
        assert isinstance(result.data, AgentView)
        assert result.data.component_id == "async-agent"
        assert result.data.stage == "draft"


class TestLifecycle:
    def test_draft_is_not_current_until_explicit_publish(
        self,
        studio: StudioTools,
        run_context: RunContext,
    ):
        created = _create_agent(studio, run_context, component_id="draft-only")

        current = studio.get_agent("draft-only", _agno_run_context=run_context)
        exact_draft = studio.get_agent("draft-only", version=1, _agno_run_context=run_context)
        run_payload = json.loads(studio.run_agent("draft-only", "hello", _agno_run_context=run_context))

        assert created.data is not None
        assert created.data.stage == "draft"
        assert created.data.is_current is False
        assert _error_code(current) == "published_version_not_found"
        assert exact_draft.ok is True
        assert exact_draft.data is not None
        assert exact_draft.data.stage == "draft"
        assert "error" in run_payload

    def test_publish_edit_cas_and_rollback_lifecycle(
        self,
        studio: StudioTools,
        run_context: RunContext,
    ):
        assert _create_agent(studio, run_context, component_id="lifecycle").ok is True

        published_v1 = studio.publish_component(
            "lifecycle",
            version=1,
            expected_current_version=None,
            _agno_run_context=run_context,
        )
        edited_v2 = studio.edit_agent(
            "lifecycle",
            AgentPatch(description="Version two"),
            expected_version=1,
            _agno_run_context=run_context,
        )
        still_current_v1 = studio.get_agent("lifecycle", _agno_run_context=run_context)
        stale_edit = studio.edit_agent(
            "lifecycle",
            AgentPatch(description="Stale edit"),
            expected_version=1,
            _agno_run_context=run_context,
        )
        stale_publish = studio.publish_component(
            "lifecycle",
            version=2,
            expected_current_version=None,
            _agno_run_context=run_context,
        )
        published_v2 = studio.publish_component(
            "lifecycle",
            version=2,
            expected_current_version=1,
            _agno_run_context=run_context,
        )
        stale_rollback = studio.set_current_version(
            "lifecycle",
            version=1,
            expected_current_version=1,
            _agno_run_context=run_context,
        )
        rollback = studio.set_current_version(
            "lifecycle",
            version=1,
            expected_current_version=2,
            _agno_run_context=run_context,
        )

        assert published_v1.ok is True
        assert published_v1.data is not None
        assert published_v1.data.stage == "published"
        assert published_v1.data.is_current is True
        assert edited_v2.ok is True
        assert edited_v2.data is not None
        assert edited_v2.data.version == 2
        assert edited_v2.data.stage == "draft"
        assert edited_v2.data.is_current is False
        assert still_current_v1.ok is True
        assert still_current_v1.data is not None
        assert still_current_v1.data.version == 1
        assert still_current_v1.data.description is None
        assert _error_code(stale_edit) == "version_conflict"
        assert _error_code(stale_publish) == "version_conflict"
        assert published_v2.ok is True
        assert published_v2.data is not None
        assert published_v2.data.version == 2
        assert published_v2.data.is_current is True
        assert _error_code(stale_rollback) == "version_conflict"
        assert rollback.ok is True
        assert rollback.status == "current_version_set"
        assert rollback.data is not None
        assert rollback.data.version == 1
        assert rollback.data.is_current is True

        versions = studio.list_versions("lifecycle", _agno_run_context=run_context)
        assert versions.ok is True
        assert versions.data is not None
        assert {item.version: item.is_current for item in versions.data} == {1: True, 2: False}

    def test_publish_and_set_current_revalidate_registry_dependencies(
        self,
        studio: StudioTools,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
    ):
        draft = studio.create_agent(
            AgentCreate(
                component_id="publishability-draft",
                name="Publishability draft",
                instructions="Use the registered calculator.",
                tools=[ToolRef(kind="function", name="add", toolkit="calculator")],
            ),
            _agno_run_context=run_context,
        )
        assert draft.ok

        assert _create_agent(studio, run_context, component_id="rollback-publishability", save_as="published").ok
        published_v2 = studio.edit_agent(
            "rollback-publishability",
            AgentPatch(tools=[ToolRef(kind="function", name="add", toolkit="calculator")]),
            expected_version=1,
            save_as="published",
            _agno_run_context=run_context,
        )
        assert published_v2.ok
        assert studio.set_current_version(
            "rollback-publishability",
            version=1,
            expected_current_version=2,
            _agno_run_context=run_context,
        ).ok

        registry.tools.clear()

        publish = studio.publish_component(
            "publishability-draft",
            version=1,
            expected_current_version=None,
            _agno_run_context=run_context,
        )
        set_current = studio.set_current_version(
            "rollback-publishability",
            version=2,
            expected_current_version=1,
            _agno_run_context=run_context,
        )

        assert _error_code(publish) == "tool_not_found"
        assert _error_code(set_current) == "tool_not_found"
        assert db.get_component("publishability-draft")["current_version"] is None  # type: ignore[index]
        assert db.get_component("rollback-publishability")["current_version"] == 1  # type: ignore[index]

    def test_immediate_publish_recursively_revalidates_pinned_children(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
    ):
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=_model_ref(),
            teams=True,
        )
        child = tool.create_agent(
            AgentCreate(
                component_id="strict-child",
                name="Strict child",
                instructions="Use the registered calculator.",
                tools=[ToolRef(kind="function", name="add", toolkit="calculator")],
            ),
            save_as="published",
            _agno_run_context=run_context,
        )
        assert child.ok

        registry.tools.clear()

        parent = tool.create_team(
            TeamCreate(
                component_id="strict-parent",
                name="Strict parent",
                instructions="Delegate to the pinned child.",
                members=[ComponentRef(component_type="agent", component_id="strict-child", version=1)],
            ),
            save_as="published",
            _agno_run_context=run_context,
        )

        assert _error_code(parent) in {"tool_not_found", "component_not_publishable"}
        assert db.get_component("strict-parent") is None

    def test_publish_rejects_runtime_config_that_diverges_from_typed_manifest(
        self,
        studio: StudioTools,
        db: SqliteDb,
        run_context: RunContext,
    ):
        created = studio.create_agent(
            AgentCreate(
                component_id="diverged-runtime",
                name="Diverged runtime",
                instructions="Use the registered calculator.",
                tools=[ToolRef(kind="function", name="add", toolkit="calculator")],
            ),
            _agno_run_context=run_context,
        )
        assert created.ok
        row = db.get_config("diverged-runtime", version=1)
        assert row is not None
        corrupted = dict(row["config"])
        corrupted.pop("tools")
        # Simulate out-of-band storage corruption. The public DB lifecycle now
        # keeps version payloads immutable, so an adversarial fidelity test must
        # bypass that contract deliberately rather than weakening it.
        configs_table = db._get_table(table_type="component_configs")
        assert configs_table is not None
        with db.Session() as session, session.begin():
            session.execute(
                configs_table.update()
                .where(
                    configs_table.c.component_id == "diverged-runtime",
                    configs_table.c.version == 1,
                )
                .values(config=corrupted)
            )

        result = studio.publish_component(
            "diverged-runtime",
            version=1,
            expected_current_version=None,
            _agno_run_context=run_context,
        )

        assert _error_code(result) == "component_not_publishable"
        assert db.get_component("diverged-runtime")["current_version"] is None  # type: ignore[index]

    def test_draft_delete_is_guarded_and_does_not_delete_component(
        self,
        studio: StudioTools,
        db: SqliteDb,
        run_context: RunContext,
    ):
        assert _create_agent(studio, run_context, component_id="delete-draft").ok is True
        edited = studio.edit_agent(
            "delete-draft",
            AgentPatch(description="Disposable draft"),
            expected_version=1,
            _agno_run_context=run_context,
        )
        assert edited.ok is True

        stale_delete = studio.delete_version(
            "delete-draft",
            version=2,
            expected_latest_version=1,
            _agno_run_context=run_context,
        )
        deleted = studio.delete_version(
            "delete-draft",
            version=2,
            expected_latest_version=2,
            _agno_run_context=run_context,
        )

        assert _error_code(stale_delete) == "version_conflict"
        assert deleted.ok is True
        assert deleted.status == "draft_deleted"
        assert deleted.data is not None
        assert deleted.data.version == 2
        component = db.get_component("delete-draft")
        assert component is not None
        assert component["metadata"]["_agno"]["studio"]["last_action"] == "delete_version"
        assert component["metadata"]["_agno"]["studio"]["last_actor_id"] == run_context.user_id
        assert db.get_config("delete-draft", version=2) is None
        assert [row["version"] for row in db.list_configs("delete-draft")] == [1]

    def test_published_version_delete_returns_stable_non_retryable_error(
        self,
        studio: StudioTools,
        db: SqliteDb,
        run_context: RunContext,
    ):
        assert _create_agent(studio, run_context, component_id="published-delete", save_as="published").ok

        result = studio.delete_version(
            "published-delete",
            version=1,
            expected_latest_version=1,
            _agno_run_context=run_context,
        )

        assert _error_code(result) == "draft_required"
        assert result.error is not None
        assert result.error.retryable is False
        assert result.error.details == {"component_id": "published-delete", "version": 1}
        assert db.get_config("published-delete", version=1) is not None

    def test_archive_is_soft_delete_idempotent_and_reserves_id(
        self,
        studio: StudioTools,
        db: SqliteDb,
        run_context: RunContext,
    ):
        assert _create_agent(studio, run_context, component_id="archived", save_as="published").ok is True

        archived = studio.archive_agent(
            "archived",
            expected_current_version=1,
            _agno_run_context=run_context,
        )
        archived_again = studio.archive_agent(
            "archived",
            expected_current_version=1,
            _agno_run_context=run_context,
        )
        recreate = studio.create_agent(
            _agent_request(component_id="archived"),
            _agno_run_context=run_context,
        )

        assert archived.ok is True
        assert archived.status == "archived"
        assert archived_again.ok is True
        assert archived_again.status == "already_archived"
        assert _error_code(recreate) == "component_archived"
        assert db.get_component("archived") is None
        tombstone = db.get_component("archived", include_deleted=True)
        assert tombstone is not None
        assert tombstone["deleted_at"] is not None

    def test_dependency_errors_project_safe_parent_refs_without_link_metadata(
        self,
        studio: StudioTools,
        db: SqliteDb,
        run_context: RunContext,
    ):
        assert _create_agent(studio, run_context, component_id="dependency-child", save_as="published").ok
        db.create_component_with_config(
            component_id="dependency-parent",
            component_type=ComponentType.TEAM,
            name="Dependency parent",
            description=None,
            metadata=None,
            config={"name": "Dependency parent"},
            stage="published",
            links=[
                {
                    "link_kind": "member",
                    "link_key": "member_0",
                    "child_component_id": "dependency-child",
                    "child_version": 1,
                    "position": 0,
                    "meta": {"type": "agent", "api_key": MODEL_API_KEY_SECRET},
                }
            ],
        )

        result = studio.archive_agent(
            "dependency-child",
            expected_current_version=1,
            _agno_run_context=run_context,
        )

        assert _error_code(result) == "component_has_dependents"
        assert result.error is not None
        assert result.error.details == {"dependents": [{"component_id": "dependency-parent", "version": 1}]}
        assert MODEL_API_KEY_SECRET not in str(result)
        assert "meta" not in str(result)


class TestSafeViewsAndComposites:
    def test_discovery_distinguishes_latest_draft_from_current_publication(
        self,
        studio: StudioTools,
        run_context: RunContext,
    ):
        assert studio.create_agent(
            _agent_request(component_id="summary-agent", name="Published name"),
            save_as="published",
            _agno_run_context=run_context,
        ).ok
        assert studio.edit_agent(
            "summary-agent",
            AgentPatch(name="Draft name"),
            expected_version=1,
            _agno_run_context=run_context,
        ).ok

        result = studio.list_agents(_agno_run_context=run_context)

        assert result.ok
        assert result.data is not None
        summary = next(item for item in result.data if item.component_id == "summary-agent")
        assert summary.name == "Draft name"
        assert summary.latest_version == 2
        assert summary.latest_stage == "draft"
        assert summary.current_version == 1

    def test_public_reads_never_expose_raw_config_or_connection_secrets(
        self,
        studio: StudioTools,
        db: SqliteDb,
        run_context: RunContext,
    ):
        created = _create_agent(studio, run_context, component_id="safe-view", save_as="published")
        version = studio.get_version("safe-view", version=1, _agno_run_context=run_context)
        versions = studio.list_versions("safe-view", _agno_run_context=run_context)

        public_payload = json.dumps(
            {
                "created": created.model_dump(mode="json"),
                "version": version.model_dump(mode="json"),
                "versions": versions.model_dump(mode="json"),
            }
        )
        for secret in (
            db.db_file,
            MODEL_BASE_URL_SECRET,
            MODEL_API_KEY_SECRET,
            "_agno_studio",
            "db_file",
            "db_url",
        ):
            assert secret not in public_payload

        assert version.ok is True
        assert version.data is not None
        assert "config" not in version.data.model_dump()
        assert "metadata" not in version.data.model_dump()
        assert json.loads(str(version))["data"]["component_id"] == "safe-view"

        stored = db.get_config("safe-view", version=1)
        assert stored is not None
        assert "db" not in stored["config"]
        stored_payload = json.dumps(stored["config"])
        assert db.db_file not in stored_payload
        assert MODEL_BASE_URL_SECRET not in stored_payload
        assert MODEL_API_KEY_SECRET not in stored_payload

    def test_team_and_workflow_views_pin_exact_component_versions(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
    ):
        def publish_copy(value: str) -> str:
            """Publish a prepared value."""

            return value

        registry.functions.append(publish_copy)
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=_model_ref(),
            teams=True,
            workflows=True,
        )
        assert _create_agent(tool, run_context, component_id="researcher", save_as="published").ok is True

        team = tool.create_team(
            TeamCreate(
                component_id="editors",
                name="Editors",
                instructions="Edit the research.",
                members=[ComponentRef(component_type="agent", component_id="researcher")],
            ),
            _agno_run_context=run_context,
        )
        assert team.ok is True
        assert isinstance(team.data, TeamView)
        assert team.data.members == [ComponentRef(component_type="agent", component_id="researcher", version=1)]
        assert (
            tool.publish_component(
                "editors",
                version=1,
                expected_current_version=None,
                _agno_run_context=run_context,
            ).ok
            is True
        )

        workflow = tool.create_workflow(
            WorkflowCreate(
                component_id="editorial-flow",
                name="Editorial flow",
                steps=[
                    TeamWorkflowStep(kind="team", name="Review", component_id="editors"),
                    FunctionWorkflowStep(kind="function", name="Publish", function_name="publish_copy"),
                ],
            ),
            _agno_run_context=run_context,
        )

        assert workflow.ok is True
        assert isinstance(workflow.data, WorkflowView)
        assert isinstance(workflow.data.steps[0], TeamWorkflowStep)
        assert workflow.data.steps[0].version == 1
        assert workflow.data.steps[0].step_id == "review-1"
        assert workflow.data.steps[1].step_id == "publish-2"
        assert (
            tool.publish_component(
                "editorial-flow",
                version=1,
                expected_current_version=None,
                _agno_run_context=run_context,
            ).ok
            is True
        )

    def test_workflow_dispatch_preserves_two_exact_versions_of_one_agent(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
    ):
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=_model_ref(),
            workflows=True,
        )
        assert _create_agent(tool, run_context, component_id="shared-versioned-agent", save_as="published").ok
        edited = tool.edit_agent(
            "shared-versioned-agent",
            AgentPatch(tools=[ToolRef(kind="toolkit", name="calculator")]),
            expected_version=1,
            save_as="published",
            _agno_run_context=run_context,
        )
        assert edited.ok and edited.data is not None and edited.data.version == 2

        created = tool.create_workflow(
            WorkflowCreate(
                component_id="two-exact-pins",
                name="Two exact pins",
                steps=[
                    AgentWorkflowStep(
                        kind="agent",
                        step_id="old",
                        name="Old behavior",
                        component_id="shared-versioned-agent",
                        version=1,
                    ),
                    AgentWorkflowStep(
                        kind="agent",
                        step_id="new",
                        name="New behavior",
                        component_id="shared-versioned-agent",
                        version=2,
                    ),
                ],
            ),
            save_as="published",
            _agno_run_context=run_context,
        )

        assert created.ok
        assert [
            (link["link_key"], link["child_component_id"], link["child_version"])
            for link in db.get_links("two-exact-pins", 1)
        ] == [
            ("old", "shared-versioned-agent", 1),
            ("new", "shared-versioned-agent", 2),
        ]
        loaded = tool._runner_tools._load_workflow_from_db("two-exact-pins", version=1, for_dispatch=True)
        assert loaded is not None and isinstance(loaded.steps, list)
        assert [len(step.agent.tools or []) for step in loaded.steps] == [
            0,
            len(registry.tools[0].get_functions()),
        ]

    def test_parent_dispatch_does_not_mix_direct_and_nested_pin_occurrences(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
    ):
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=_model_ref(),
            teams=True,
        )
        assert _create_agent(tool, run_context, component_id="nested-shared-agent", save_as="published").ok
        nested = tool.create_team(
            TeamCreate(
                component_id="nested-version-holder",
                name="Nested version holder",
                instructions="Use the old member.",
                members=[
                    ComponentRef(component_type="agent", component_id="nested-shared-agent", version=1),
                ],
            ),
            save_as="published",
            _agno_run_context=run_context,
        )
        assert nested.ok
        edited = tool.edit_agent(
            "nested-shared-agent",
            AgentPatch(tools=[ToolRef(kind="toolkit", name="calculator")]),
            expected_version=1,
            save_as="published",
            _agno_run_context=run_context,
        )
        assert edited.ok and edited.data is not None and edited.data.version == 2
        parent = tool.create_team(
            TeamCreate(
                component_id="mixed-depth-parent",
                name="Mixed depth parent",
                instructions="Use both members.",
                members=[
                    ComponentRef(component_type="team", component_id="nested-version-holder", version=1),
                    ComponentRef(component_type="agent", component_id="nested-shared-agent", version=2),
                ],
            ),
            save_as="published",
            _agno_run_context=run_context,
        )

        assert parent.ok
        loaded = tool._runner_tools._load_team_from_db("mixed-depth-parent", version=1, for_dispatch=True)
        assert loaded is not None and isinstance(loaded.members, list)
        nested_runtime, direct_runtime = loaded.members
        assert isinstance(nested_runtime.members, list)
        assert len(nested_runtime.members[0].tools or []) == 0
        assert len(direct_runtime.tools or []) == len(registry.tools[0].get_functions())

    def test_single_function_ref_stays_narrow_while_whole_toolkit_stays_whole(
        self,
        db: SqliteDb,
        run_context: RunContext,
    ):
        from agno.agent._tools import parse_tools

        toolkit_guidance = "Use every calculator operation when the complete toolkit is attached."
        calculator = CalculatorTools(instructions=toolkit_guidance, add_instructions=True)
        registry = Registry(
            name="Exact tool registry",
            tools=[calculator],
            models=[OpenAIResponses(id=MODEL_ID)],
            dbs=[db],
        )
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=_model_ref(),
        )
        selected_ref = ToolRef(kind="function", name="add", toolkit="calculator")
        toolkit_ref = ToolRef(kind="toolkit", name="calculator")

        selected = tool.create_agent(
            AgentCreate(
                component_id="selected-calculator-function",
                name="Selected calculator function",
                instructions="Only add numbers.",
                tools=[selected_ref],
            ),
            save_as="published",
            _agno_run_context=run_context,
        )
        whole = tool.create_agent(
            AgentCreate(
                component_id="whole-calculator-toolkit",
                name="Whole calculator toolkit",
                instructions="Use any calculator operation.",
                tools=[toolkit_ref],
            ),
            save_as="published",
            _agno_run_context=run_context,
        )

        assert selected.ok and selected.data is not None
        assert whole.ok and whole.data is not None
        assert selected.data.tools == [selected_ref]
        assert whole.data.tools == [toolkit_ref]
        selected_view = tool.get_agent("selected-calculator-function", _agno_run_context=run_context)
        whole_view = tool.get_agent("whole-calculator-toolkit", _agno_run_context=run_context)
        assert selected_view.ok and selected_view.data is not None and selected_view.data.tools == [selected_ref]
        assert whole_view.ok and whole_view.data is not None and whole_view.data.tools == [toolkit_ref]

        selected_row = db.get_config("selected-calculator-function", version=1)
        whole_row = db.get_config("whole-calculator-toolkit", version=1)
        assert selected_row is not None and whole_row is not None
        selected_tools = selected_row["config"]["tools"]
        whole_tools = whole_row["config"]["tools"]
        assert [(item["toolkit"], item["name"]) for item in selected_tools] == [("calculator", "add")]
        assert {item["name"] for item in whole_tools} == set(calculator.get_functions())
        assert {item["toolkit"] for item in whole_tools} == {"calculator"}

        selected_runtime = tool._runner_tools._agent_for_run("selected-calculator-function")
        whole_runtime = tool._runner_tools._agent_for_run("whole-calculator-toolkit")
        assert isinstance(selected_runtime.tools, list)
        assert isinstance(whole_runtime.tools, list)
        selected_functions = parse_tools(selected_runtime, selected_runtime.tools, selected_runtime.model)
        whole_functions = parse_tools(whole_runtime, whole_runtime.tools, whole_runtime.model)

        assert [getattr(function, "name", None) for function in selected_functions] == ["add"]
        assert toolkit_guidance not in (selected_runtime._tool_instructions or [])
        assert {getattr(function, "name", None) for function in whole_functions} == set(calculator.get_functions())
        assert whole_runtime._tool_instructions == [toolkit_guidance]

    def test_workflow_step_identity_and_descriptions_survive_unrelated_edits(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
    ):
        def publish_copy(value: str) -> str:
            """Publish a prepared value."""

            return value

        registry.functions.append(publish_copy)
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=_model_ref(),
            teams=True,
            workflows=True,
        )
        assert _create_agent(tool, run_context, component_id="workflow-agent", save_as="published").ok
        assert tool.create_team(
            TeamCreate(
                component_id="workflow-team",
                name="Workflow team",
                instructions="Coordinate the work.",
                members=[ComponentRef(component_type="agent", component_id="workflow-agent")],
            ),
            save_as="published",
            _agno_run_context=run_context,
        ).ok

        request = WorkflowCreate(
            component_id="described-workflow",
            name="Described workflow",
            description="Original workflow description.",
            steps=[
                AgentWorkflowStep(
                    kind="agent",
                    step_id="research-step",
                    name="Research",
                    component_id="workflow-agent",
                    description="Collect the source material.",
                ),
                TeamWorkflowStep(
                    kind="team",
                    step_id="review-step",
                    name="Review",
                    component_id="workflow-team",
                    description="Review the material as a team.",
                ),
                FunctionWorkflowStep(
                    kind="function",
                    step_id="publish-step",
                    name="Publish",
                    function_name="publish_copy",
                    description="Publish the reviewed result.",
                ),
            ],
        )
        created = tool.create_workflow(
            request,
            save_as="published",
            _agno_run_context=run_context,
        )
        assert created.ok and created.data is not None
        expected_steps = [
            request.steps[0].model_copy(update={"version": 1}),
            request.steps[1].model_copy(update={"version": 1}),
            request.steps[2],
        ]
        assert created.data.steps == expected_steps

        current = tool.get_workflow("described-workflow", _agno_run_context=run_context)
        exact_v1 = tool.get_version("described-workflow", 1, _agno_run_context=run_context)
        versions_v1 = tool.list_versions("described-workflow", _agno_run_context=run_context)
        assert current.ok and current.data is not None and current.data.steps == expected_steps
        assert exact_v1.ok and isinstance(exact_v1.data, WorkflowView) and exact_v1.data.steps == expected_steps
        assert versions_v1.ok and versions_v1.data is not None
        assert [(item.version, item.stage) for item in versions_v1.data] == [(1, "published")]

        edited = tool.edit_workflow(
            "described-workflow",
            WorkflowPatch(description="Updated workflow description only."),
            expected_version=1,
            _agno_run_context=run_context,
        )
        exact_v2 = tool.get_workflow("described-workflow", version=2, _agno_run_context=run_context)
        generic_v2 = tool.get_version("described-workflow", 2, _agno_run_context=run_context)
        versions_v2 = tool.list_versions("described-workflow", _agno_run_context=run_context)

        assert edited.ok and edited.data is not None and edited.data.steps == expected_steps
        assert exact_v2.ok and exact_v2.data is not None and exact_v2.data.steps == expected_steps
        assert generic_v2.ok and isinstance(generic_v2.data, WorkflowView) and generic_v2.data.steps == expected_steps
        assert versions_v2.ok and versions_v2.data is not None
        assert sorted((item.version, item.stage) for item in versions_v2.data) == [(1, "published"), (2, "draft")]


def test_studio_lenient_internal_load_keeps_broken_reference_component_repairable(tmp_path):
    """The typed control plane retains the runner's lenient repair-load path."""

    def search(query: str) -> str:
        """Search for a query."""

        return f"results for {query}"

    db = SqliteDb(db_file=str(tmp_path / "studio-repair.db"))
    model = OpenAIChat(id="gpt-4o-mini")
    Agent(id="repair-agent", name="Repair Agent", model=model, tools=[search]).save(db=db)
    tool = StudioTools(
        registry=Registry(models=[model], dbs=[db]),
        db=db,
        authorize=_allow,
        default_model=ModelRef(id="gpt-4o-mini", provider="OpenAI", name="OpenAIChat"),
    )

    # The stored callable is intentionally absent from the registry. Reads for
    # repair remain lenient; dispatch still applies the runner's strict guard.
    loaded = tool._load_db_component("agent", "repair-agent", version=1)

    assert loaded is not None
    assert loaded.id == "repair-agent"


class TestEditPreservation:
    """Typed edits preserve omitted state and re-emit exact dependency pins."""

    def test_description_edit_preserves_typed_request_and_immutable_base(
        self,
        studio: StudioTools,
        db: SqliteDb,
        run_context: RunContext,
    ):
        request = AgentCreate(
            component_id="preserved-agent",
            name="Preserved agent",
            instructions="Use the calculator carefully.",
            model=_model_ref(),
            tools=[ToolRef(kind="function", name="add", toolkit="calculator")],
            context=ContextPolicy(include_history=True, history_runs=7, include_datetime=False),
        )
        created = studio.create_agent(request, _agno_run_context=run_context)
        assert created.ok
        version_one = db.get_config("preserved-agent", version=1)
        assert version_one is not None
        immutable_config = json.loads(json.dumps(version_one["config"]))

        edited = studio.edit_agent(
            "preserved-agent",
            AgentPatch(description="Description only."),
            expected_version=1,
            _agno_run_context=run_context,
        )

        assert edited.ok and edited.data is not None
        assert edited.data.description == "Description only."
        assert edited.data.instructions == request.instructions
        assert edited.data.model == request.model
        assert edited.data.tools == request.tools
        assert edited.data.context == request.context
        version_two = db.get_config("preserved-agent", version=2)
        assert version_two is not None
        assert version_two["config"]["_agno_studio"]["request"] == request.model_copy(
            update={"description": "Description only."}
        ).model_dump(mode="json")
        assert db.get_config("preserved-agent", version=1)["config"] == immutable_config  # type: ignore[index]

    def test_team_edit_repins_members(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
    ):
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=_model_ref(),
            teams=True,
        )
        assert _create_agent(tool, run_context, component_id="repin-member", save_as="published").ok
        created = tool.create_team(
            TeamCreate(
                component_id="repin-team",
                name="Repin team",
                instructions="Coordinate the member.",
                members=[ComponentRef(component_type="agent", component_id="repin-member", version=1)],
            ),
            _agno_run_context=run_context,
        )
        assert created.ok

        edited = tool.edit_team(
            "repin-team",
            TeamPatch(description="Description only."),
            expected_version=1,
            _agno_run_context=run_context,
        )

        assert edited.ok and edited.data is not None
        assert edited.data.members == [ComponentRef(component_type="agent", component_id="repin-member", version=1)]
        for version in (1, 2):
            links = db.get_links("repin-team", version)
            assert [(link["child_component_id"], link["child_version"]) for link in links] == [("repin-member", 1)]

    def test_workflow_edit_repins_step_members(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
    ):
        tool = StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=_model_ref(),
            workflows=True,
        )
        assert _create_agent(tool, run_context, component_id="repin-step-agent", save_as="published").ok
        step = AgentWorkflowStep(
            kind="agent",
            step_id="pinned-step",
            name="Pinned step",
            component_id="repin-step-agent",
            version=1,
        )
        created = tool.create_workflow(
            WorkflowCreate(component_id="repin-workflow", name="Repin workflow", steps=[step]),
            _agno_run_context=run_context,
        )
        assert created.ok

        edited = tool.edit_workflow(
            "repin-workflow",
            WorkflowPatch(description="Description only."),
            expected_version=1,
            _agno_run_context=run_context,
        )

        assert edited.ok and edited.data is not None
        assert edited.data.steps == [step]
        for version in (1, 2):
            links = db.get_links("repin-workflow", version)
            assert [(link["link_key"], link["child_component_id"], link["child_version"]) for link in links] == [
                ("pinned-step", "repin-step-agent", 1)
            ]


class TestScheduleControlPlane:
    @staticmethod
    def _tool(registry: Registry, db: SqliteDb, *, schedules: bool = True) -> StudioTools:
        return StudioTools(
            registry=registry,
            db=db,
            authorize=_allow,
            default_model=_model_ref(),
            schedules=schedules,
        )

    @staticmethod
    def _request(name: str = "daily-research", *, cron: str = "0 9 * * *") -> ScheduleCreate:
        return ScheduleCreate(
            name=name,
            cron=cron,
            target_type="agent",
            target_id="scheduled-agent",
            message="sk-schedule-message-secret",
            description="Daily research",
        )

    def test_create_schedule_schema_is_typed_and_descriptive(self, registry: Registry, db: SqliteDb):
        tool = self._tool(registry, db)
        function = tool.functions["create_schedule"]
        async_function = tool.async_functions["create_schedule"]

        function.process_entrypoint()
        async_function.process_entrypoint()
        schema = function.parameters
        properties = schema["properties"]
        request_schema = properties["request"]

        assert set(properties) == {"request", "if_exists"}
        assert schema["required"] == ["request"]
        assert request_schema["additionalProperties"] is False
        assert set(request_schema["required"]) == {"name", "cron", "target_type", "target_id", "message"}
        assert set(properties["if_exists"]["enum"]) == {"error", "update"}
        assert all(field.get("description") for field in request_schema["properties"].values())
        assert async_function.parameters == schema

    @pytest.mark.parametrize("actor_id", [" actor", "actor\nspoof", "josé", "a" * 256])
    def test_create_schedule_rejects_actor_ids_that_cannot_be_delegated(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
        actor_id: str,
    ):
        tool = self._tool(registry, db)
        assert _create_agent(tool, run_context, component_id="scheduled-agent", save_as="published").ok
        invalid_context = RunContext(
            run_id="invalid-actor-run",
            session_id="invalid-actor-session",
            user_id=actor_id,
        )

        result = tool.create_schedule(self._request(), _agno_run_context=invalid_context)

        assert _error_code(result) == "invalid_schedule_actor"
        assert db.get_schedule_by_name("daily-research") is None

    def test_schedule_views_are_actor_scoped_and_redact_payload_and_run_secrets(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
    ):
        tool = self._tool(registry, db)
        assert _create_agent(tool, run_context, component_id="scheduled-agent", save_as="published").ok

        created = tool.create_schedule(self._request(), _agno_run_context=run_context)
        assert created.ok is True
        assert isinstance(created.data, ScheduleView)
        schedule_id = created.data.schedule_id

        stored = ScheduleManager(db).get(schedule_id)
        assert stored is not None
        assert stored.payload == {"message": "sk-schedule-message-secret"}
        assert stored.managed_by == STUDIO_SCHEDULE_MANAGED_BY
        assert stored.owner_actor_id == run_context.user_id
        assert stored.target_type == "agent"
        assert stored.target_id == "scheduled-agent"
        assert stored.created_by_run_id == run_context.run_id
        assert stored.created_by_session_id == run_context.session_id

        db.create_schedule_run(
            {
                "id": "schedule-run-1",
                "schedule_id": schedule_id,
                "attempt": 1,
                "triggered_at": 10,
                "completed_at": 20,
                "status": "failed",
                "status_code": 500,
                "run_id": "component-run-1",
                "session_id": "component-session-1",
                "error": "sk-schedule-error-secret",
                "input": {"api_key": "sk-schedule-input-secret"},
                "output": {"token": "sk-schedule-output-secret"},
                "requirements": [{"secret": "sk-schedule-requirement-secret"}],
                "created_at": 10,
            }
        )

        listed = tool.list_schedules(_agno_run_context=run_context)
        fetched = tool.get_schedule(schedule_id, _agno_run_context=run_context)
        runs = tool.get_schedule_runs(schedule_id, _agno_run_context=run_context)

        assert listed.data == [created.data]
        assert fetched.data == created.data
        assert runs.ok is True
        assert isinstance(runs.data, list)
        assert len(runs.data) == 1
        assert isinstance(runs.data[0], ScheduleRunView)
        assert runs.data[0].has_error is True
        assert runs.data[0].has_requirements is True
        public_payload = "".join(str(result) for result in (created, listed, fetched, runs))
        for secret in (
            "sk-schedule-message-secret",
            "sk-schedule-error-secret",
            "sk-schedule-input-secret",
            "sk-schedule-output-secret",
            "sk-schedule-requirement-secret",
            "_agno_studio",
            '"payload"',
            '"input"',
            '"output"',
            '"requirements"',
            '"error"',
        ):
            assert secret not in public_payload

        other_actor = RunContext(run_id="other-run", session_id="other-session", user_id="other-actor")
        other_list = tool.list_schedules(_agno_run_context=other_actor)
        assert other_list.ok is True
        assert other_list.data == []
        assert _error_code(tool.get_schedule(schedule_id, _agno_run_context=other_actor)) == "schedule_not_found"
        assert _error_code(tool.get_schedule_runs(schedule_id, _agno_run_context=other_actor)) == "schedule_not_found"
        for operation in (
            tool.trigger_schedule,
            tool.enable_schedule,
            tool.disable_schedule,
            tool.delete_schedule,
        ):
            assert _error_code(operation(schedule_id, _agno_run_context=other_actor)) == "schedule_not_found"
        assert ScheduleManager(db).get(schedule_id) is not None

    def test_owner_update_is_in_place_but_foreign_same_name_is_never_taken_over(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
    ):
        tool = self._tool(registry, db)
        assert _create_agent(tool, run_context, component_id="scheduled-agent", save_as="published").ok

        created = tool.create_schedule(self._request(), _agno_run_context=run_context)
        assert isinstance(created.data, ScheduleView)
        conflict = tool.create_schedule(self._request(), _agno_run_context=run_context)
        updated = tool.create_schedule(
            self._request(cron="0 10 * * *"),
            if_exists="update",
            _agno_run_context=run_context,
        )

        assert _error_code(conflict) == "schedule_conflict"
        assert updated.ok is True
        assert updated.status == "updated"
        assert isinstance(updated.data, ScheduleView)
        assert updated.data.schedule_id == created.data.schedule_id
        assert updated.data.cron == "0 10 * * *"

        foreign = ScheduleManager(db).create(
            name="foreign-shared-name",
            cron="0 8 * * *",
            endpoint="/agents/scheduled-agent/runs",
            payload={
                "api_key": "sk-foreign-schedule-secret",
                "_agno_studio": {
                    "schema_version": 1,
                    "owner_actor_id": run_context.user_id,
                    "target_type": "agent",
                    "target_id": "scheduled-agent",
                },
            },
        )
        refused = tool.create_schedule(
            self._request(name="foreign-shared-name"),
            if_exists="update",
            _agno_run_context=run_context,
        )
        unchanged = ScheduleManager(db).get(foreign.id)

        assert _error_code(refused) == "schedule_name_conflict"
        assert unchanged is not None
        assert unchanged.endpoint == "/agents/scheduled-agent/runs"
        assert unchanged.payload is not None
        assert unchanged.payload["api_key"] == "sk-foreign-schedule-secret"
        assert unchanged.managed_by is None
        assert _error_code(tool.get_schedule(foreign.id, _agno_run_context=run_context)) == "schedule_not_found"
        assert "sk-foreign-schedule-secret" not in str(tool.list_schedules(_agno_run_context=run_context))

    def test_concurrent_schedule_create_is_database_unique(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        tool = self._tool(registry, db)
        assert _create_agent(tool, run_context, component_id="scheduled-agent", save_as="published").ok
        barrier = Barrier(2)
        create_record = tool._create_studio_schedule_record

        def racing_create(request: ScheduleCreate, target_id: str, context: RunContext):
            barrier.wait(timeout=5)
            return create_record(request, target_id, context)

        monkeypatch.setattr(tool, "_create_studio_schedule_record", racing_create)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: tool.create_schedule(self._request(), _agno_run_context=run_context),
                    range(2),
                )
            )

        assert sum(result.ok for result in results) == 1
        assert [_error_code(result) for result in results if not result.ok] == ["schedule_name_conflict"]
        stored = [schedule for schedule in ScheduleManager(db).list() if schedule.name == "daily-research"]
        assert len(stored) == 1

        other = ScheduleManager(db).create(
            name="other-name",
            cron="0 8 * * *",
            endpoint="/external/webhook",
        )
        with pytest.raises(ScheduleNameConflictError):
            ScheduleManager(db).update(other.id, name="daily-research")
        assert len([schedule for schedule in ScheduleManager(db).list() if schedule.name == "daily-research"]) == 1
        assert "sk-schedule-message-secret" not in caplog.text

    def test_concurrent_schedule_create_stays_conflict_after_winner_is_deleted(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
        monkeypatch: pytest.MonkeyPatch,
    ):
        tool = self._tool(registry, db)
        assert _create_agent(tool, run_context, component_id="scheduled-agent", save_as="published").ok
        barrier = Barrier(2)
        create_record = tool._create_studio_schedule_record

        def racing_create(request: ScheduleCreate, target_id: str, context: RunContext):
            barrier.wait(timeout=5)
            try:
                return create_record(request, target_id, context)
            except ScheduleNameConflictError:
                winner = db.get_schedule_by_name(request.name)
                assert winner is not None
                assert db.delete_schedule(winner["id"]) is True
                raise

        monkeypatch.setattr(tool, "_create_studio_schedule_record", racing_create)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: tool.create_schedule(self._request(), _agno_run_context=run_context),
                    range(2),
                )
            )

        assert sum(result.ok for result in results) == 1
        assert [_error_code(result) for result in results if not result.ok] == ["schedule_name_conflict"]
        assert db.get_schedule_by_name("daily-research") is None

    def test_archive_disables_owned_schedules_even_when_schedule_tools_are_hidden(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
    ):
        schedule_tool = self._tool(registry, db)
        assert _create_agent(schedule_tool, run_context, component_id="scheduled-agent", save_as="published").ok
        created = schedule_tool.create_schedule(self._request(), _agno_run_context=run_context)
        assert isinstance(created.data, ScheduleView)

        archive_tool = self._tool(registry, db, schedules=False)
        archived = archive_tool.archive_agent(
            "scheduled-agent",
            expected_current_version=1,
            _agno_run_context=run_context,
        )
        stored = ScheduleManager(db).get(created.data.schedule_id)

        assert archived.ok is True
        assert archived.status == "archived"
        assert archived.warnings == []
        assert stored is not None
        assert stored.enabled is False

    def test_schedule_create_cleans_up_when_archive_wins_after_target_validation(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
        monkeypatch: pytest.MonkeyPatch,
    ):
        tool = self._tool(registry, db)
        assert _create_agent(tool, run_context, component_id="scheduled-agent", save_as="published").ok
        create_record = tool._create_studio_schedule_record

        def create_after_archive(request: ScheduleCreate, target_id: str, context: RunContext):
            archived = tool.archive_agent(
                "scheduled-agent",
                expected_current_version=1,
                _agno_run_context=run_context,
            )
            assert archived.ok
            return create_record(request, target_id, context)

        monkeypatch.setattr(tool, "_create_studio_schedule_record", create_after_archive)
        result = tool.create_schedule(self._request(), _agno_run_context=run_context)

        assert _error_code(result) == "published_target_not_found"
        assert db.get_schedule_by_name("daily-research") is None

    def test_schedule_enable_reverts_when_archive_wins_after_target_validation(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
        monkeypatch: pytest.MonkeyPatch,
    ):
        tool = self._tool(registry, db)
        assert _create_agent(tool, run_context, component_id="scheduled-agent", save_as="published").ok
        created = tool.create_schedule(self._request(), _agno_run_context=run_context)
        assert isinstance(created.data, ScheduleView)
        assert tool.disable_schedule(created.data.schedule_id, _agno_run_context=run_context).ok
        manager = tool._schedule_manager()
        enable = manager.enable

        def enable_after_archive(schedule_id: str):
            archived = tool.archive_agent(
                "scheduled-agent",
                expected_current_version=1,
                _agno_run_context=run_context,
            )
            assert archived.ok
            return enable(schedule_id)

        monkeypatch.setattr(manager, "enable", enable_after_archive)
        result = tool.enable_schedule(created.data.schedule_id, _agno_run_context=run_context)
        stored = ScheduleManager(db).get(created.data.schedule_id)

        assert _error_code(result) == "published_target_not_found"
        assert stored is not None
        assert stored.enabled is False

    @pytest.mark.parametrize("delete_on_failure", [False, True])
    def test_schedule_revalidation_requires_the_cleanup_write_to_succeed(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
        monkeypatch: pytest.MonkeyPatch,
        delete_on_failure: bool,
    ):
        tool = self._tool(registry, db)
        assert _create_agent(tool, run_context, component_id="scheduled-agent", save_as="published").ok
        archived = tool.archive_agent(
            "scheduled-agent",
            expected_current_version=1,
            _agno_run_context=run_context,
        )
        assert archived.ok
        schedule = tool._create_studio_schedule_record(self._request(), "scheduled-agent", run_context)
        failed_cleanup = SimpleNamespace(
            delete=lambda _schedule_id: False,
            disable=lambda _schedule_id: None,
            # Official getters also use None for backend read failures. It is
            # not evidence that a failed cleanup made the schedule safe.
            get=lambda _schedule_id: None,
        )
        monkeypatch.setattr(tool, "_catalog_schedule_manager", lambda: failed_cleanup)

        with pytest.raises(RuntimeError, match="could not be cleaned up"):
            tool._revalidate_schedule_target_after_write(
                schedule,
                "agent",
                "scheduled-agent",
                delete_on_failure=delete_on_failure,
            )

        stored = ScheduleManager(db).get(schedule.id)
        assert stored is not None
        assert stored.enabled is True

    def test_archive_reports_success_with_warning_when_schedule_disable_fails(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        schedule_tool = self._tool(registry, db)
        assert _create_agent(schedule_tool, run_context, component_id="scheduled-agent", save_as="published").ok
        created = schedule_tool.create_schedule(self._request(), _agno_run_context=run_context)
        assert isinstance(created.data, ScheduleView)

        tool = self._tool(registry, db, schedules=False)
        disable_schedules = tool._disable_studio_schedules_for_target

        def fail_disable(_component_type: str, _component_id: str) -> int:
            raise RuntimeError("scheduler backend at postgres://private-scheduler")

        monkeypatch.setattr(tool, "_disable_studio_schedules_for_target", fail_disable)
        archived = tool.archive_agent(
            "scheduled-agent",
            expected_current_version=1,
            _agno_run_context=run_context,
        )

        assert archived.ok is True
        assert archived.status == "archived"
        assert archived.warnings == [
            "The component was archived, but one or more schedules could not be disabled; inspect the scheduler."
        ]
        assert "private-scheduler" not in str(archived)
        assert "private-scheduler" not in caplog.text
        assert db.get_component("scheduled-agent") is None
        assert db.get_component("scheduled-agent", include_deleted=True) is not None
        stored = ScheduleManager(db).get(created.data.schedule_id)
        assert stored is not None
        assert stored.enabled is True

        monkeypatch.setattr(tool, "_disable_studio_schedules_for_target", disable_schedules)
        retried = tool.archive_agent(
            "scheduled-agent",
            expected_current_version=1,
            _agno_run_context=run_context,
        )
        stored = ScheduleManager(db).get(created.data.schedule_id)

        assert retried.ok is True
        assert retried.status == "already_archived"
        assert retried.warnings == []
        assert stored is not None
        assert stored.enabled is False

    @pytest.mark.asyncio
    async def test_async_schedule_surface_returns_the_same_typed_results(
        self,
        registry: Registry,
        db: SqliteDb,
        run_context: RunContext,
    ):
        tool = self._tool(registry, db)
        assert _create_agent(tool, run_context, component_id="scheduled-agent", save_as="published").ok

        created = await tool.acreate_schedule(self._request(), _agno_run_context=run_context)
        assert isinstance(created.data, ScheduleView)
        schedule_id = created.data.schedule_id
        listed = await tool.alist_schedules(_agno_run_context=run_context)
        fetched = await tool.aget_schedule(schedule_id, _agno_run_context=run_context)
        disabled = await tool.adisable_schedule(schedule_id, _agno_run_context=run_context)
        enabled = await tool.aenable_schedule(schedule_id, _agno_run_context=run_context)
        triggered = await tool.atrigger_schedule(schedule_id, _agno_run_context=run_context)
        runs = await tool.aget_schedule_runs(schedule_id, _agno_run_context=run_context)
        deleted = await tool.adelete_schedule(schedule_id, _agno_run_context=run_context)

        assert isinstance(listed.data, list)
        assert isinstance(fetched.data, ScheduleView)
        for result in (disabled, enabled, triggered, deleted):
            assert result.ok is True
            assert isinstance(result.data, ScheduleActionView)
        assert runs.ok is True
        assert runs.data == []
