

from typing import Iterator
import pytest

from agno.agent.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.run.response import RunResponse
from agno.workflow.workflow import Workflow



@pytest.fixture
def workflow(workflow_storage):
    
    class ExampleWorkflow(Workflow):
        description: str = "A workflow for tests"

        agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

        def run(self, message: str) -> RunResponse:
            return RunResponse(
                run_id=self.run_id, content="Received message: " + message
            )

    return ExampleWorkflow(
        storage=workflow_storage,
    )


@pytest.fixture
def async_workflow(workflow_storage):
    
    class ExampleWorkflow(Workflow):
        description: str = "A workflow for tests"

        agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

        async def arun(self, message: str) -> RunResponse:
            return RunResponse(
                run_id=self.run_id, content="Received message: " + message
            )
        
    return ExampleWorkflow(
        storage=workflow_storage,
    )


def test_workflow_storage(workflow, workflow_storage):
    
    response: RunResponse = workflow.run(message="Tell me a joke.")
    assert response.content == "Received message: Tell me a joke."
    
    stored_workflow_session = workflow_storage.read(session_id=workflow.session_id)
    assert stored_workflow_session is not None
    

@pytest.mark.asyncio
async def test_workflow_storage_async(async_workflow, workflow_storage):
    
    response: RunResponse = await async_workflow.arun(message="Tell me a joke.")
    assert response.content == "Received message: Tell me a joke."
    
    stored_workflow_session = workflow_storage.read(session_id=async_workflow.session_id)
    assert stored_workflow_session is not None
    
    
    
    
        
    
    
    