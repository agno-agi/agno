"""End-to-end Studio 2.9 lifecycle tests against PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.run import RunContext
from agno.tools.studio import StudioTools
from agno.tools.studio_schema import (
    AgentCreate,
    AgentPatch,
    ComponentRef,
    ModelRef,
    TeamCreate,
    TeamWorkflowStep,
    WorkflowCreate,
)

MODEL_REF = ModelRef(id="gpt-5.4", provider="OpenAI", name="OpenAIResponses")
RUN_CONTEXT = RunContext(run_id="postgres-run", session_id="postgres-session", user_id="studio-admin")


def _studio(postgres_db_real: PostgresDb, authorize=lambda *_: True) -> StudioTools:
    registry = Registry(models=[OpenAIResponses(id=MODEL_REF.id)], dbs=[postgres_db_real])
    return StudioTools(
        registry=registry,
        db=postgres_db_real,
        authorize=authorize,
        default_model=MODEL_REF,
        teams=True,
        workflows=True,
    )


def _agent(component_id: str, name: str | None = None) -> AgentCreate:
    return AgentCreate(
        component_id=component_id,
        name=name or component_id,
        instructions="Work carefully.",
    )


def test_postgres_studio_publish_edit_rollback_and_archive_are_atomic(postgres_db_real: PostgresDb) -> None:
    studio = _studio(postgres_db_real)

    created = studio.create_agent(_agent("release-agent", "Version one"), _agno_run_context=RUN_CONTEXT)
    assert created.ok and created.data is not None
    assert postgres_db_real.get_config("release-agent") is None

    published_v1 = studio.publish_component(
        "release-agent",
        version=1,
        expected_current_version=None,
        _agno_run_context=RUN_CONTEXT,
    )
    edited_v2 = studio.edit_agent(
        "release-agent",
        AgentPatch(name="Version two", description="Second release"),
        expected_version=1,
        _agno_run_context=RUN_CONTEXT,
    )
    assert published_v1.ok and edited_v2.ok
    assert studio.publish_component(
        "release-agent",
        version=2,
        expected_current_version=1,
        _agno_run_context=RUN_CONTEXT,
    ).ok

    component = postgres_db_real.get_component("release-agent")
    assert component is not None
    assert (component["current_version"], component["name"], component["description"]) == (
        2,
        "Version two",
        "Second release",
    )

    rollback = studio.set_current_version(
        "release-agent",
        version=1,
        expected_current_version=2,
        _agno_run_context=RUN_CONTEXT,
    )
    assert rollback.ok and rollback.data is not None
    component = postgres_db_real.get_component("release-agent")
    assert component is not None
    assert (component["current_version"], component["name"], component["description"]) == (
        1,
        "Version one",
        None,
    )

    stored = postgres_db_real.get_config("release-agent", version=1)
    assert stored is not None and "db" not in stored["config"]
    published_delete = studio.delete_version(
        "release-agent",
        version=2,
        expected_latest_version=2,
        _agno_run_context=RUN_CONTEXT,
    )
    assert not published_delete.ok and published_delete.error is not None
    assert published_delete.error.code == "draft_required"
    assert published_delete.error.retryable is False

    archived = studio.archive_agent(
        "release-agent",
        expected_current_version=1,
        _agno_run_context=RUN_CONTEXT,
    )
    assert archived.ok
    assert postgres_db_real.get_component("release-agent") is None
    assert postgres_db_real.get_component("release-agent", include_deleted=True) is not None


def test_postgres_studio_composites_pin_versions_and_archive_dependency_order(
    postgres_db_real: PostgresDb,
) -> None:
    studio = _studio(postgres_db_real)
    assert studio.create_agent(
        _agent("researcher"),
        save_as="published",
        _agno_run_context=RUN_CONTEXT,
    ).ok
    team = studio.create_team(
        TeamCreate(
            component_id="editors",
            name="Editors",
            instructions="Edit the result.",
            members=[ComponentRef(component_type="agent", component_id="researcher")],
        ),
        save_as="published",
        _agno_run_context=RUN_CONTEXT,
    )
    assert team.ok and team.data is not None
    assert team.data.members[0].version == 1

    workflow = studio.create_workflow(
        WorkflowCreate(
            component_id="editorial-flow",
            name="Editorial flow",
            steps=[TeamWorkflowStep(kind="team", name="Review", component_id="editors")],
        ),
        save_as="published",
        _agno_run_context=RUN_CONTEXT,
    )
    assert workflow.ok and workflow.data is not None
    assert workflow.data.steps[0].version == 1

    blocked = studio.archive_agent(
        "researcher",
        expected_current_version=1,
        _agno_run_context=RUN_CONTEXT,
    )
    assert not blocked.ok and blocked.error is not None
    assert blocked.error.code == "component_has_dependents"

    assert studio.archive_workflow(
        "editorial-flow",
        expected_current_version=1,
        _agno_run_context=RUN_CONTEXT,
    ).ok
    assert studio.archive_team(
        "editors",
        expected_current_version=1,
        _agno_run_context=RUN_CONTEXT,
    ).ok
    assert studio.archive_agent(
        "researcher",
        expected_current_version=1,
        _agno_run_context=RUN_CONTEXT,
    ).ok


def test_postgres_studio_concurrent_identical_retries_create_once(postgres_db_real: PostgresDb) -> None:
    ready = Barrier(2)

    def authorize(_context: RunContext, _access: str, action: str) -> bool:
        if action == "create_agent":
            ready.wait()
        return True

    studio = _studio(postgres_db_real, authorize=authorize)
    request = _agent("concurrent-agent")

    def create() -> str:
        result = studio.create_agent(
            request,
            if_exists="return_existing",
            _agno_run_context=RUN_CONTEXT,
        )
        assert result.ok
        return result.status

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _index: create(), range(2)))

    assert sorted(statuses) == ["created", "existing"]
    assert [row["version"] for row in postgres_db_real.list_configs("concurrent-agent")] == [1]
