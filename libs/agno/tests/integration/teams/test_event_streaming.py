from textwrap import dedent

import pytest

from agno.models.openai.chat import OpenAIChat
from agno.team import Team, TeamRunEvent
from agno.tools.decorator import tool
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools


def test_basic_events():
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        telemetry=False,
        monitoring=False,
    )

    response_generator = team.run("Hello, how are you?", stream=True, stream_intermediate_steps=False)

    event_counts = {}
    for run_response in response_generator:
        event_counts[run_response.event] = event_counts.get(run_response.event, 0) + 1

    assert event_counts.keys() == {TeamRunEvent.run_response_content}

    assert event_counts[TeamRunEvent.run_response_content] > 1


@pytest.mark.asyncio
async def test_async_basic_events():
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        telemetry=False,
        monitoring=False,
    )
    response_generator = await team.arun("Hello, how are you?", stream=True, stream_intermediate_steps=False)

    event_counts = {}
    async for run_response in response_generator:
        event_counts[run_response.event] = event_counts.get(run_response.event, 0) + 1

    assert event_counts.keys() == {TeamRunEvent.run_response_content}

    assert event_counts[TeamRunEvent.run_response_content] > 1


def test_basic_intermediate_steps_events():
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        telemetry=False,
        monitoring=False,
    )

    response_generator = team.run("Hello, how are you?", stream=True, stream_intermediate_steps=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {TeamRunEvent.run_started, TeamRunEvent.run_response_content, TeamRunEvent.run_completed}

    assert len(events[TeamRunEvent.run_started]) == 1
    assert events[TeamRunEvent.run_started][0].model == "gpt-4o-mini"
    assert events[TeamRunEvent.run_started][0].model_provider == "OpenAI"
    assert events[TeamRunEvent.run_started][0].session_id is not None
    assert events[TeamRunEvent.run_started][0].team_id is not None
    assert events[TeamRunEvent.run_started][0].run_id is not None
    assert events[TeamRunEvent.run_started][0].created_at is not None
    assert len(events[TeamRunEvent.run_response_content]) > 1
    assert len(events[TeamRunEvent.run_completed]) == 1


def test_intermediate_steps_with_tools():
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        tools=[YFinanceTools(cache_results=True)],
        telemetry=False,
        monitoring=False,
    )

    response_generator = team.run("What is the stock price of Apple?", stream=True, stream_intermediate_steps=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        TeamRunEvent.run_started,
        TeamRunEvent.tool_call_started,
        TeamRunEvent.tool_call_completed,
        TeamRunEvent.run_response_content,
        TeamRunEvent.run_completed,
    }

    assert len(events[TeamRunEvent.run_started]) == 1
    assert len(events[TeamRunEvent.run_response_content]) > 1
    assert len(events[TeamRunEvent.run_completed]) == 1
    assert len(events[TeamRunEvent.tool_call_started]) == 1
    assert events[TeamRunEvent.tool_call_started][0].tool.tool_name == "get_current_stock_price"
    assert len(events[TeamRunEvent.tool_call_completed]) == 1
    assert events[TeamRunEvent.tool_call_completed][0].content is not None
    assert events[TeamRunEvent.tool_call_completed][0].tool.result is not None


def test_intermediate_steps_with_reasoning():
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        tools=[ReasoningTools(add_instructions=True)],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
        telemetry=False,
        monitoring=False,
    )

    response_generator = team.run(
        "What is the sum of the first 10 natural numbers?",
        stream=True,
        stream_intermediate_steps=True,
    )

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        TeamRunEvent.run_started,
        TeamRunEvent.tool_call_started,
        TeamRunEvent.tool_call_completed,
        TeamRunEvent.reasoning_started,
        TeamRunEvent.reasoning_completed,
        TeamRunEvent.reasoning_step,
        TeamRunEvent.run_response_content,
        TeamRunEvent.run_completed,
    }

    assert len(events[TeamRunEvent.run_started]) == 1
    assert len(events[TeamRunEvent.run_response_content]) > 1
    assert len(events[TeamRunEvent.run_completed]) == 1
    assert len(events[TeamRunEvent.tool_call_started]) > 1
    assert len(events[TeamRunEvent.tool_call_completed]) > 1
    assert len(events[TeamRunEvent.reasoning_started]) == 1
    assert len(events[TeamRunEvent.reasoning_completed]) == 1
    assert events[TeamRunEvent.reasoning_completed][0].content is not None
    assert events[TeamRunEvent.reasoning_completed][0].content_type == "ReasoningSteps"
    assert len(events[TeamRunEvent.reasoning_step]) > 1
    assert events[TeamRunEvent.reasoning_step][0].content is not None
    assert events[TeamRunEvent.reasoning_step][0].content_type == "ReasoningStep"
    assert events[TeamRunEvent.reasoning_step][0].reasoning_content is not None


@pytest.mark.skip(reason="Not yet implemented")
def test_intermediate_steps_with_user_confirmation():
    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        tools=[get_the_weather],
        telemetry=False,
        monitoring=False,
    )

    response_generator = team.run("What is the weather in Tokyo?", stream=True, stream_intermediate_steps=True)

    # First until we hit a pause
    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {TeamRunEvent.run_started, TeamRunEvent.run_paused}

    assert len(events[TeamRunEvent.run_started]) == 1
    assert len(events[TeamRunEvent.run_paused]) == 1
    assert events[TeamRunEvent.run_paused][0].tools[0].requires_confirmation is True

    assert team.is_paused

    assert team.run_response.tools[0].requires_confirmation

    # Mark the tool as confirmed
    updated_tools = team.run_response.tools
    run_id = team.run_response.run_id
    updated_tools[0].confirmed = True

    # Then we continue the run
    response_generator = team.continue_run(
        run_id=run_id, updated_tools=updated_tools, stream=True, stream_intermediate_steps=True
    )

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert team.run_response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"

    assert events.keys() == {
        TeamRunEvent.run_continued,
        TeamRunEvent.tool_call_started,
        TeamRunEvent.tool_call_completed,
        TeamRunEvent.run_response_content,
        TeamRunEvent.run_completed,
    }

    assert len(events[TeamRunEvent.run_continued]) == 1
    assert len(events[TeamRunEvent.tool_call_started]) == 1
    assert events[TeamRunEvent.tool_call_started][0].tool.tool_name == "get_the_weather"
    assert len(events[TeamRunEvent.tool_call_completed]) == 1
    assert events[TeamRunEvent.tool_call_completed][0].content is not None
    assert events[TeamRunEvent.tool_call_completed][0].tool.result is not None
    assert len(events[TeamRunEvent.run_response_content]) > 1
    assert len(events[TeamRunEvent.run_completed]) == 1

    assert team.run_response.is_paused is False


def test_intermediate_steps_with_memory(team_storage, memory):
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        memory=memory,
        storage=team_storage,
        enable_user_memories=True,
        telemetry=False,
        monitoring=False,
    )

    response_generator = team.run("Hello, how are you?", stream=True, stream_intermediate_steps=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        TeamRunEvent.run_started,
        TeamRunEvent.run_response_content,
        TeamRunEvent.run_completed,
        TeamRunEvent.memory_update_started,
        TeamRunEvent.memory_update_completed,
    }

    assert len(events[TeamRunEvent.run_started]) == 1
    assert len(events[TeamRunEvent.run_response_content]) > 1
    assert len(events[TeamRunEvent.run_completed]) == 1
    assert len(events[TeamRunEvent.memory_update_started]) == 1
    assert len(events[TeamRunEvent.memory_update_completed]) == 1
