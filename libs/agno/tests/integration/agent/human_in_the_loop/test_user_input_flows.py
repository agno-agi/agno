import asyncio

import pytest

from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIChat
from agno.tools.decorator import tool


def test_tool_call_requires_user_input():
    @tool(requires_user_input=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo?")

    assert response.is_paused
    assert response.tools is not None
    assert response.tools[0].requires_user_input
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}
    assert response.tools[0].user_input_schema is not None

    # Provide user input
    response.tools[0].user_input_schema[0].value = "Tokyo"

    response = agent.continue_run(response)
    assert response.is_paused is False
    assert response.tools is not None
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


def test_tool_call_requires_user_input_specific_fields():
    @tool(requires_user_input=True, user_input_fields=["temperature"])
    def get_the_weather(city: str, temperature: int):
        return f"It is currently {temperature} degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo?")
    assert response.tools is not None
    assert response.is_paused
    assert response.tools[0].requires_user_input
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}
    assert response.tools[0].user_input_schema is not None

    # Provide user input
    assert response.tools[0].user_input_schema[0].name == "city"
    assert response.tools[0].user_input_schema[0].value == "Tokyo"
    assert response.tools[0].user_input_schema[1].name == "temperature"
    assert response.tools[0].user_input_schema[1].value is None
    response.tools[0].user_input_schema[1].value = 70

    response = agent.continue_run(response)
    assert response.is_paused is False
    assert response.tools is not None
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


def test_tool_call_requires_user_input_stream(shared_db):
    @tool(requires_user_input=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        markdown=True,
        telemetry=False,
    )

    found_user_input = False
    for response in agent.run("What is the weather in Tokyo?", stream=True):
        if response.is_paused:
            assert response.tools is not None
            assert response.tools[0].requires_user_input
            assert response.tools[0].tool_name == "get_the_weather"
            assert response.tools[0].tool_args == {"city": "Tokyo"}
            assert response.tools[0].user_input_schema is not None

            # Provide user input
            response.tools[0].user_input_schema[0].value = "Tokyo"
            found_user_input = True

    assert found_user_input, "No tools were found to require user input"

    found_user_input = False
    for response in agent.continue_run(run_id=response.run_id, updated_tools=response.tools, stream=True):
        if response.is_paused:
            found_user_input = True
    assert found_user_input is False, "Some tools still require user input"


@pytest.mark.asyncio
async def test_tool_call_requires_user_input_async(shared_db):
    @tool(requires_user_input=True)
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
    assert response.tools[0].requires_user_input
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Provide user input
    for tool_response in response.tools:
        if tool_response.requires_user_input:
            assert tool_response.user_input_schema is not None
            tool_response.user_input_schema[0].value = "Tokyo"

    response = await agent.acontinue_run(response)
    await asyncio.sleep(1)
    assert response.is_paused is False
    assert response.tools is not None
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


@pytest.mark.asyncio
async def test_tool_call_requires_user_input_stream_async(shared_db):
    @tool(requires_user_input=True)
    async def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        markdown=True,
        telemetry=False,
    )

    found_user_input = False
    async for response in agent.arun("What is the weather in Tokyo?", stream=True):
        if response.is_paused:
            assert response.tools is not None
            assert response.tools[0].requires_user_input
            assert response.tools[0].tool_name == "get_the_weather"
            assert response.tools[0].tool_args == {"city": "Tokyo"}
            assert response.tools[0].user_input_schema is not None

            # Provide user input
            response.tools[0].user_input_schema[0].value = "Tokyo"
            found_user_input = True
    assert found_user_input, "No tools were found to require user input"

    found_user_input = False
    async for response in agent.acontinue_run(run_id=response.run_id, updated_tools=response.tools, stream=True):
        if response.is_paused:
            found_user_input = True
    await asyncio.sleep(1)
    assert found_user_input is False, "Some tools still require user input"


def test_tool_call_requires_user_input_continue_with_run_id(shared_db):
    @tool(requires_user_input=True)
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
    assert response.tools[0].requires_user_input
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Provide user input
    assert response.tools[0].user_input_schema is not None
    response.tools[0].user_input_schema[0].value = "Tokyo"

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


def test_tool_call_multiple_requires_user_input():
    @tool(requires_user_input=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    def get_activities(city: str):
        return f"The following activities are available in {city}: \n - Shopping \n - Eating \n - Drinking"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather, get_activities],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo and what are the activities?")

    assert response.is_paused
    tool_found = False
    assert response.tools is not None
    for _t in response.tools:
        if _t.requires_user_input:
            tool_found = True
            assert _t.tool_name == "get_the_weather"
            assert _t.tool_args == {"city": "Tokyo"}
            assert _t.user_input_schema is not None
            _t.user_input_schema[0].value = "Tokyo"

    assert tool_found, "No tool was found to require user input"

    response = agent.continue_run(response)
    assert response.is_paused is False
    assert response.content


def test_run_requirement_user_input(shared_db):
    """Test the new DX for user input using active_requirements and field.value"""

    @tool(requires_user_input=True, user_input_fields=["city"])
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    session_id = "test_session_user_input"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    # Initial run that requires user input
    response = agent.run("What is the weather?", session_id=session_id)

    # Verify the run is paused and has active requirements
    assert response.is_paused
    assert len(response.active_requirements) == 1

    # Get the requirement and verify it needs user input
    requirement = response.active_requirements[0]
    assert requirement.needs_user_input
    assert requirement.tool_execution and requirement.tool_execution.tool_name == "get_the_weather"

    input_schema = requirement.user_input_schema
    assert input_schema is not None
    assert len(input_schema) == 1
    assert input_schema[0].name == "city"

    # Set the field value
    input_schema[0].value = "Tokyo"

    # Verify the field was updated
    assert input_schema[0].value == "Tokyo"

    # Continue the run with run_id and requirements
    response = agent.continue_run(run_id=response.run_id, requirements=response.requirements, session_id=session_id)

    # Verify the run completed successfully
    assert response.is_paused is False
    assert response.tools is not None
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


def test_run_requirement_user_input_multiple_fields(shared_db):
    """Test the new DX for user input with multiple fields"""

    @tool(requires_user_input=True, user_input_fields=["city", "temperature"])
    def get_the_weather(city: str, temperature: int):
        return f"It is currently {temperature} degrees and cloudy in {city}"

    session_id = "test_session_user_input_multiple"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    # Initial run that requires user input
    response = agent.run("What is the weather?", session_id=session_id)

    # Verify the run is paused
    assert response.is_paused
    assert len(response.active_requirements) == 1

    # Get the requirement
    requirement = response.active_requirements[0]
    assert requirement.needs_user_input

    # Use the new DX to provide user input for multiple fields
    input_schema = requirement.user_input_schema
    assert input_schema is not None
    assert len(input_schema) == 2

    # Set values for all fields
    for field in input_schema:
        if field.name == "city":
            field.value = "Tokyo"
        elif field.name == "temperature":
            field.value = 70

    # Continue the run
    response = agent.continue_run(run_id=response.run_id, requirements=response.requirements, session_id=session_id)

    # Verify completion
    assert response.is_paused is False
    assert response.tools is not None
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


@pytest.mark.asyncio
async def test_async_user_input(shared_db):
    """Test the new DX for async user input using active_requirements"""

    @tool(requires_user_input=True, user_input_fields=["city"])
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    session_id = "test_session_async_user_input"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    # Initial async run that requires user input
    response = await agent.arun("What is the weather?", session_id=session_id)

    # Verify the run is paused and has active requirements
    assert response.is_paused
    assert len(response.active_requirements) == 1

    # Get the requirement and provide input
    requirement = response.active_requirements[0]
    assert requirement.needs_user_input

    # Use the new DX to provide user input
    input_schema = requirement.user_input_schema
    assert input_schema is not None
    assert len(input_schema) == 1
    input_schema[0].value = "Tokyo"

    # Continue the run with run_id and requirements
    response = await agent.acontinue_run(
        run_id=response.run_id, requirements=response.requirements, session_id=session_id
    )

    # Verify completion
    assert response.is_paused is False
    assert response.tools is not None
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


def test_streaming_user_input(shared_db):
    """Test the new DX for streaming user input using active_requirements"""

    @tool(requires_user_input=True, user_input_fields=["city"])
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    session_id = "test_session_streaming_user_input"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    # Stream the initial run
    paused_run_output = None
    for run_output in agent.run("What is the weather?", session_id=session_id, stream=True):
        if run_output.is_paused:  # type: ignore
            paused_run_output = run_output
            break

    # Verify we got a paused run with active requirements
    assert paused_run_output is not None
    assert paused_run_output.is_paused

    # Get the requirement using new DX - note: streaming uses .requirements not .active_requirements
    requirements = paused_run_output.requirements  # type: ignore
    assert requirements is not None
    assert len(requirements) == 1

    requirement = requirements[0]
    assert requirement.needs_user_input

    # Provide user input
    input_schema = requirement.user_input_schema
    assert input_schema is not None
    assert len(input_schema) == 1
    input_schema[0].value = "Tokyo"

    # Continue the run with streaming
    final_output = None
    for run_output in agent.continue_run(
        run_id=paused_run_output.run_id,
        updated_tools=paused_run_output.tools,  # type: ignore
        session_id=session_id,
        stream=True,
        yield_run_output=True,
    ):
        final_output = run_output

    # Verify completion
    assert final_output is not None
    assert final_output.is_paused is False  # type: ignore
    assert final_output.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"  # type: ignore
