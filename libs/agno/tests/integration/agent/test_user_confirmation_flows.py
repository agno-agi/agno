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
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    agent.run("What is the weather in Tokyo?")

    assert agent.run_response.is_paused
    assert agent.run_response.tools[0].requires_confirmation
    assert agent.run_response.tools[0].tool_name == "get_the_weather"
    assert agent.run_response.tools[0].tool_args == {"city": "Tokyo"}

    # Mark the tool as confirmed
    agent.run_response.tools[0].confirmed = True

    agent.continue_run()
    assert agent.run_response.is_paused is False
    assert agent.run_response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


def test_tool_call_requires_confirmation_continue_with_run_response():
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
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


def test_tool_call_requires_confirmation_continue_with_run_id(agent_storage, memory):
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    session_id = "test_session_1"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        storage=agent_storage,
        memory=memory,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What is the weather in Tokyo?", session_id=session_id)

    assert response.is_paused
    assert response.tools[0].requires_confirmation
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Mark the tool as confirmed
    response.tools[0].confirmed = True

    # Create a completely new agent instance
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        storage=agent_storage,
        memory=memory,
        telemetry=False,
        monitoring=False,
    )

    response = agent.continue_run(run_id=response.run_id, updated_tools=response.tools, session_id=session_id)
    assert response.is_paused is False
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


def test_tool_call_requires_confirmation_continue_with_run_id_stream(agent_storage, memory):
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    session_id = "test_session_1"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        storage=agent_storage,
        memory=memory,
        telemetry=False,
        monitoring=False,
    )

    updated_tools = None
    for response in agent.run("What is the weather in Tokyo?", session_id=session_id, stream=True):
        if response.is_paused:
            assert response.tools[0].requires_confirmation
            assert response.tools[0].tool_name == "get_the_weather"
            assert response.tools[0].tool_args == {"city": "Tokyo"}

            # Mark the tool as confirmed
            response.tools[0].confirmed = True
            updated_tools = response.tools

    assert agent.run_response.is_paused

    # Create a completely new agent instance
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        storage=agent_storage,
        memory=memory,
        telemetry=False,
        monitoring=False,
    )

    response = agent.continue_run(
        run_id=response.run_id, updated_tools=updated_tools, session_id=session_id, stream=True
    )
    for response in response:
        if response.is_paused:
            assert False, "The run should not be paused"

    assert agent.run_response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


@pytest.mark.asyncio
@pytest.mark.skip(reason="Async makes this test flaky")
async def test_tool_call_requires_confirmation_continue_with_run_id_async(agent_storage, memory):
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    session_id = "test_session_1"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        storage=agent_storage,
        memory=memory,
        instructions="When you have confirmation, then just use the tool",
        telemetry=False,
        monitoring=False,
    )

    response = await agent.arun("What is the weather in Tokyo?", session_id=session_id)

    assert response.is_paused
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
        storage=agent_storage,
        memory=memory,
        telemetry=False,
        monitoring=False,
    )

    response = await agent.acontinue_run(run_id=response.run_id, updated_tools=response.tools, session_id=session_id)
    assert response.is_paused is False
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


def test_tool_call_requires_confirmation_memory_footprint():
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    session_id = "test_session"

    response = agent.run("What is the weather in Tokyo?", session_id=session_id)

    assert len(agent.memory.runs[session_id]) == 1, "There should be one run in the memory"
    assert len(agent.memory.runs[session_id][0].messages) == 3, (
        "There should be three messages in the run (system, user, assistant)"
    )

    assert response.is_paused

    # Mark the tool as confirmed
    response.tools[0].confirmed = True

    response = agent.continue_run(response)
    assert response.is_paused is False
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"

    assert len(agent.memory.runs[session_id]) == 1, "There should be one run in the memory"
    assert len(agent.memory.runs[session_id][0].messages) == 5, (
        "There should be five messages in the run (system, user, assistant, tool call, assistant)"
    )


def test_tool_call_requires_confirmation_stream():
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
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
    for response in agent.continue_run(agent.run_response, stream=True):
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
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


@pytest.mark.asyncio
@pytest.mark.skip(reason="Async makes this test flaky")
async def test_tool_call_requires_confirmation_stream_async():
    @tool(requires_confirmation=True)
    async def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
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
            for tool_response in response.tools:
                if tool_response.requires_confirmation:
                    tool_response.confirmed = True
            found_confirmation = True
    assert found_confirmation, "No tools were found to require confirmation"

    found_confirmation = False
    async for response in await agent.acontinue_run(agent.run_response, stream=True):
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
