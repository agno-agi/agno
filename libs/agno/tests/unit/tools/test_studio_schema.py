"""Tests for Studio's typed public request and response contract."""

import json
from typing import Literal

import pytest
from pydantic import TypeAdapter, ValidationError

import agno.tools.studio_schema as studio_schema
from agno.tools.function import Function
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
    ContextPolicyPatch,
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
    WorkflowView,
)


def _model() -> ModelRef:
    return ModelRef(id="gpt-5", provider="OpenAI", name="OpenAIResponses")


def _context() -> ContextPolicy:
    return ContextPolicy()


def _contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def _agent_view() -> AgentView:
    return AgentView(
        component_id="researcher",
        name="Researcher",
        instructions="Research the topic.",
        model=_model(),
        context=_context(),
        version=1,
        stage="draft",
        is_current=False,
        source="studio",
    )


def test_schema_models_are_strict_and_forbid_extra_fields():
    with pytest.raises(ValidationError, match="Input should be a valid string"):
        ModelRef(id=5)  # type: ignore[arg-type]

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ModelRef(id="gpt-5", unknown=True)  # type: ignore[call-arg]


def test_tool_ref_supports_whole_toolkits_and_qualified_functions():
    whole_toolkit = ToolRef(kind="toolkit", name="calculator")
    top_level_function = ToolRef(kind="function", name="search")
    toolkit_function = ToolRef(kind="function", name="add", toolkit="calculator")

    assert whole_toolkit.toolkit is None
    assert top_level_function.toolkit is None
    assert toolkit_function.toolkit == "calculator"

    with pytest.raises(ValidationError, match="only valid when kind='function'"):
        ToolRef(kind="toolkit", name="calculator", toolkit="calculator")


def test_function_ref_is_a_strict_copyable_discovery_projection():
    function = FunctionRef(name="publish_article", description="Publish an article.")

    assert function.model_dump() == {"name": "publish_article", "description": "Publish an article."}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FunctionRef(name="publish_article", signature="()")  # type: ignore[call-arg]


def test_context_policy_rejects_history_depth_when_history_is_disabled():
    with pytest.raises(ValidationError, match="history_runs.*disabled"):
        ContextPolicy(include_history=False, history_runs=2)

    assert ContextPolicy(include_history=False).history_runs is None


def test_agent_create_has_safe_defaults_and_independent_tool_lists():
    first = AgentCreate(name="Researcher", instructions="Research the topic.")
    second = AgentCreate(name="Writer", instructions="Write the answer.")

    first.tools.append(ToolRef(kind="toolkit", name="web"))

    assert first.component_id is None
    assert first.context is None
    assert second.tools == []

    explicit_context = AgentCreate(
        name="Reviewer",
        instructions="Review the answer.",
        context=ContextPolicy(include_history=False),
    )
    assert explicit_context.context == ContextPolicy(include_history=False)


@pytest.mark.parametrize("component_id", [" ", "../escape", "foo/bar", "foo%2Fbar", "café"])
def test_component_ids_are_path_safe(component_id: str):
    with pytest.raises(ValidationError):
        AgentCreate(component_id=component_id, name="Agent", instructions="Work.")
    with pytest.raises(ValidationError):
        ComponentRef(component_type="agent", component_id=component_id)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: AgentCreate(name="   ", instructions="Work."),
        lambda: AgentCreate(name="Agent", instructions="\n\t"),
        lambda: TeamCreate(
            name=" ",
            instructions="Coordinate.",
            members=[ComponentRef(component_type="agent", component_id="member")],
        ),
        lambda: WorkflowCreate(
            name="Workflow",
            steps=[AgentWorkflowStep(kind="agent", name=" ", component_id="member")],
        ),
    ],
)
def test_public_names_and_instructions_must_be_nonblank(factory):
    with pytest.raises(ValidationError, match="non-whitespace"):
        factory()


def test_agent_create_generates_descriptive_nested_tool_schema():
    def create_agent(
        request: AgentCreate,
        save_as: Literal["draft", "published"] = "draft",
    ) -> str:
        return request.name + save_as

    function = Function.from_callable(create_agent)
    request_schema = function.parameters["properties"]["request"]

    assert request_schema["additionalProperties"] is False
    assert request_schema["required"] == ["name", "instructions"]
    assert request_schema["properties"]["component_id"]["description"].startswith("Stable path-safe component id")
    assert all(property_schema.get("description") for property_schema in request_schema["properties"].values())
    assert request_schema["properties"]["model"]["anyOf"][0]["properties"]["id"]["description"].startswith(
        "Exact model id"
    )


def test_agent_patch_distinguishes_omission_null_and_empty_list():
    description_patch = AgentPatch(description=None)
    model_patch = AgentPatch(model=None)
    tools_patch = AgentPatch(tools=[])

    assert description_patch.model_dump(exclude_unset=True) == {"description": None}
    assert model_patch.model_dump(exclude_unset=True) == {"model": None}
    assert tools_patch.model_dump(exclude_unset=True) == {"tools": []}

    with pytest.raises(ValidationError, match="at least one field"):
        AgentPatch()
    with pytest.raises(ValidationError, match="'instructions' cannot be set to null"):
        AgentPatch(instructions=None)
    with pytest.raises(ValidationError, match="'tools' cannot be set to null"):
        AgentPatch(tools=None)


def test_context_patch_is_omission_aware():
    reset_depth = ContextPolicyPatch(history_runs=None)
    assert reset_depth.model_dump(exclude_unset=True) == {"history_runs": None}

    with pytest.raises(ValidationError, match="at least one field"):
        ContextPolicyPatch()
    with pytest.raises(ValidationError, match="'include_datetime' cannot be set to null"):
        ContextPolicyPatch(include_datetime=None)
    with pytest.raises(ValidationError, match="history_runs.*disabled"):
        ContextPolicyPatch(include_history=False, history_runs=2)


def test_team_models_use_typed_versioned_member_refs():
    member = ComponentRef(component_type="agent", component_id="researcher", version=2)
    request = TeamCreate(
        name="Editorial team",
        instructions="Research and write.",
        members=[member],
    )

    assert request.members == [member]
    assert request.context is None

    with pytest.raises(ValidationError):
        TeamCreate(name="Empty team", instructions="Coordinate.", members=[])
    with pytest.raises(ValidationError):
        ComponentRef(component_type="workflow", component_id="pipeline")  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="at least one field"):
        TeamPatch()
    with pytest.raises(ValidationError):
        TeamPatch(members=[])
    with pytest.raises(ValidationError, match="unique component_id.*shared"):
        TeamCreate(
            name="Ambiguous team",
            instructions="Coordinate.",
            members=[
                ComponentRef(component_type="agent", component_id="shared", version=1),
                ComponentRef(component_type="team", component_id="shared", version=2),
            ],
        )
    with pytest.raises(ValidationError, match="unique component_id.*researcher"):
        TeamPatch(
            members=[
                ComponentRef(component_type="agent", component_id="researcher", version=1),
                ComponentRef(component_type="agent", component_id="researcher", version=2),
            ]
        )


def test_workflow_steps_are_discriminated_and_round_trip_without_null_executors():
    workflow = WorkflowCreate.model_validate(
        {
            "name": "Editorial workflow",
            "steps": [
                {
                    "kind": "agent",
                    "step_id": "research",
                    "name": "Research",
                    "component_id": "researcher",
                    "version": 2,
                },
                {"kind": "team", "step_id": "edit", "name": "Edit", "component_id": "editors"},
                {
                    "kind": "function",
                    "step_id": "publish",
                    "name": "Publish",
                    "function_name": "publish_article",
                },
            ],
        }
    )

    assert isinstance(workflow.steps[0], AgentWorkflowStep)
    assert isinstance(workflow.steps[1], TeamWorkflowStep)
    assert isinstance(workflow.steps[2], FunctionWorkflowStep)
    assert workflow.model_dump()["steps"][1] == {
        "kind": "team",
        "step_id": "edit",
        "name": "Edit",
        "component_id": "editors",
        "version": None,
        "description": None,
    }

    items_schema = WorkflowCreate.model_json_schema()["properties"]["steps"]["items"]
    assert items_schema["discriminator"]["propertyName"] == "kind"
    assert len(items_schema["oneOf"]) == 3

    with pytest.raises(ValidationError, match="Unable to extract tag"):
        WorkflowCreate(name="Broken", steps=[{"name": "Step", "component_id": "agent"}])
    with pytest.raises(ValidationError):
        WorkflowCreate(name="Empty", steps=[])
    with pytest.raises(ValidationError):
        AgentWorkflowStep(kind="agent", step_id="", name="Step", component_id="agent")


def test_workflow_create_function_schema_inlines_discriminated_steps():
    def create_workflow(request: WorkflowCreate) -> str:
        return request.name

    function = Function.from_callable(create_workflow)
    request_schema = function.parameters["properties"]["request"]
    items_schema = request_schema["properties"]["steps"]["items"]

    assert not _contains_key(request_schema, "$defs")
    assert not _contains_key(request_schema, "$ref")
    assert items_schema["discriminator"] == {"propertyName": "kind"}
    assert {branch["properties"]["kind"]["const"] for branch in items_schema["oneOf"]} == {
        "agent",
        "team",
        "function",
    }
    for branch in items_schema["oneOf"]:
        assert all(property_schema.get("description") for property_schema in branch["properties"].values())


def test_workflow_patch_distinguishes_clearable_description_from_required_steps():
    assert WorkflowPatch(description=None).model_dump(exclude_unset=True) == {"description": None}

    with pytest.raises(ValidationError, match="at least one field"):
        WorkflowPatch()
    with pytest.raises(ValidationError, match="'steps' cannot be set to null"):
        WorkflowPatch(steps=None)
    with pytest.raises(ValidationError):
        WorkflowPatch(steps=[])


def test_views_are_typed_safe_projections():
    agent = _agent_view()
    team = TeamView(
        component_id="editorial-team",
        name="Editorial team",
        instructions="Research and write.",
        members=[ComponentRef(component_type="agent", component_id=agent.component_id, version=agent.version)],
        model=_model(),
        context=_context(),
        version=1,
        stage="published",
        is_current=True,
        source="studio",
    )
    workflow = WorkflowView(
        component_id="editorial-workflow",
        name="Editorial workflow",
        steps=[AgentWorkflowStep(kind="agent", name="Research", component_id=agent.component_id, version=1)],
        version=1,
        stage="published",
        is_current=True,
        source="studio",
    )

    assert agent.component_type == "agent"
    assert team.component_type == "team"
    assert workflow.component_type == "workflow"


def test_component_support_views_are_strict_and_version_aware():
    code_summary = ComponentSummary(
        component_id=None,
        component_type="agent",
        name="Code agent",
        source="code",
        latest_version=None,
        latest_stage="code",
        current_version=None,
    )
    stored_summary = ComponentSummary(
        component_id="researcher",
        component_type="agent",
        name="Researcher",
        source="studio",
        latest_version=2,
        latest_stage="draft",
        current_version=1,
    )
    version = VersionSummary(
        version=1,
        stage="published",
        label="stable",
        is_current=True,
        created_at=1,
    )
    action = ComponentActionView(component_id="researcher", component_type="agent", version=2)

    assert code_summary.component_id is None
    assert stored_summary.latest_version == 2
    assert stored_summary.current_version == 1
    assert version.updated_at is None
    assert action.model_dump() == {"component_id": "researcher", "component_type": "agent", "version": 2}

    with pytest.raises(ValidationError):
        VersionSummary(version=0, stage="draft", label=None, is_current=False)
    with pytest.raises(ValidationError):
        ComponentActionView(component_id="researcher", component_type="function")  # type: ignore[arg-type]


def test_component_view_union_discriminates_safe_views():
    adapter = TypeAdapter(ComponentView)

    agent = adapter.validate_python(_agent_view().model_dump())
    workflow = adapter.validate_python(
        WorkflowView(
            component_id="pipeline",
            name="Pipeline",
            version=1,
            stage="published",
            is_current=True,
            source="studio",
        ).model_dump()
    )

    assert isinstance(agent, AgentView)
    assert isinstance(workflow, WorkflowView)
    schema = adapter.json_schema()
    assert schema["discriminator"]["propertyName"] == "component_type"


def test_studio_result_requires_exactly_one_coherent_data_or_error():
    success = StudioResult[AgentView](ok=True, status="created", data=_agent_view())
    failure = StudioResult[AgentView](
        ok=False,
        status="error",
        error=StudioError(code="component_conflict", message="The component changed."),
    )

    assert success.data is not None
    assert failure.error is not None

    with pytest.raises(ValidationError, match="exactly one"):
        StudioResult[AgentView](ok=True, status="created")
    with pytest.raises(ValidationError, match="exactly one"):
        StudioResult[AgentView](
            ok=True,
            status="created",
            data=_agent_view(),
            error=StudioError(code="unexpected", message="Unexpected."),
        )
    with pytest.raises(ValidationError, match="'ok' must be true"):
        StudioResult[AgentView](ok=False, status="created", data=_agent_view())


def test_studio_result_string_is_valid_json_and_excludes_none():
    success = StudioResult[AgentView](ok=True, status="created", data=_agent_view())
    failure = StudioResult[AgentView](
        ok=False,
        status="error",
        error=StudioError(code="not_found", message="Component not found."),
    )

    success_json = json.loads(str(success))
    failure_json = json.loads(str(failure))

    assert success_json["data"]["component_id"] == "researcher"
    assert "error" not in success_json
    assert failure_json["error"]["code"] == "not_found"
    assert "data" not in failure_json


def test_result_and_view_collection_defaults_are_not_shared():
    first = StudioResult[AgentView](ok=True, status="created", data=_agent_view())
    second = StudioResult[AgentView](ok=True, status="created", data=_agent_view())
    first.warnings.append("warning")

    assert second.warnings == []


def test_schedule_models_are_typed_safe_and_publicly_exported():
    request = ScheduleCreate(
        name="Daily research",
        cron="0 9 * * *",
        target_type="agent",
        target_id="researcher",
        message="Research the latest topic.",
    )
    view = ScheduleView(
        schedule_id="schedule-1",
        name=request.name,
        cron=request.cron,
        target_type=request.target_type,
        target_id=request.target_id,
        timezone=request.timezone,
        enabled=True,
        owner_actor_id="studio-admin",
    )
    run = ScheduleRunView(
        schedule_run_id="schedule-run-1",
        schedule_id=view.schedule_id,
        attempt=1,
        status="failed",
        has_error=True,
        has_requirements=True,
    )
    action = ScheduleActionView(
        schedule_id=view.schedule_id,
        name=view.name,
        target_type=view.target_type,
        target_id=view.target_id,
        enabled=False,
    )

    assert request.timezone == "UTC"
    assert view.model_dump().keys().isdisjoint({"payload", "message", "endpoint", "method"})
    assert run.model_dump().keys().isdisjoint({"input", "output", "error", "requirements"})
    assert action.enabled is False
    assert {
        "ScheduleActionView",
        "ScheduleCreate",
        "ScheduleRunView",
        "ScheduleTargetType",
        "ScheduleView",
    }.issubset(studio_schema.__all__)

    request_schema = ScheduleCreate.model_json_schema()
    assert request_schema["additionalProperties"] is False
    assert all(field.get("description") for field in request_schema["properties"].values())

    with pytest.raises(ValidationError, match="non-whitespace"):
        ScheduleCreate(
            name="Daily research",
            cron="0 9 * * *",
            target_type="agent",
            target_id="researcher",
            message="   ",
        )
    with pytest.raises(ValidationError, match="Extra inputs"):
        ScheduleView(
            schedule_id="schedule-1",
            name="Daily research",
            cron="0 9 * * *",
            target_type="agent",
            target_id="researcher",
            timezone="UTC",
            enabled=True,
            owner_actor_id="studio-admin",
            payload={"secret": "hidden"},
        )
