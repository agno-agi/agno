from collections.abc import AsyncIterator
from typing import Iterator

import pytest

from agno.agent.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.run.response import RunResponse
from agno.workflow.workflow import Workflow


def test_workflow_storage(workflow_storage):
    class ExampleWorkflow(Workflow):
        description: str = "A workflow for tests"

        agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

        def run(self, message: str) -> RunResponse:
            return RunResponse(run_id=self.run_id, content="Received message: " + message)

    workflow = ExampleWorkflow(storage=workflow_storage)
    response: RunResponse = workflow.run(message="Tell me a joke.")
    assert response.content == "Received message: Tell me a joke."

    stored_workflow_session = workflow_storage.read(session_id=workflow.session_id)
    assert stored_workflow_session is not None


def test_workflow_storage_streaming(workflow_storage):
    class ExampleWorkflow(Workflow):
        description: str = "A workflow for tests"

        agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

        def run(self, message: str) -> Iterator[RunResponse]:
            yield RunResponse(run_id=self.run_id, content="Received message: " + message)

    workflow = ExampleWorkflow(storage=workflow_storage)
    response: Iterator[RunResponse] = workflow.run(message="Tell me a joke.")
    assert list(response)[0].content == "Received message: Tell me a joke."

    stored_workflow_session = workflow_storage.read(session_id=workflow.session_id)
    assert stored_workflow_session is not None


@pytest.mark.asyncio
async def test_workflow_storage_async(workflow_storage):
    class ExampleWorkflow(Workflow):
        description: str = "A workflow for tests"

        agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

        async def arun(self, message: str) -> RunResponse:
            return RunResponse(run_id=self.run_id, content="Received message: " + message)

    workflow = ExampleWorkflow(storage=workflow_storage)
    response: RunResponse = await workflow.arun(message="Tell me a joke.")
    assert response.content == "Received message: Tell me a joke."

    stored_workflow_session = workflow_storage.read(session_id=workflow.session_id)
    assert stored_workflow_session is not None


@pytest.mark.asyncio
async def test_workflow_storage_async_streaming(workflow_storage):
    class ExampleWorkflow(Workflow):
        description: str = "A workflow for tests"

        agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

        async def arun(self, message: str) -> AsyncIterator[RunResponse]:
            yield RunResponse(run_id=self.run_id, content="Received message: " + message)

    workflow = ExampleWorkflow(storage=workflow_storage)
    async for item in workflow.arun(message="Tell me a joke."):
        assert item.content == "Received message: Tell me a joke."

    stored_workflow_session = workflow_storage.read(session_id=workflow.session_id)
    assert stored_workflow_session is not None
