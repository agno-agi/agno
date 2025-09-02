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
    assert response.tools[0].requires_confirmation
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Mark the tool as confirmed
    response.tools[0].confirmed = True

    response = agent.continue_run(response)
    assert response.is_paused is False
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
    assert response.tools[0].requires_confirmation
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Mark the tool as confirmed
    response.tools[0].confirmed = True

    response = agent.continue_run(response)
    assert response.is_paused is False
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
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


def test_tool_call_requires_confirmation_continue_with_run_id_stream(shared_db):
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

    updated_tools = None
    for response in agent.run("What is the weather in Tokyo?", session_id=session_id, stream=True):
        if response.is_paused:
            assert response.tools[0].requires_confirmation
            assert response.tools[0].tool_name == "get_the_weather"
            assert response.tools[0].tool_args == {"city": "Tokyo"}

            # Mark the tool as confirmed
            response.tools[0].confirmed = True
            updated_tools = response.tools

    run_response = agent.get_last_run_output(session_id=session_id)
    assert run_response.is_paused

    # Create a completely new agent instance
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    response = agent.continue_run(
        run_id=run_response.run_id, updated_tools=updated_tools, session_id=session_id, stream=True
    )
    for response in response:
        if response.is_paused:
            assert False, "The run should not be paused"
    run_response = agent.get_last_run_output(session_id=session_id)
    assert run_response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


@pytest.mark.asyncio
@pytest.mark.skip(reason="Async makes this test flaky")
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

    assert len(session_from_db.runs) == 1, "There should be one run in the memory"
    assert len(session_from_db.runs[0].messages) == 3, [m.role for m in session_from_db.runs[0].messages]
    assert response.is_paused

    # Mark the tool as confirmed
    response.tools[0].confirmed = True

    response = agent.continue_run(response)
    assert response.is_paused is False
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"

    session_from_db = agent.get_session(session_id=session_id)

    assert len(session_from_db.runs) == 1, "There should be one run in the memory"
    assert len(session_from_db.runs[0].messages) == 5, [m.role for m in session_from_db.runs[0].messages]


@pytest.mark.flaky(reruns=2, reason="Asserting against a generated response makes this flaky")
def test_tool_call_requires_confirmation_stream(shared_db):
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

    found_confirmation = False
    for response in agent.run("What is the weather in Tokyo?", stream=True):
        if response.is_paused:
            assert response.tools is not None
            assert response.tools[0].requires_confirmation
            assert response.tools[0].tool_name == "get_the_weather"
            assert response.tools[0].tool_args == {"city": "Tokyo"}
            # Mark the tool as confirmed
            response.tools[0].confirmed = True
            found_confirmation = True

    assert found_confirmation, "No tools were found to require confirmation"
    run_response = agent.get_last_run_output()

    found_confirmation = False
    for response in agent.continue_run(run_response, stream=True):
        if response.is_paused:
            found_confirmation = True

    assert found_confirmation is False, "Some tools still require confirmation"


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
    assert response.tools[0].requires_confirmation
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Mark the tool as confirmed
    response.tools[0].confirmed = True

    response = await agent.acontinue_run(response)
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"


@pytest.mark.asyncio
@pytest.mark.flaky(reruns=2, reason="Async makes this test flaky")
async def test_tool_call_requires_confirmation_stream_async(shared_db):
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

    found_confirmation = False
    async for response in agent.arun("What is the weather in Tokyo?", stream=True):
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

    run_response = agent.get_last_run_output()

    found_confirmation = False
    async for response in agent.acontinue_run(run_response, stream=True):
        if response.is_paused:
            found_confirmation = True
    assert found_confirmation is False, "Some tools still require confirmation"


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
