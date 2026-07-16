import asyncio
import json

from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.utils import resolve_team
from agno.registry import Registry
from agno.team import Team
from agno.utils.component_versioning import get_pinned_component_version
from agno.workflow import Workflow
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import get_workflow_by_id


def _approval_gate(step_input: StepInput) -> StepOutput:
    return StepOutput(content="approved")


def _finish_v1(step_input: StepInput) -> StepOutput:
    return StepOutput(content="finished-v1")


def _finish_v2(step_input: StepInput) -> StepOutput:
    return StepOutput(content="finished-v2")


def _build_versioned_hitl_workflow(db: SqliteDb, finish_executor):
    return Workflow(
        name="Versioned HITL Workflow",
        id="versioned-hitl-workflow",
        db=db,
        telemetry=False,
        steps=[
            Step(
                name="gate",
                executor=_approval_gate,
                requires_confirmation=True,
                confirmation_message="Approve execution?",
            ),
            Step(name="finish", executor=finish_executor),
        ],
    )


def test_continue_workflow_uses_pinned_version_after_new_version_saved(temp_storage_db_file):
    db = SqliteDb(db_file=temp_storage_db_file)
    registry = Registry(functions=[_approval_gate, _finish_v1, _finish_v2])

    version_1 = _build_versioned_hitl_workflow(db, _finish_v1).save(db=db)
    client = TestClient(AgentOS(db=db, registry=registry).get_app())

    start_response = client.post(
        "/workflows/versioned-hitl-workflow/runs",
        data={"message": "go", "stream": "false"},
    )
    assert start_response.status_code == 200
    start_data = start_response.json()
    assert start_data["status"] == "PAUSED"

    persisted_v1 = Workflow.load(id="versioned-hitl-workflow", db=db, registry=registry, version=version_1)
    assert persisted_v1 is not None
    paused_run = persisted_v1.get_run_output(run_id=start_data["run_id"], session_id=start_data["session_id"])
    assert paused_run is not None
    assert (
        get_pinned_component_version(
            paused_run.metadata,
            component_type="workflow",
            component_id="versioned-hitl-workflow",
        )
        == version_1
    )

    version_2 = _build_versioned_hitl_workflow(db, _finish_v2).save(db=db)
    assert version_2 > version_1
    latest_workflow = get_workflow_by_id(db=db, id="versioned-hitl-workflow", registry=registry)
    assert latest_workflow is not None
    assert latest_workflow._version == version_2

    requirements = start_data["step_requirements"]
    requirements[-1]["confirmed"] = True
    continue_response = client.post(
        f"/workflows/versioned-hitl-workflow/runs/{start_data['run_id']}/continue",
        data={
            "stream": "false",
            "session_id": start_data["session_id"],
            "step_requirements": json.dumps(requirements),
        },
    )

    assert continue_response.status_code == 200
    continue_data = continue_response.json()
    assert continue_data["status"] == "COMPLETED"
    assert "finished-v1" in (continue_data.get("content") or "")
    assert "finished-v2" not in (continue_data.get("content") or "")


def test_team_load_specific_version_preserves_saved_member_version(temp_storage_db_file):
    db = SqliteDb(db_file=temp_storage_db_file)

    version_1 = Team(
        name="Versioned Team V1",
        id="versioned-team",
        db=db,
        telemetry=False,
        members=[Agent(name="Shared Member V1", id="shared-member", telemetry=False)],
    ).save(db=db)
    version_2 = Team(
        name="Versioned Team V2",
        id="versioned-team",
        db=db,
        telemetry=False,
        members=[Agent(name="Shared Member V2", id="shared-member", telemetry=False)],
    ).save(db=db)

    loaded_v1 = Team.load(id="versioned-team", db=db, version=version_1)
    loaded_latest = Team.load(id="versioned-team", db=db)

    assert version_2 > version_1
    assert loaded_v1 is not None
    assert loaded_latest is not None
    assert loaded_v1.name == "Versioned Team V1"
    assert loaded_v1.members[0].name == "Shared Member V1"
    assert loaded_latest.name == "Versioned Team V2"
    assert loaded_latest.members[0].name == "Shared Member V2"


def test_versioned_team_resolution_preserves_saved_member_version(temp_storage_db_file):
    db = SqliteDb(db_file=temp_storage_db_file)

    version_1 = Team(
        name="Resolver Team V1",
        id="resolver-team",
        db=db,
        telemetry=False,
        members=[Agent(name="Resolver Member V1", id="resolver-member", telemetry=False)],
    ).save(db=db)
    Team(
        name="Resolver Team V2",
        id="resolver-team",
        db=db,
        telemetry=False,
        members=[Agent(name="Resolver Member V2", id="resolver-member", telemetry=False)],
    ).save(db=db)

    resolved = asyncio.run(resolve_team("resolver-team", teams=None, db=db, version=version_1))

    assert resolved is not None
    assert resolved.name == "Resolver Team V1"
    assert resolved.members[0].name == "Resolver Member V1"


def test_get_workflow_by_id_specific_version_preserves_step_agent_version(temp_storage_db_file):
    db = SqliteDb(db_file=temp_storage_db_file)

    version_1 = Workflow(
        name="Workflow Agent V1",
        id="workflow-step-agent",
        db=db,
        telemetry=False,
        steps=[Step(name="agent-step", agent=Agent(name="Step Agent V1", id="step-agent", telemetry=False))],
    ).save(db=db)
    Workflow(
        name="Workflow Agent V2",
        id="workflow-step-agent",
        db=db,
        telemetry=False,
        steps=[Step(name="agent-step", agent=Agent(name="Step Agent V2", id="step-agent", telemetry=False))],
    ).save(db=db)

    workflow_v1 = get_workflow_by_id(db=db, id="workflow-step-agent", version=version_1)
    workflow_latest = get_workflow_by_id(db=db, id="workflow-step-agent")

    assert workflow_v1 is not None
    assert workflow_latest is not None
    assert workflow_v1.steps[0].agent is not None
    assert workflow_latest.steps[0].agent is not None
    assert workflow_v1.steps[0].agent.name == "Step Agent V1"
    assert workflow_latest.steps[0].agent.name == "Step Agent V2"


def test_workflow_class_load_specific_version_preserves_step_agent_version(temp_storage_db_file):
    db = SqliteDb(db_file=temp_storage_db_file)

    version_1 = Workflow(
        name="Workflow Load Agent V1",
        id="workflow-load-agent",
        db=db,
        telemetry=False,
        steps=[Step(name="agent-step", agent=Agent(name="Load Agent V1", id="load-agent", telemetry=False))],
    ).save(db=db)
    Workflow(
        name="Workflow Load Agent V2",
        id="workflow-load-agent",
        db=db,
        telemetry=False,
        steps=[Step(name="agent-step", agent=Agent(name="Load Agent V2", id="load-agent", telemetry=False))],
    ).save(db=db)

    workflow_v1 = Workflow.load(id="workflow-load-agent", db=db, version=version_1)

    assert workflow_v1 is not None
    assert workflow_v1.steps[0].agent is not None
    assert workflow_v1.steps[0].agent.name == "Load Agent V1"


def test_workflow_load_specific_version_preserves_step_team_version(temp_storage_db_file):
    db = SqliteDb(db_file=temp_storage_db_file)

    version_1 = Workflow(
        name="Workflow Team V1",
        id="workflow-step-team",
        db=db,
        telemetry=False,
        steps=[
            Step(
                name="team-step",
                team=Team(
                    name="Step Team V1",
                    id="step-team",
                    telemetry=False,
                    members=[Agent(name="Team Member V1", id="team-member", telemetry=False)],
                ),
            )
        ],
    ).save(db=db)
    Workflow(
        name="Workflow Team V2",
        id="workflow-step-team",
        db=db,
        telemetry=False,
        steps=[
            Step(
                name="team-step",
                team=Team(
                    name="Step Team V2",
                    id="step-team",
                    telemetry=False,
                    members=[Agent(name="Team Member V2", id="team-member", telemetry=False)],
                ),
            )
        ],
    ).save(db=db)

    workflow_v1 = get_workflow_by_id(db=db, id="workflow-step-team", version=version_1)
    workflow_latest = get_workflow_by_id(db=db, id="workflow-step-team")

    assert workflow_v1 is not None
    assert workflow_latest is not None
    assert workflow_v1.steps[0].team is not None
    assert workflow_latest.steps[0].team is not None
    assert workflow_v1.steps[0].team.name == "Step Team V1"
    assert workflow_v1.steps[0].team.members[0].name == "Team Member V1"
    assert workflow_latest.steps[0].team.name == "Step Team V2"
    assert workflow_latest.steps[0].team.members[0].name == "Team Member V2"
