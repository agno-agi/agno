import pytest

from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIChat
from agno.tools.decorator import tool


def test_tool_call_requires_confirmation(shared_db):
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo?")

    assert response.is_paused
    assert response.tools is not None
    assert response.tools[0].requires_confirmation
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Mark the tool as confirmed
    response.tools[0].confirmed = True

    response = agent.continue_run(response)
    assert response.is_paused is False
    assert response.tools is not None
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


def test_tool_call_requires_confirmation_continue_with_run_response(shared_db):
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo?")

    assert response.is_paused
    assert response.tools is not None
    assert response.tools[0].requires_confirmation
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Mark the tool as confirmed
    response.tools[0].confirmed = True

    response = agent.continue_run(response)
    assert response.is_paused is False
    assert response.tools is not None
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


def test_tool_call_requires_confirmation_continue_with_run_id(shared_db):
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    session_id = "test_session_1"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo?", session_id=session_id)

    assert response.is_paused
    assert response.tools is not None
    assert response.tools[0].requires_confirmation
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Mark the tool as confirmed
    response.tools[0].confirmed = True

    # Create a completely new agent instance
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    response = agent.continue_run(run_id=response.run_id, updated_tools=response.tools, session_id=session_id)
    assert response.is_paused is False
    assert response.tools is not None
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


def test_tool_call_requires_confirmation_continue_with_run_id_stream(shared_db):
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    session_id = "test_session_1"
    agent = Agent(
        id="test_agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    updated_tools = None
    for response in agent.run("What is the weather in Tokyo?", session_id=session_id, stream=True, stream_events=True):
        if response.is_paused:
            assert response.tools is not None
            assert response.tools[0].requires_confirmation
            assert response.tools[0].tool_name == "get_the_weather"
            assert response.tools[0].tool_args == {"city": "Tokyo"}

            # Mark the tool as confirmed
            response.tools[0].confirmed = True
            updated_tools = response.tools

    run_response = agent.get_last_run_output(session_id=session_id)
    assert run_response and run_response.is_paused

    # Create a completely new agent instance
    agent = Agent(
        id="test_agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    response = agent.continue_run(
        run_id=run_response.run_id, updated_tools=updated_tools, session_id=session_id, stream=True, stream_events=True
    )
    for response in response:
        if response.is_paused:
            assert False, "The run should not be paused"
    run_response = agent.get_run_output(run_id=run_response.run_id, session_id=session_id)  # type: ignore

    assert run_response and run_response.tools is not None
    assert run_response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


@pytest.mark.asyncio
async def test_tool_call_requires_confirmation_continue_with_run_id_async(shared_db):
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    session_id = "test_session_1"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        instructions="When you have confirmation, then just use the tool",
        telemetry=False,
    )

    response = await agent.arun("What is the weather in Tokyo?", session_id=session_id)

    assert response.is_paused
    assert response.tools is not None
    assert len(response.tools) == 1
    assert response.tools[0].requires_confirmation
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Mark the tool as confirmed
    response.tools[0].confirmed = True

    # Create a completely new agent instance
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    response = await agent.acontinue_run(run_id=response.run_id, updated_tools=response.tools, session_id=session_id)
    assert response.is_paused is False
    assert response.tools is not None
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


def test_tool_call_requires_confirmation_memory_footprint(shared_db):
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        markdown=True,
        telemetry=False,
    )

    session_id = "test_session"

    response = agent.run("What is the weather in Tokyo?", session_id=session_id)

    session_from_db = agent.get_session(session_id=session_id)
    assert session_from_db and session_from_db.runs is not None
    assert len(session_from_db.runs) == 1, "There should be one run in the memory"
    assert len(session_from_db.runs[0].messages) == 3, [m.role for m in session_from_db.runs[0].messages]  # type: ignore
    assert response.is_paused
    assert response.tools is not None

    # Mark the tool as confirmed
    response.tools[0].confirmed = True

    response = agent.continue_run(response)
    assert response.is_paused is False
    assert response.tools is not None
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"

    session_from_db = agent.get_session(session_id=session_id)
    assert session_from_db and session_from_db.runs is not None
    assert len(session_from_db.runs) == 1, "There should be one run in the memory"
    assert len(session_from_db.runs[0].messages) == 5, [m.role for m in session_from_db.runs[0].messages]  # type: ignore


@pytest.mark.asyncio
async def test_tool_call_requires_confirmation_async(shared_db):
    @tool(requires_confirmation=True)
    async def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        markdown=True,
        telemetry=False,
    )

    response = await agent.arun("What is the weather in Tokyo?")

    assert response.is_paused
    assert response.tools is not None
    assert response.tools[0].requires_confirmation
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Mark the tool as confirmed
    response.tools[0].confirmed = True

    response = await agent.acontinue_run(response)
    assert response.tools is not None
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


def test_tool_call_multiple_requires_confirmation(shared_db):
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    def get_activities(city: str):
        return f"The following activities are available in {city}: \n - Shopping \n - Eating \n - Drinking"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather, get_activities],
        db=shared_db,
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo and what are the activities?")

    assert response.is_paused
    assert response.tools is not None
    tool_found = False
    for _t in response.tools:
        if _t.requires_confirmation:
            tool_found = True
            assert _t.tool_name == "get_the_weather"
            assert _t.tool_args == {"city": "Tokyo"}
            _t.confirmed = True

    assert tool_found, "No tool was found to require confirmation"

    response = agent.continue_run(response)
    assert response.is_paused is False
    assert response.content


def test_run_requirement_confirmation(shared_db):
    """Test a HITL confirmation flow using RunRequirements"""

    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    session_id = "test_session_confirmation"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    # Initial run that requires confirmation
    response = agent.run("What is the weather in Tokyo?", session_id=session_id)
    assert response.is_paused
    assert len(response.active_requirements) == 1

    # Get the requirement and verify it needs confirmation
    requirement = response.active_requirements[0]
    assert requirement.needs_confirmation
    assert requirement.tool_execution and requirement.tool_execution.tool_name == "get_the_weather"
    assert requirement.tool_execution and requirement.tool_execution.tool_args == {"city": "Tokyo"}

    # Confirm the RunRequirement
    requirement.confirm()

    # Verify the RunRequirement was confirmed
    assert requirement.tool_execution and requirement.tool_execution.confirmed is True
    assert requirement.confirmation is True

    # Continue the run with run_id and requirements
    response = agent.continue_run(run_id=response.run_id, requirements=response.requirements, session_id=session_id)

    # Verify the run completed successfully
    assert response.is_paused is False
    assert response.tools is not None
    assert response.tools[0].confirmed is True
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


def test_run_requirement_rejection(shared_db):
    """Test a HITL rejection flow using RunRequirements"""

    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    session_id = "test_session_rejection"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    # Initial run that requires confirmation
    response = agent.run("What is the weather in Tokyo?", session_id=session_id)
    assert response.is_paused
    assert len(response.active_requirements) == 1

    # Get the requirement and verify it needs confirmation
    requirement = response.active_requirements[0]
    assert requirement.needs_confirmation
    assert requirement.tool_execution and requirement.tool_execution.tool_name == "get_the_weather"
    assert requirement.tool_execution and requirement.tool_execution.tool_args == {"city": "Tokyo"}

    # Reject the RunRequirement
    requirement.reject()

    # Verify the tool is marked as rejected
    assert requirement.tool_execution and requirement.tool_execution.confirmed is False
    assert requirement.confirmation is False

    # Continue the run with run_id and requirements
    response = agent.continue_run(run_id=response.run_id, requirements=response.requirements, session_id=session_id)

    # Verify the tool was not executed (no result)
    assert response.tools is not None
    assert response.tools[0].confirmed is False
    assert response.tools[0].result is None


@pytest.mark.asyncio
async def test_async_confirmation(shared_db):
    """Test a HITL confirmation flow using RunRequirements and running the agent asynchronously"""

    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    session_id = "test_session_async_confirmation"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    # Initial async run that requires confirmation
    response = await agent.arun("What is the weather in Tokyo?", session_id=session_id)
    assert response.is_paused
    assert len(response.active_requirements) == 1

    # Get the requirement and confirm it
    requirement = response.active_requirements[0]
    assert requirement.needs_confirmation
    assert requirement.tool_execution and requirement.tool_execution.tool_name == "get_the_weather"
    assert requirement.tool_execution and requirement.tool_execution.tool_args == {"city": "Tokyo"}

    # Confirm the RunRequirement
    requirement.confirm()
    assert requirement.tool_execution and requirement.tool_execution.confirmed is True

    # Continue the run with run_id and requirements
    response = await agent.acontinue_run(
        run_id=response.run_id, requirements=response.requirements, session_id=session_id
    )
    assert response.is_paused is False
    assert response.tools is not None
    assert response.tools[0].confirmed is True
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


def test_streaming_confirmation(shared_db):
    """Test a HITL confirmation flow using RunRequirements and streaming the response"""

    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    session_id = "test_session_streaming_confirmation"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    # Stream the initial run (stream=True without stream_events returns RunOutput objects)
    paused_run_output = None
    for run_output in agent.run("What is the weather in Tokyo?", session_id=session_id, stream=True):
        if run_output.is_paused:  # type: ignore
            paused_run_output = run_output
            break

    # Verify we got a paused run with active requirements
    assert paused_run_output is not None
    assert paused_run_output.is_paused
    assert len(paused_run_output.requirements) == 1  # type: ignore

    # Get the requirement and confirm it using the new DX
    requirement = paused_run_output.requirements[0]  # type: ignore
    assert requirement.needs_confirmation
    assert requirement.tool_execution and requirement.tool_execution.tool_name == "get_the_weather"
    assert requirement.tool_execution and requirement.tool_execution.tool_args == {"city": "Tokyo"}

    # Confirm the RunRequirement
    requirement.confirm()
    assert requirement.tool_execution and requirement.tool_execution.confirmed is True

    # Continue the run, streaming the response
    for run_output in agent.continue_run(
        run_id=paused_run_output.run_id,
        updated_tools=paused_run_output.tools,  # type: ignore
        session_id=session_id,
        stream=True,
        yield_run_output=True,
    ):
        continue

    # Verify completion
    assert run_output is not None
    assert run_output.is_paused is False
    assert run_output.tools is not None
    assert run_output.tools[0].confirmed is True
    assert run_output.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


@pytest.mark.asyncio
async def test_streaming_confirmation_async(shared_db):
    """Test a HITL confirmation flow using RunRequirements and streaming the response asynchronously"""

    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    session_id = "test_session_streaming_confirmation"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    # Stream the initial run (stream=True without stream_events returns RunOutput objects)
    paused_run_output = None
    async for run_output in agent.arun("What is the weather in Tokyo?", session_id=session_id, stream=True):
        if run_output.is_paused:  # type: ignore
            paused_run_output = run_output
            break

    # Verify we got a paused run with active requirements
    assert paused_run_output is not None
    assert paused_run_output.is_paused
    assert len(paused_run_output.requirements) == 1  # type: ignore

    # Get the requirement and confirm it using the new DX
    requirement = paused_run_output.requirements[0]  # type: ignore
    assert requirement.needs_confirmation
    assert requirement.tool_execution and requirement.tool_execution.tool_name == "get_the_weather"
    assert requirement.tool_execution and requirement.tool_execution.tool_args == {"city": "Tokyo"}

    # Confirm the RunRequirement
    requirement.confirm()
    assert requirement.tool_execution and requirement.tool_execution.confirmed is True

    # Continue the run, streaming the response
    async for run_output in agent.acontinue_run(
        run_id=paused_run_output.run_id,
        updated_tools=paused_run_output.tools,  # type: ignore
        session_id=session_id,
        stream=True,
        yield_run_output=True,
    ):
        continue

    # Verify completion
    assert run_output is not None
    assert run_output.is_paused is False
    assert run_output.tools is not None
    assert run_output.tools[0].confirmed is True
    assert run_output.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"
