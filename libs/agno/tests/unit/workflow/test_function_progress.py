import pytest

from agno.db.in_memory import InMemoryDb
from agno.run.workflow import StepProgressEvent, WorkflowCompletedEvent, workflow_run_output_event_from_dict
from agno.workflow import Workflow
from agno.workflow.step import Step
from agno.workflow.types import StepOutput, StepProgress


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("async_executor", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_function_progress_has_native_identity_and_does_not_pollute_output(asynchronous, async_executor, stream):
    if async_executor and not asynchronous:
        pytest.skip("sync execution deliberately rejects async executors")
    attempts = []

    def work(step_input):
        attempts.append(1)
        yield StepProgress(content="Indexed one page", data={"processed": 1})
        yield StepOutput(content="final result")

    async def awork(step_input):
        for event in work(step_input):
            yield event

    workflow = Workflow(
        id="index",
        steps=[Step(name="sync", executor=awork if async_executor else work)],
        db=InMemoryDb(),
        store_events=True,
        telemetry=False,
    )
    if stream:
        kwargs = dict(input="go", session_id="session", stream=True, stream_events=True, stream_executor_events=False)
        events = [event async for event in workflow.arun(**kwargs)] if asynchronous else list(workflow.run(**kwargs))
        progress = [event for event in events if isinstance(event, StepProgressEvent)]
        assert len(progress) == 1
        event = progress[0]
        completed = next(event for event in events if isinstance(event, WorkflowCompletedEvent))
        assert event.run_id == completed.run_id and event.workflow_id == "index" and event.session_id == "session"
        assert event.step_id and event.step_name == "sync" and event.attempt == 1
        assert workflow_run_output_event_from_dict(event.to_dict()) == event
        assert len(completed.step_results) == 1 and completed.step_results[0].content == "final result"
        assert all(type(event).__module__ != "agno.run.agent" for event in events)
    else:
        output = await workflow.arun("go") if asynchronous else workflow.run("go")
        assert output.content == "final result" and "Indexed one page" not in str(output.content)
    assert len(attempts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_progress_identifies_retry_attempt_without_another_executor_run(asynchronous):
    attempts = []

    def work(step_input):
        attempts.append(1)
        yield StepProgress(content="working")
        if len(attempts) == 1:
            raise RuntimeError("temporary failure")
        yield StepOutput(content="finished")

    workflow = Workflow(id="retry", steps=[Step(name="sync", executor=work, max_retries=1)], telemetry=False)
    kwargs = dict(input="go", stream=True, stream_events=True)
    events = [e async for e in workflow.arun(**kwargs)] if asynchronous else list(workflow.run(**kwargs))
    progress = [e for e in events if isinstance(e, StepProgressEvent)]
    assert [e.attempt for e in progress] == [1, 2]
    assert len({(e.run_id, e.step_id) for e in progress}) == 1
    completed = next(e for e in events if isinstance(e, WorkflowCompletedEvent))
    assert len(completed.step_results) == 1
