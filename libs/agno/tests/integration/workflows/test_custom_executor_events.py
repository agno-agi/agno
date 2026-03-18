"""Integration tests for workflow streaming events."""

from pydantic import BaseModel

from agno.agent.agent import Agent
from agno.workflow import Step, Workflow
from agno.workflow.types import StepInput, StepOutput


def test_agent_stream_basic_events():
    def test_step_one_executor(step_input: StepInput) -> StepOutput:
        agent = Agent(
            name="custom_agent",
            instructions="You are a custom agent that can perform a custom task.",
        )
        response = agent.run(input=step_input.input, stream=True)
        for chunk in response:
            yield chunk

    test_step_one = Step(
        name="test_step_one",
        executor=test_step_one_executor,
    )

    workflow = Workflow(
        name="test_workflow",
        steps=[test_step_one],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))
    event_types = [type(event).__name__ for event in events]

    print(event_types)

    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types
    assert "StepStartedEvent" in event_types
    assert "StepCompletedEvent" in event_types
    assert "StepOutputEvent" in event_types
    assert "StepOutputEvent" in event_types
    assert "RunContentEvent" in event_types


def test_agent_stream_all_events():
    def test_step_one_executor(step_input: StepInput) -> StepOutput:
        agent = Agent(
            name="custom_agent",
            instructions="You are a custom agent that can perform a custom task.",
        )
        response = agent.run(input=step_input.input, stream=True, stream_events=True)
        for chunk in response:
            yield chunk

    test_step_one = Step(
        name="test_step_one",
        executor=test_step_one_executor,
    )

    workflow = Workflow(
        name="test_workflow",
        steps=[test_step_one],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))
    event_types = [type(event).__name__ for event in events]

    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types
    assert "StepStartedEvent" in event_types
    assert "StepCompletedEvent" in event_types
    assert "StepOutputEvent" in event_types
    assert "StepOutputEvent" in event_types
    assert "RunContentEvent" in event_types
    assert "RunStartedEvent" in event_types
    assert "RunContentCompletedEvent" in event_types
    assert "RunCompletedEvent" in event_types


def test_agent_stream_with_output_schema():
    class TestClass(BaseModel):
        name: str
        age: int
        location: str

    def test_step_one_executor(step_input: StepInput) -> StepOutput:
        agent = Agent(
            name="custom_agent",
            output_schema=TestClass,
            instructions="You are a custom agent that can perform a custom task.",
        )
        response = agent.run(input=step_input.input, stream=True)
        for chunk in response:
            yield chunk

    test_step_one = Step(
        name="test_step_one",
        executor=test_step_one_executor,
    )

    workflow = Workflow(
        name="test_workflow",
        steps=[test_step_one],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))
    event_types = [type(event).__name__ for event in events]

    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types
    assert "StepStartedEvent" in event_types
    assert "StepCompletedEvent" in event_types
    assert "StepOutputEvent" in event_types
    assert "StepOutputEvent" in event_types
    assert "RunContentEvent" in event_types


def test_agent_stream_with_yield_run_output():
    def test_step_one_executor(step_input: StepInput) -> StepOutput:
        agent = Agent(
            name="custom_agent",
            instructions="You are a custom agent that can perform a custom task.",
        )
        response = agent.run(input=step_input.input, stream=True, yield_run_output=True)
        for chunk in response:
            yield chunk

    test_step_one = Step(
        name="test_step_one",
        executor=test_step_one_executor,
    )

    workflow = Workflow(
        name="test_workflow",
        steps=[test_step_one],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))
    event_types = [type(event).__name__ for event in events]

    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types
    assert "StepStartedEvent" in event_types
    assert "StepCompletedEvent" in event_types
    assert "StepOutputEvent" in event_types
    assert "StepOutputEvent" in event_types
    assert "RunContentEvent" in event_types


def test_agent_stream_with_yield_step_output():
    def test_step_one_executor(step_input: StepInput) -> StepOutput:
        agent = Agent(
            name="custom_agent",
            instructions="You are a custom agent that can perform a custom task.",
        )
        response = agent.run(input=step_input.input, stream=True, yield_run_output=True)
        for chunk in response:
            yield chunk
        yield StepOutput(content="Hello, world!")

    test_step_one = Step(
        name="test_step_one",
        executor=test_step_one_executor,
    )

    workflow = Workflow(
        name="test_workflow",
        steps=[test_step_one],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))
    event_types = [type(event).__name__ for event in events]

    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types
    assert "StepStartedEvent" in event_types
    assert "StepCompletedEvent" in event_types
    assert "StepOutputEvent" in event_types
    assert "RunContentEvent" in event_types
