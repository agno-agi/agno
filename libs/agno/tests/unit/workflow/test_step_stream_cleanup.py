import pytest

from agno.agent import Agent
from agno.run.agent import RunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput


class _ClosableIterator:
    def __init__(self):
        self.closed = False
        self._items = iter([RunOutput(run_id="executor-run", content="done")])

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._items)

    def close(self):
        self.closed = True


class _ClosableAsyncIterator:
    def __init__(self):
        self.closed = False
        self._sent = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        return RunOutput(run_id="executor-run", content="done")

    async def aclose(self):
        self.closed = True


class _StreamingAgent(Agent):
    def __init__(self, stream):
        super().__init__(name="streaming-agent")
        self.stream = stream

    def run(self, **kwargs):
        return self.stream

    def arun(self, **kwargs):
        return self.stream


def _workflow_run_response():
    return WorkflowRunOutput(
        run_id="workflow-run",
        session_id="workflow-session",
        workflow_id="workflow",
        workflow_name="Workflow",
    )


def test_execute_stream_closes_executor_stream_after_final_run_output():
    stream = _ClosableIterator()
    step = Step(name="step", agent=_StreamingAgent(stream))

    events = list(
        step.execute_stream(
            StepInput(input="hello"),
            stream_events=True,
            workflow_run_response=_workflow_run_response(),
        )
    )

    assert stream.closed is True
    assert any(isinstance(event, StepOutput) and event.content == "done" for event in events)


@pytest.mark.asyncio
async def test_aexecute_stream_acloses_executor_stream_after_final_run_output():
    stream = _ClosableAsyncIterator()
    step = Step(name="step", agent=_StreamingAgent(stream))

    events = [
        event
        async for event in step.aexecute_stream(
            StepInput(input="hello"),
            stream_events=True,
            workflow_run_response=_workflow_run_response(),
        )
    ]

    assert stream.closed is True
    assert any(isinstance(event, StepOutput) and event.content == "done" for event in events)
