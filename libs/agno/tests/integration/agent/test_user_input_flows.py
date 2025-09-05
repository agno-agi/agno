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
    assert response.tools[0].requires_user_input
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Provide user input
    response.tools[0].user_input_schema[0].value = "Tokyo"

    response = agent.continue_run(response)
    assert response.is_paused is False
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

    assert response.is_paused
    assert response.tools[0].requires_user_input
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Provide user input
    assert response.tools[0].user_input_schema[0].name == "city"
    assert response.tools[0].user_input_schema[0].value == "Tokyo"
    assert response.tools[0].user_input_schema[1].name == "temperature"
    assert response.tools[0].user_input_schema[1].value is None
    response.tools[0].user_input_schema[1].value = 70

    response = agent.continue_run(response)
    assert response.is_paused is False
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
            assert response.tools[0].requires_user_input
            assert response.tools[0].tool_name == "get_the_weather"
            assert response.tools[0].tool_args == {"city": "Tokyo"}

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
@pytest.mark.skip(reason="Async makes this test flaky")
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
    assert response.tools[0].requires_user_input
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Provide user input
    for tool_response in response.tools:
        if tool_response.requires_user_input:
            tool_response.user_input_schema[0].value = "Tokyo"

    response = await agent.acontinue_run(response)
    await asyncio.sleep(1)
    assert response.is_paused is False
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
            assert response.tools[0].requires_user_input
            assert response.tools[0].tool_name == "get_the_weather"
            assert response.tools[0].tool_args == {"city": "Tokyo"}

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
    assert response.tools[0].requires_user_input
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Provide user input
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
    for _t in response.tools:
        if _t.requires_user_input:
            tool_found = True
            assert _t.tool_name == "get_the_weather"
            assert _t.tool_args == {"city": "Tokyo"}
            _t.user_input_schema[0].value = "Tokyo"

    assert tool_found, "No tool was found to require user input"

    response = agent.continue_run(response)
    assert response.is_paused is False
    assert response.content
