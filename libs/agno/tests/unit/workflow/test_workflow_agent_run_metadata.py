"""A workflow that answers through its workflow agent must persist the caller's
run metadata.

The run routes stamp the previewed component version into the run metadata and
read it back on continue/fork. The four workflow-agent paths build their own
WorkflowRunOutput, so a stamp that only reaches run()/arun() is lost for any
workflow that has an agent, and the continue silently resolves the published
version instead of the previewed draft.
"""

from typing import Any, List

import pytest

from agno.db.in_memory import InMemoryDb
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session.workflow import WorkflowSession
from agno.workflow.types import WorkflowExecutionInput
from agno.workflow.workflow import Workflow

STAMP = {"agno_component_version": 7}


class FakeWorkflowAgent:
    """Stands in for a WorkflowAgent that answers directly (no workflow tool call)."""

    def __init__(self) -> None:
        self.id = "wf-agent"

    def _output(self) -> RunOutput:
        return RunOutput(run_id="agent-run-1", content="direct answer", messages=None)

    def run(self, **kwargs: Any) -> Any:
        if kwargs.get("stream"):
            return iter([self._output()])
        return self._output()

    def arun(self, **kwargs: Any) -> Any:
        # The streaming path iterates the return value directly, the
        # non-streaming path awaits it.
        if kwargs.get("stream"):

            async def _events():
                yield self._output()

            return _events()

        async def _answer():
            return self._output()

        return _answer()


def make_workflow() -> Workflow:
    workflow = Workflow(id="wf-meta", name="wf meta", db=InMemoryDb(), steps=[])
    workflow.agent = FakeWorkflowAgent()  # type: ignore[assignment]
    workflow._initialize_workflow_agent = lambda *a, **kw: None  # type: ignore[method-assign]
    workflow._async_initialize_workflow_agent = lambda *a, **kw: None  # type: ignore[method-assign]
    workflow._get_workflow_agent_dependencies = lambda session: {}  # type: ignore[method-assign]
    return workflow


def make_context() -> RunContext:
    return RunContext(run_id="run-1", session_id="s-1", metadata=dict(STAMP))


def capture_persisted(workflow: Workflow) -> List[WorkflowRunOutput]:
    persisted: List[WorkflowRunOutput] = []

    def _persist(session: Any = None, run: Any = None, **kwargs: Any) -> None:
        persisted.append(run)

    async def _apersist(session: Any = None, run: Any = None, **kwargs: Any) -> None:
        persisted.append(run)

    workflow._persist_session_and_run = _persist  # type: ignore[method-assign]
    workflow._apersist_session_and_run = _apersist  # type: ignore[method-assign]
    return persisted


class TestWorkflowAgentRunMetadata:
    def test_sync_direct_answer_carries_the_caller_metadata(self):
        workflow = make_workflow()
        capture_persisted(workflow)
        run_context = make_context()

        run = workflow._run_workflow_agent(
            agent_input="hi",
            session=WorkflowSession(session_id="s-1", workflow_id=workflow.id),
            execution_input=WorkflowExecutionInput(input="hi"),
            run_context=run_context,
        )

        assert run.metadata == STAMP

    @pytest.mark.asyncio
    async def test_async_direct_answer_carries_the_caller_metadata(self):
        workflow = make_workflow()
        capture_persisted(workflow)
        run_context = make_context()

        run = await workflow._arun_workflow_agent(
            agent_input="hi",
            session=WorkflowSession(session_id="s-1", workflow_id=workflow.id),
            execution_input=WorkflowExecutionInput(input="hi"),
            run_context=run_context,
        )

        assert run.metadata == STAMP

    def test_sync_stream_direct_answer_carries_the_caller_metadata(self):
        workflow = make_workflow()
        persisted = capture_persisted(workflow)
        run_context = make_context()

        list(
            workflow._run_workflow_agent_stream(
                agent_input="hi",
                session=WorkflowSession(session_id="s-1", workflow_id=workflow.id),
                execution_input=WorkflowExecutionInput(input="hi"),
                run_context=run_context,
            )
        )

        assert persisted, "the direct answer must be persisted"
        assert persisted[-1].metadata == STAMP

    @pytest.mark.asyncio
    async def test_async_stream_direct_answer_carries_the_caller_metadata(self):
        workflow = make_workflow()
        persisted = capture_persisted(workflow)
        run_context = make_context()

        async for _ in workflow._arun_workflow_agent_stream(
            agent_input="hi",
            session=WorkflowSession(session_id="s-1", workflow_id=workflow.id),
            execution_input=WorkflowExecutionInput(input="hi"),
            run_context=run_context,
        ):
            pass

        assert persisted, "the direct answer must be persisted"
        assert persisted[-1].metadata == STAMP
