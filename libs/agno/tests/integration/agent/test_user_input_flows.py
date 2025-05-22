import pytest

from agno.agent import Agent, RunResponse  # noqa
from agno.models.openai import OpenAIChat
from agno.tools.decorator import tool


def test_tool_call_requires_user_input():
    @tool(requires_user_input=True)
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
    assert response.tools[0].requires_user_input
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Mark the tool as confirmed
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
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What is the weather in Tokyo?")

    assert response.is_paused
    assert response.tools[0].requires_user_input
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Mark the tool as confirmed
    assert response.tools[0].user_input_schema[0].name == "city"
    assert response.tools[0].user_input_schema[0].value == "Tokyo"
    assert response.tools[0].user_input_schema[1].name == "temperature"
    assert response.tools[0].user_input_schema[1].value is None
    response.tools[0].user_input_schema[1].value = 70

    response = agent.continue_run(response)
    assert response.is_paused is False
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


def test_tool_call_requires_user_input_stream():
    @tool(requires_user_input=True)
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

    found_user_input = False
    for response in agent.run("What is the weather in Tokyo?", stream=True):
        if response.is_paused:
            assert response.tools[0].requires_user_input
            assert response.tools[0].tool_name == "get_the_weather"
            assert response.tools[0].tool_args == {"city": "Tokyo"}

            # Mark the tool as confirmed
            response.tools[0].user_input_schema[0].value = "Tokyo"
            found_user_input = True
    assert found_user_input, "No tools were found to require user input"

    found_user_input = False
    for response in agent.continue_run(response, stream=True):
        if response.is_paused:
            found_user_input = True
    assert found_user_input is False, "Some tools still require user input"


@pytest.mark.asyncio
async def test_tool_call_requires_user_input_async():
    @tool(requires_user_input=True)
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
    assert response.tools[0].requires_user_input
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Mark the tool as confirmed
    response.tools[0].user_input_schema[0].value = "Tokyo"

    response = await agent.acontinue_run(response)
    assert response.is_paused is False
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


@pytest.mark.asyncio
async def test_tool_call_requires_user_input_stream_async():
    @tool(requires_user_input=True)
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

    found_user_input = False
    async for response in await agent.arun("What is the weather in Tokyo?", stream=True):
        if response.is_paused:
            assert response.tools[0].requires_user_input
            assert response.tools[0].tool_name == "get_the_weather"
            assert response.tools[0].tool_args == {"city": "Tokyo"}

            # Mark the tool as confirmed
            response.tools[0].user_input_schema[0].value = "Tokyo"
            found_user_input = True
    assert found_user_input, "No tools were found to require user input"

    found_user_input = False
    async for response in await agent.acontinue_run(response, stream=True):
        if response.is_paused:
            found_user_input = True
    assert found_user_input is False, "Some tools still require user input"


def test_tool_call_multiple_requires_user_input():
    @tool(requires_user_input=True)
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
        if _t.requires_user_input:
            tool_found = True
            assert _t.tool_name == "get_the_weather"
            assert _t.tool_args == {"city": "Tokyo"}
            _t.user_input_schema[0].value = "Tokyo"

    assert tool_found, "No tool was found to require user input"

    response = agent.continue_run(response)
    assert response.is_paused is False
    assert response.content
