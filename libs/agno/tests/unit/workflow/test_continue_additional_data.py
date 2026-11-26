"""Run-scoped step data must survive human review and storage reload."""

import asyncio

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


@pytest.mark.parametrize("background", [False, True])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("reload", [False, True])
async def test_acontinue_preserves_additional_data(workflow_factory, stream, reload, background):
    create, received = workflow_factory
    workflow = create()
    data = {"room": "Boardroom 204", "attendees": ["Ada", "Lin"]}
    run = workflow.arun(
        "Weekly planning", session_id="session", additional_data=data, stream=stream, background=background
    )
    if not stream:
        run = await run
        if background:
            from agno.workflow.workflow import _workflow_background_tasks

            tasks = [task for task in _workflow_background_tasks if run.run_id in task.get_name()]
            assert len(tasks) == 1
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
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


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("review", ["input", "retry"])
@pytest.mark.parametrize("data", [None, {}, {"room": "Boardroom 204"}])
async def test_review_data_does_not_mutate_run_data(tmp_path, async_mode, stream, review, data):
    received = []

    def execute(step_input: StepInput) -> StepOutput:
        received.append(dict(step_input.additional_data or {}))
        return StepOutput(content="draft")

    def create():
        return Workflow(
            id="review-data",
            db=JsonDb(db_path=str(tmp_path)),
            steps=[
                Step(
                    name="Review",
                    executor=execute,
                    human_review=HumanReview(
                        requires_user_input=review == "input",
                        user_input_schema=[{"name": "preference", "field_type": "str"}] if review == "input" else None,
                        requires_output_review=review == "retry",
                        on_reject="retry",
                    ),
                ),
                Step(name="Final", executor=execute),
            ],
            telemetry=False,
        )

    workflow = create()
    if async_mode:
        run = workflow.arun("input", session_id="review-session", additional_data=data)
        run = await run
    else:
        run = workflow.run("input", session_id="review-session", additional_data=data)
    assert run.is_paused
    requirement = run.active_step_requirements[0]
    if review == "input":
        requirement.set_user_input(preference="fast")
    else:
        requirement.reject(feedback="Revise this")
    workflow = create()
    params = dict(
        run_id=run.run_id, session_id="review-session", step_requirements=run.step_requirements, stream=stream
    )
    result = await workflow.acontinue_run(**params) if async_mode else workflow.continue_run(**params)
    if stream:
        if async_mode:
            async for _ in result:
                pass
        else:
            list(result)
        result = workflow.get_last_run_output(session_id="review-session")
    expected = (
        {**(data or {}), "user_input": {"preference": "fast"}}
        if review == "input"
        else {**(data or {}), "rejection_feedback": "Revise this", "previous_output": "draft"}
    )
    assert received[-1 if review == "retry" else 0] == expected
    assert result.additional_data == data
    restored = create().get_run_output(run.run_id, session_id="review-session")
    assert restored.additional_data == data
    if review == "retry":
        assert result.is_paused
        result.active_step_requirements[0].confirm()
        workflow = create()
        params = dict(run_id=result.run_id, session_id="review-session", step_requirements=result.step_requirements)
        result = await workflow.acontinue_run(**params) if async_mode else workflow.continue_run(**params)
    assert result.status == RunStatus.completed
    assert received[-1] == (data or {})
    assert result.additional_data == data
