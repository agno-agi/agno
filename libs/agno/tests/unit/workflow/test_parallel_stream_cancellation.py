"""Async Parallel must propagate cancellation and retire its producer tasks."""

import asyncio

import pytest

from agno.db.sqlite import SqliteDb
from agno.exceptions import RunCancelledException
from agno.run.agent import RunContentEvent
from agno.run.base import RunStatus
from agno.run.workflow import WorkflowCancelledEvent, WorkflowCompletedEvent
from agno.workflow import Step, Workflow
from agno.workflow.loop import Loop
from agno.workflow.parallel import Parallel
from agno.workflow.step import UnresolvableCallableError
from agno.workflow.types import StepInput, StepOutput


@pytest.mark.asyncio
@pytest.mark.parametrize("stream_events", [False, True])
@pytest.mark.parametrize("cancel", [False, True])
async def test_parallel_loop_stream_cancellation(stream_events, cancel):
    entered = [asyncio.Event(), asyncio.Event()]
    release = asyncio.Event()
    progress_seen = asyncio.Event()
    producers = set()
    calls = [0, 0]

    def make_loop(index):
        async def executor(step_input):
            producers.add(asyncio.current_task())
            calls[index] += 1
            if calls[index] == 1:
                yield RunContentEvent(content=f"progress-{index}")
                entered[index].set()
                await release.wait()
            yield StepOutput(content=f"result-{index}")

        return Loop(name=f"loop-{index}", steps=[Step(name=f"step-{index}", executor=executor)], max_iterations=2)

    workflow = Workflow(steps=[Parallel(make_loop(0), make_loop(1))], telemetry=False)
    events = []

    async def consume():
        async for event in workflow.arun("test", run_id="parallel-cancel", stream=True, stream_events=stream_events):
            events.append(event)
            if isinstance(event, RunContentEvent):
                progress_seen.set()

    consumer = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered), progress_seen.wait()), 2)
        if cancel:
            assert await workflow.acancel_run("parallel-cancel")
        release.set()
        await asyncio.wait_for(asyncio.shield(consumer), 2)
        completed = [event for event in events if isinstance(event, WorkflowCompletedEvent)]
        assert len(completed) == 1
        assert completed[0].run_output.status == (RunStatus.cancelled if cancel else RunStatus.completed)
        assert len([event for event in events if isinstance(event, WorkflowCancelledEvent)]) == int(cancel)
        assert calls == ([1, 1] if cancel else [2, 2])
        assert all(task.done() for task in producers)
        if cancel:
            assert any("progress-" in str(result.content) for result in completed[0].step_results)
    finally:
        consumer.cancel()
        for task in producers:
            task.cancel()
        await asyncio.gather(consumer, *producers, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("exception_type", [RunCancelledException, UnresolvableCallableError])
async def test_parallel_terminal_error_cleans_up_sibling(exception_type):
    sibling_started = asyncio.Event()
    sibling_closed = asyncio.Event()
    producers = set()

    async def waiting(step_input):
        producers.add(asyncio.current_task())
        try:
            sibling_started.set()
            await asyncio.Event().wait()
        finally:
            sibling_closed.set()

    async def failing(step_input):
        producers.add(asyncio.current_task())
        await sibling_started.wait()
        raise exception_type("stop parallel")

    parallel = Parallel(Step(name="waiting", executor=waiting), Step(name="failing", executor=failing, max_retries=0))

    async def consume():
        return [event async for event in parallel.aexecute_stream(StepInput(input="test"))]

    consumer = asyncio.create_task(consume())
    try:
        with pytest.raises(exception_type, match="stop parallel"):
            await asyncio.wait_for(asyncio.shield(consumer), 2)
        assert sibling_closed.is_set()
        assert all(task.done() for task in producers)
    finally:
        consumer.cancel()
        for task in producers:
            task.cancel()
        await asyncio.gather(consumer, *producers, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("close_stream", [False, True])
async def test_parallel_consumer_exit_cleans_up_producer(close_stream):
    started = asyncio.Event()
    closed = asyncio.Event()
    producers = set()

    async def executor(step_input):
        producers.add(asyncio.current_task())
        try:
            yield RunContentEvent(content="started")
            started.set()
            await asyncio.Event().wait()
        finally:
            closed.set()

    stream = Parallel(Step(name="waiting", executor=executor)).aexecute_stream(StepInput(input="test"))
    consumer = None
    try:
        await asyncio.wait_for(stream.__anext__(), 2)
        await asyncio.wait_for(started.wait(), 2)
        if close_stream:
            await stream.aclose()
        else:
            consumer = asyncio.create_task(stream.__anext__())
            # Ensure cancellation lands inside the generator's next iteration.
            await asyncio.sleep(0)
            consumer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await consumer
        assert closed.is_set()
        assert all(task.done() for task in producers)
    finally:
        if consumer:
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)
        await stream.aclose()
        for task in producers:
            task.cancel()
        await asyncio.gather(*producers, return_exceptions=True)


@pytest.mark.asyncio
async def test_parallel_ordinary_error_keeps_successful_result():
    async def success(step_input):
        return StepOutput(content="successful result")

    async def failure(step_input):
        raise ValueError("ordinary failure")

    parallel = Parallel(Step(name="success", executor=success), Step(name="failure", executor=failure, max_retries=0))
    events = [event async for event in parallel.aexecute_stream(StepInput(input="test"))]
    result = events[-1]
    assert isinstance(result, StepOutput)
    assert result.success is False
    assert len(result.steps) == 2
    assert any(step.content == "successful result" and step.success for step in result.steps)
    assert any(step.error == "ordinary failure" and not step.success for step in result.steps)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream_events", [False, True])
async def test_parallel_cancel_retains_completed_branch(stream_events, tmp_path):
    completed = asyncio.Event()
    waiting = asyncio.Event()
    release = asyncio.Event()
    sibling_closed = asyncio.Event()
    producers = {}

    async def success(step_input):
        producers["success"] = asyncio.current_task()
        completed.set()
        return StepOutput(content="completed before cancellation")

    async def loop_step(step_input):
        producers["loop"] = asyncio.current_task()
        await release.wait()
        return StepOutput(content="loop iteration")

    async def sibling(step_input):
        producers["sibling"] = asyncio.current_task()
        try:
            waiting.set()
            await asyncio.Event().wait()
        finally:
            sibling_closed.set()

    workflow = Workflow(
        db=SqliteDb(db_file=str(tmp_path / "cancelled.db")),
        steps=[
            Parallel(
                Step(name="success", executor=success),
                Loop(steps=[Step(executor=loop_step)], max_iterations=2),
                Step(executor=sibling),
            )
        ],
        telemetry=False,
    )
    events = []

    async def consume():
        async for event in workflow.arun(
            "test", run_id="retain-completed", session_id="session", stream=True, stream_events=stream_events
        ):
            events.append(event)

    consumer = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(asyncio.gather(completed.wait(), waiting.wait()), 2)
        # This task owns the completed branch's producer, including its queue notification.
        await asyncio.wait_for(asyncio.shield(producers["success"]), 2)
        assert await workflow.acancel_run("retain-completed")
        release.set()
        await asyncio.wait_for(asyncio.shield(consumer), 2)
        assert sibling_closed.is_set()
        assert all(task.done() for task in producers.values())
        assert len([event for event in events if isinstance(event, WorkflowCancelledEvent)]) == 1
        final = [event for event in events if isinstance(event, WorkflowCompletedEvent)]
        assert len(final) == 1
        assert final[0].run_output.status == RunStatus.cancelled
        assert any("completed before cancellation" in str(result.content) for result in final[0].step_results)
        assert not any(event.event == "ParallelExecutionCompleted" for event in events)
        reader_db = SqliteDb(db_file=str(tmp_path / "cancelled.db"))
        try:
            stored = Workflow(db=reader_db, telemetry=False).get_run("retain-completed", session_id="session")
            assert stored.status == RunStatus.cancelled
            assert any("completed before cancellation" in str(result.content) for result in stored.step_results)
        finally:
            reader_db.close()
    finally:
        consumer.cancel()
        for task in producers.values():
            task.cancel()
        await asyncio.gather(consumer, *producers.values(), return_exceptions=True)
        workflow.db.close()


@pytest.mark.asyncio
async def test_parallel_background_run_survives_sse_close(tmp_path, monkeypatch):
    import agno.os.event_streams as event_streams
    from agno.os.event_streams import InMemoryEventStream
    from agno.os.managers import EventsBuffer, SSESubscriberManager

    monkeypatch.setattr(
        event_streams,
        "_event_stream",
        InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager()),
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def executor(step_input):
        started.set()
        await release.wait()
        return StepOutput(content="completed after disconnect")

    db = SqliteDb(db_file=str(tmp_path / "background.db"))
    workflow = Workflow(db=db, steps=[Parallel(Step(executor=executor))], telemetry=False)
    stream = workflow.arun("test", run_id="background-parallel", session_id="session", background=True, stream=True)
    background = []
    try:
        await asyncio.wait_for(stream.__anext__(), 2)
        await asyncio.wait_for(started.wait(), 2)
        background = [
            task for task in asyncio.all_tasks() if task.get_name() == "workflow-background-stream-background-parallel"
        ]
        assert len(background) == 1
        await stream.aclose()
        assert not background[0].done()
        release.set()
        await asyncio.wait_for(asyncio.gather(*background), 2)
        stored = workflow.get_run("background-parallel", session_id="session")
        assert stored.status == RunStatus.completed
        assert "completed after disconnect" in str(stored.content)
    finally:
        await stream.aclose()
        for task in background:
            task.cancel()
        await asyncio.gather(*background, return_exceptions=True)
        db.close()
