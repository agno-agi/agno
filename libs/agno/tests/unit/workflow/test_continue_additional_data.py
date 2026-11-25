"""Run-scoped step data must survive human review and storage reload."""

import pytest

from agno.db.json import JsonDb
from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus
from agno.run.workflow import WorkflowRunOutput
from agno.workflow import HumanReview, Step, StepInput, StepOutput, Workflow


@pytest.fixture(params=["json", "sqlite"])
def workflow_factory(tmp_path, request):
    received = []

    def schedule(step_input: StepInput) -> StepOutput:
        received.append(step_input.additional_data)
        room = (step_input.additional_data or {}).get("room", "Main Conference Room")
        return StepOutput(content=f"{step_input.input} | {room}")

    def create():
        return Workflow(
            id="planning",
            db=JsonDb(db_path=str(tmp_path))
            if request.param == "json"
            else SqliteDb(db_file=str(tmp_path / "workflow.db")),
            steps=[
                Step(name="Draft", executor=schedule, human_review=HumanReview(requires_output_review=True)),
                Step(name="Schedule", executor=schedule),
            ],
            telemetry=False,
        )

    return create, received


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("reload", [False, True])
def test_continue_preserves_additional_data(workflow_factory, stream, reload):
    create, received = workflow_factory
    workflow = create()
    data = {"room": "Boardroom 204", "attendees": ["Ada", "Lin"]}
    run = workflow.run("Weekly planning", session_id="session", additional_data=data, stream=stream)
    if stream:
        list(run)
        run = workflow.get_last_run_output(session_id="session")
    assert run.is_paused
    assert received == [data]
    run.active_step_requirements[0].confirm()
    if reload:
        workflow = create()
        result = workflow.continue_run(
            run_id=run.run_id, session_id="session", step_requirements=run.step_requirements, stream=stream
        )
    else:
        result = workflow.continue_run(run, stream=stream)
    if stream:
        list(result)
        result = workflow.get_last_run_output(session_id="session")
    assert result.status == RunStatus.completed
    assert received == [data, data]
    assert result.content == "Weekly planning | Boardroom 204"


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("reload", [False, True])
async def test_acontinue_preserves_additional_data(workflow_factory, stream, reload):
    create, received = workflow_factory
    workflow = create()
    data = {"room": "Boardroom 204", "attendees": ["Ada", "Lin"]}
    run = workflow.arun("Weekly planning", session_id="session", additional_data=data, stream=stream)
    if not stream:
        run = await run
    if stream:
        async for _ in run:
            pass
        run = await workflow.aget_last_run_output(session_id="session")
    assert run.is_paused
    assert received == [data]
    run.active_step_requirements[0].confirm()
    if reload:
        workflow = create()
        result = await workflow.acontinue_run(
            run_id=run.run_id, session_id="session", step_requirements=run.step_requirements, stream=stream
        )
    else:
        result = await workflow.acontinue_run(run, stream=stream)
    if stream:
        async for _ in result:
            pass
        result = await workflow.aget_last_run_output(session_id="session")
    assert result.status == RunStatus.completed
    assert received == [data, data]
    assert result.content == "Weekly planning | Boardroom 204"


@pytest.mark.parametrize("data", [None, {}, {"room": "Boardroom 204", "attendees": ["Ada", "Lin"]}])
def test_run_additional_data_roundtrip(data):
    import json

    run = WorkflowRunOutput(additional_data=data)
    restored = WorkflowRunOutput.from_dict(json.loads(json.dumps(run.to_dict())))
    assert restored.additional_data == data


def test_legacy_run_without_additional_data():
    run = WorkflowRunOutput.from_dict({"run_id": "legacy", "status": "PAUSED"})
    assert run.additional_data is None
