"""Tests for async workflows and async generators in Agno workflows.

This module contains tests to verify that async workflows and async generators
work correctly with the Agno workflow system.
"""

import asyncio
from typing import AsyncIterator

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.response import RunResponse
from agno.run.workflow import WorkflowCompletedEvent
from agno.workflow import Workflow


class SimpleAsyncWorkflow(Workflow):
    """Simple async workflow that returns a RunResponse."""

    description: str = "A simple async workflow for testing"

    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

    async def arun(self, message: str) -> RunResponse:
        return RunResponse(run_id=self.run_id, content=f"Async response: {message}")


class AsyncGeneratorWorkflow(Workflow):
    """Async workflow that yields multiple RunResponse events."""

    description: str = "An async generator workflow for testing"

    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

    async def arun(self, message: str) -> AsyncIterator[RunResponse]:
        # Yield multiple responses
        yield RunResponse(run_id=self.run_id, content=f"First async response: {message}")
        yield RunResponse(run_id=self.run_id, content=f"Second async response: {message}")
        yield WorkflowCompletedEvent(run_id=self.run_id, content=f"Workflow completed: {message}")


class MixedWorkflow(Workflow):
    """Workflow with both sync and async methods."""

    description: str = "A workflow with both sync and async methods"

    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

    def run(self, message: str) -> RunResponse:
        return RunResponse(run_id=self.run_id, content=f"Sync response: {message}")

    async def arun(self, message: str) -> RunResponse:
        return RunResponse(run_id=self.run_id, content=f"Async response: {message}")


class AsyncGeneratorWithStateWorkflow(Workflow):
    """Async generator workflow that maintains state."""

    description: str = "An async generator workflow with state management"

    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

    async def arun(self, message: str) -> AsyncIterator[RunResponse]:
        # Initialize state
        if "counter" not in self.session_state:
            self.session_state["counter"] = 0

        # Increment counter
        self.session_state["counter"] += 1

        yield RunResponse(run_id=self.run_id, content=f"Step {self.session_state['counter']}: {message}")

        # Simulate some async work
        await asyncio.sleep(0.01)

        yield RunResponse(run_id=self.run_id, content=f"Step {self.session_state['counter'] + 1}: Processing complete")

        yield WorkflowCompletedEvent(
            run_id=self.run_id, content=f"Workflow completed with {self.session_state['counter'] + 1} steps"
        )


class ErrorHandlingAsyncWorkflow(Workflow):
    """Async workflow that tests error handling."""

    description: str = "An async workflow for testing error handling"

    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

    async def arun(self, should_error: bool = False) -> RunResponse:
        if should_error:
            raise ValueError("Test error from async workflow")

        return RunResponse(run_id=self.run_id, content="Async workflow completed successfully")


# Basic async workflow tests
@pytest.mark.asyncio
async def test_simple_async_workflow():
    """Test basic async workflow functionality."""
    workflow = SimpleAsyncWorkflow()
    response = await workflow.arun(message="Hello, async world!")

    assert response is not None
    assert response.content == "Async response: Hello, async world!"
    assert response.run_id is not None
    assert response.session_id is not None
    assert response.workflow_id is not None


@pytest.mark.asyncio
async def test_simple_async_workflow_with_storage(workflow_storage):
    """Test async workflow with storage."""
    workflow = SimpleAsyncWorkflow(storage=workflow_storage)
    response = await workflow.arun(message="Hello, async world!")

    assert response is not None
    assert response.content == "Async response: Hello, async world!"

    # Verify storage was used
    stored_session = workflow_storage.read(session_id=workflow.session_id)
    assert stored_session is not None
    assert stored_session.session_id == workflow.session_id


# Async generator tests
@pytest.mark.asyncio
async def test_async_generator_workflow():
    """Test async generator workflow functionality."""
    workflow = AsyncGeneratorWorkflow()
    responses = []

    async for response in workflow.arun(message="Hello, generator!"):
        responses.append(response)

    assert len(responses) == 3
    assert responses[0].content == "First async response: Hello, generator!"
    assert responses[1].content == "Second async response: Hello, generator!"
    assert responses[2].content == "Workflow completed: Hello, generator!"
    assert isinstance(responses[2], WorkflowCompletedEvent)

    # Verify all responses have the same run_id
    run_ids = {r.run_id for r in responses}
    assert len(run_ids) == 1
    assert run_ids.pop() is not None


@pytest.mark.asyncio
async def test_async_generator_workflow_with_storage(workflow_storage):
    """Test async generator workflow with storage."""
    workflow = AsyncGeneratorWorkflow(storage=workflow_storage)
    responses = []

    async for response in workflow.arun(message="Hello, generator!"):
        responses.append(response)

    assert len(responses) == 3

    # Verify storage was used
    stored_session = workflow_storage.read(session_id=workflow.session_id)
    assert stored_session is not None
    assert stored_session.session_id == workflow.session_id


@pytest.mark.asyncio
async def test_async_generator_with_state(workflow_storage):
    """Test async generator workflow with state management."""
    workflow = AsyncGeneratorWithStateWorkflow(storage=workflow_storage)
    responses = []

    async for response in workflow.arun(message="State test"):
        responses.append(response)

    assert len(responses) == 3
    assert "Step 1: State test" in responses[0].content
    assert "Step 2: Processing complete" in responses[1].content
    assert "Workflow completed with 2 steps" in responses[2].content

    # Verify state was persisted
    stored_session = workflow_storage.read(session_id=workflow.session_id)
    assert stored_session is not None
    assert stored_session.session_data["session_state"]["counter"] == 1


# Mixed sync/async workflow tests
@pytest.mark.asyncio
async def test_mixed_workflow_async():
    """Test mixed workflow using async method."""
    workflow = MixedWorkflow()
    response = await workflow.arun(message="Mixed async")

    assert response.content == "Async response: Mixed async"


def test_mixed_workflow_sync():
    """Test mixed workflow using sync method."""
    workflow = MixedWorkflow()
    response = workflow.run(message="Mixed sync")

    assert response.content == "Sync response: Mixed sync"


# Error handling tests
@pytest.mark.asyncio
async def test_async_workflow_error_handling():
    """Test error handling in async workflows."""
    workflow = ErrorHandlingAsyncWorkflow()

    # Test successful execution
    response = await workflow.arun(should_error=False)
    assert response.content == "Async workflow completed successfully"

    # Test error handling
    with pytest.raises(ValueError, match="Test error from async workflow"):
        await workflow.arun(should_error=True)


@pytest.mark.asyncio
async def test_async_generator_error_handling():
    """Test error handling in async generators."""

    class ErrorGeneratorWorkflow(Workflow):
        description: str = "Async generator with error"

        async def arun(self, should_error: bool = False) -> AsyncIterator[RunResponse]:
            yield RunResponse(run_id=self.run_id, content="Starting...")

            if should_error:
                raise ValueError("Error in generator")

            yield RunResponse(run_id=self.run_id, content="Completed")

    workflow = ErrorGeneratorWorkflow()

    # Test successful execution
    responses = []
    async for response in workflow.arun(should_error=False):
        responses.append(response)

    assert len(responses) == 2
    assert responses[0].content == "Starting..."
    assert responses[1].content == "Completed"

    # Test error handling
    workflow = ErrorGeneratorWorkflow()
    responses = []

    with pytest.raises(ValueError, match="Error in generator"):
        async for response in workflow.arun(should_error=True):
            responses.append(response)

    # Should have received the first response before the error
    assert len(responses) == 1
    assert responses[0].content == "Starting..."


# Workflow state and session tests
@pytest.mark.asyncio
async def test_workflow_session_persistence(workflow_storage):
    """Test that workflow sessions are properly persisted."""
    workflow = AsyncGeneratorWithStateWorkflow(storage=workflow_storage)

    # First run
    responses = []
    async for response in workflow.arun(message="First run"):
        responses.append(response)

    session_id = workflow.session_id
    assert session_id is not None

    # Create new workflow instance with same session
    workflow2 = AsyncGeneratorWithStateWorkflow(storage=workflow_storage, session_id=session_id)

    # Second run - should continue from previous state
    responses2 = []
    async for response in workflow2.arun(message="Second run"):
        responses2.append(response)

    # Counter should be 2 (incremented from 1)
    assert "Step 2: Second run" in responses2[0].content
    assert "Step 3: Processing complete" in responses2[1].content
    assert "Workflow completed with 3 steps" in responses2[2].content


# Performance and concurrency tests
@pytest.mark.asyncio
async def test_concurrent_async_workflows():
    """Test running multiple async workflows concurrently."""
    workflows = [SimpleAsyncWorkflow() for _ in range(3)]

    # Run all workflows concurrently
    tasks = [workflow.arun(message=f"Concurrent test {i}") for i, workflow in enumerate(workflows)]

    responses = await asyncio.gather(*tasks)

    assert len(responses) == 3
    for i, response in enumerate(responses):
        assert response.content == f"Async response: Concurrent test {i}"


@pytest.mark.asyncio
async def test_concurrent_async_generators():
    """Test running multiple async generators concurrently."""
    workflows = [AsyncGeneratorWorkflow() for _ in range(2)]

    async def collect_responses(workflow, message):
        responses = []
        async for response in workflow.arun(message=message):
            responses.append(response)
        return responses

    # Run all workflows concurrently
    tasks = [collect_responses(workflow, f"Generator test {i}") for i, workflow in enumerate(workflows)]

    all_responses = await asyncio.gather(*tasks)

    assert len(all_responses) == 2
    for i, responses in enumerate(all_responses):
        assert len(responses) == 3
        assert f"Generator test {i}" in responses[0].content


if __name__ == "__main__":
    # Run tests directly for debugging
    pytest.main([__file__, "-v"])
