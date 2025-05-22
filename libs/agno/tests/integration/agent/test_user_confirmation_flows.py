import pytest

from agno.agent import Agent, RunResponse  # noqa
from agno.models.openai import OpenAIChat
from agno.tools.decorator import tool


def test_tool_call_requires_confirmation():
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What is the weather in Tokyo?")

    assert response.is_paused
    assert response.tools[0].requires_confirmation
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Mark the tool as confirmed
    response.tools[0].confirmed = True

    response = agent.continue_run(response)
    assert response.is_paused is False
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


def test_tool_call_requires_confirmation_stream():
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    found_confirmation = False
    for response in agent.run("What is the weather in Tokyo?", stream=True):
        if response.is_paused:
            assert response.tools[0].requires_confirmation
            assert response.tools[0].tool_name == "get_the_weather"
            assert response.tools[0].tool_args == {"city": "Tokyo"}

            # Mark the tool as confirmed
            response.tools[0].confirmed = True
            found_confirmation = True
    assert found_confirmation, "No tools were found to require confirmation"

    found_confirmation = False
    for response in agent.continue_run(response, stream=True):
        if response.is_paused:
            found_confirmation = True
    assert found_confirmation is False, "Some tools still require confirmation"


@pytest.mark.asyncio
async def test_tool_call_requires_confirmation_async():
    @tool(requires_confirmation=True)
    async def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = await agent.arun("What is the weather in Tokyo?")

    assert response.is_paused
    assert response.tools[0].requires_confirmation
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Mark the tool as confirmed
    response.tools[0].confirmed = True

    response = await agent.acontinue_run(response)
    assert response.is_paused is False
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


def test_tool_call_requires_confirmation_error():
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What is the weather in Tokyo?")

    # Check that we cannot continue without confirmation
    with pytest.raises(ValueError):
        response = agent.continue_run(response)


@pytest.mark.asyncio
async def test_tool_call_requires_confirmation_stream_async():
    @tool(requires_confirmation=True)
    async def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    found_confirmation = False
    async for response in await agent.arun("What is the weather in Tokyo?", stream=True):
        if response.is_paused:
            assert response.tools[0].requires_confirmation
            assert response.tools[0].tool_name == "get_the_weather"
            assert response.tools[0].tool_args == {"city": "Tokyo"}

            # Mark the tool as confirmed
            response.tools[0].confirmed = True
            found_confirmation = True
    assert found_confirmation, "No tools were found to require confirmation"

    found_confirmation = False
    async for response in await agent.acontinue_run(response, stream=True):
        if response.is_paused:
            found_confirmation = True
    assert found_confirmation is False, "Some tools still require confirmation"


def test_tool_call_multiple_requires_confirmation():
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    def get_activities(city: str):
        return f"The following activities are available in {city}: \n - Shopping \n - Eating \n - Drinking"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather, get_activities],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What is the weather in Tokyo and what are the activities?")

    assert response.is_paused
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
