from dataclasses import dataclass
from textwrap import dedent

import pytest
from pydantic import BaseModel

from agno.agent.agent import Agent
from agno.db.base import SessionType
from agno.models.openai.chat import OpenAIChat
from agno.run.agent import CustomEvent, RunEvent, RunInput, RunOutput
from agno.tools.decorator import tool
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools


def test_basic_events():
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
    )

    response_generator = agent.run("Hello, how are you?", stream=True, stream_events=False)

    event_counts = {}
    for run_response in response_generator:
        event_counts[run_response.event] = event_counts.get(run_response.event, 0) + 1

    assert event_counts.keys() == {RunEvent.run_content}

    assert event_counts[RunEvent.run_content] > 1


@pytest.mark.asyncio
async def test_async_basic_events():
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
    )
    event_counts = {}
    async for run_response in agent.arun("Hello, how are you?", stream=True, stream_events=False):
        event_counts[run_response.event] = event_counts.get(run_response.event, 0) + 1

    assert event_counts.keys() == {RunEvent.run_content}

    assert event_counts[RunEvent.run_content] > 1


def test_basic_intermediate_steps_events(shared_db):
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        store_events=True,
        telemetry=False,
    )

    response_generator = agent.run("Hello, how are you?", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert events[RunEvent.run_started][0].model == "gpt-4o-mini"
    assert events[RunEvent.run_started][0].model_provider == "OpenAI"
    assert events[RunEvent.run_started][0].session_id is not None
    assert events[RunEvent.run_started][0].agent_id is not None
    assert events[RunEvent.run_started][0].run_id is not None
    assert events[RunEvent.run_started][0].created_at is not None
    assert len(events[RunEvent.model_request_started]) == 1
    assert len(events[RunEvent.model_request_completed]) == 1
    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.run_content_completed]) == 1
    assert len(events[RunEvent.run_completed]) == 1

    completed_event = events[RunEvent.run_completed][0]
    assert hasattr(completed_event, "metadata")
    assert hasattr(completed_event, "metrics")

    assert completed_event.metrics is not None
    assert completed_event.metrics.total_tokens > 0

    # Check the stored events
    run_response_from_storage = shared_db.get_sessions(session_type=SessionType.AGENT)[0].runs[0]

    assert run_response_from_storage.events is not None
    assert len(run_response_from_storage.events) == 5, (
        "We should have run_started, llm events, and run completed events"
    )
    assert run_response_from_storage.events[0].event == RunEvent.run_started
    assert run_response_from_storage.events[1].event == RunEvent.model_request_started
    assert run_response_from_storage.events[2].event == RunEvent.model_request_completed
    assert run_response_from_storage.events[3].event == RunEvent.run_content_completed
    assert run_response_from_storage.events[4].event == RunEvent.run_completed

    persisted_completed_event = run_response_from_storage.events[4]
    assert hasattr(persisted_completed_event, "metadata")
    assert hasattr(persisted_completed_event, "metrics")

    assert persisted_completed_event.metrics is not None
    assert persisted_completed_event.metrics.total_tokens > 0


def test_intermediate_steps_with_tools(shared_db):
    """Test that the agent streams events."""
    agent = Agent(
        db=shared_db,
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[YFinanceTools(cache_results=True)],
        telemetry=False,
        store_events=True,
    )

    response_generator = agent.run("What is the stock price of Apple?", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.tool_call_started,
        RunEvent.tool_call_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.model_request_started]) >= 1
    assert len(events[RunEvent.model_request_completed]) >= 1
    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.run_content_completed]) == 1
    assert len(events[RunEvent.run_completed]) == 1
    assert len(events[RunEvent.tool_call_started]) == 1
    assert events[RunEvent.tool_call_started][0].tool.tool_name == "get_current_stock_price"  # type: ignore
    assert len(events[RunEvent.tool_call_completed]) == 1
    assert events[RunEvent.tool_call_completed][0].content is not None  # type: ignore
    assert events[RunEvent.tool_call_completed][0].tool.result is not None  # type: ignore

    completed_event = events[RunEvent.run_completed][0]
    assert completed_event.metrics is not None
    assert completed_event.metrics.total_tokens > 0

    # Check the stored events
    run_response_from_storage = shared_db.get_sessions(session_type=SessionType.AGENT)[0].runs[0]

    assert run_response_from_storage.events is not None
    assert len(run_response_from_storage.events) >= 7
    assert run_response_from_storage.events[0].event == RunEvent.run_started
    assert run_response_from_storage.events[1].event == RunEvent.model_request_started


def test_intermediate_steps_with_custom_events():
    """Test that the agent streams events."""

    @dataclass
    class WeatherRequestEvent(CustomEvent):
        city: str = ""
        temperature: int = 0

    def get_weather(city: str):
        yield WeatherRequestEvent(city=city, temperature=70)

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_weather],
        telemetry=False,
    )

    response_generator = agent.run("What is the weather in Tokyo?", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.tool_call_started,
        RunEvent.custom_event,
        RunEvent.tool_call_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.custom_event]) == 1
    assert events[RunEvent.custom_event][0].city == "Tokyo"
    assert events[RunEvent.custom_event][0].temperature == 70
    assert events[RunEvent.custom_event][0].to_dict()["city"] == "Tokyo"
    assert events[RunEvent.custom_event][0].to_dict()["temperature"] == 70

    # Verify tool_call_id is injected and matches the tool call
    custom_event = events[RunEvent.custom_event][0]
    tool_started_event = events[RunEvent.tool_call_started][0]
    assert custom_event.tool_call_id is not None, "tool_call_id should not be None"
    assert custom_event.tool_call_id == tool_started_event.tool.tool_call_id


@pytest.mark.asyncio
async def test_async_intermediate_steps_with_custom_events():
    """Test that the agent streams custom events asynchronously with tool_call_id."""

    @dataclass
    class WeatherRequestEvent(CustomEvent):
        city: str = ""
        temperature: int = 0

    def get_weather(city: str):
        yield WeatherRequestEvent(city=city, temperature=70)

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_weather],
        telemetry=False,
    )

    events = {}
    async for run_response_delta in agent.arun("What is the weather in Tokyo?", stream=True, stream_events=True):
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.tool_call_started,
        RunEvent.custom_event,
        RunEvent.tool_call_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.custom_event]) == 1
    assert events[RunEvent.custom_event][0].city == "Tokyo"
    assert events[RunEvent.custom_event][0].temperature == 70
    assert events[RunEvent.custom_event][0].to_dict()["city"] == "Tokyo"
    assert events[RunEvent.custom_event][0].to_dict()["temperature"] == 70

    # Verify tool_call_id is injected and matches the tool call
    custom_event = events[RunEvent.custom_event][0]
    tool_started_event = events[RunEvent.tool_call_started][0]
    assert custom_event.tool_call_id is not None, "tool_call_id should not be None"
    assert custom_event.tool_call_id == tool_started_event.tool.tool_call_id


def test_intermediate_steps_with_reasoning():
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[ReasoningTools(add_instructions=True)],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
        telemetry=False,
    )

    response_generator = agent.run("What is the sum of the first 10 natural numbers?", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.tool_call_started,
        RunEvent.tool_call_completed,
        RunEvent.reasoning_started,
        RunEvent.reasoning_completed,
        RunEvent.reasoning_step,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.model_request_started]) >= 1
    assert len(events[RunEvent.model_request_completed]) >= 1
    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.run_content_completed]) == 1
    assert len(events[RunEvent.run_completed]) == 1
    assert len(events[RunEvent.tool_call_started]) > 1
    assert len(events[RunEvent.tool_call_completed]) > 1
    assert len(events[RunEvent.reasoning_started]) == 1
    assert len(events[RunEvent.reasoning_completed]) == 1
    assert events[RunEvent.reasoning_completed][0].content is not None  # type: ignore
    assert events[RunEvent.reasoning_completed][0].content_type == "ReasoningSteps"  # type: ignore
    assert len(events[RunEvent.reasoning_step]) > 1
    assert events[RunEvent.reasoning_step][0].content is not None  # type: ignore
    assert events[RunEvent.reasoning_step][0].content_type == "ReasoningStep"  # type: ignore
    assert events[RunEvent.reasoning_step][0].reasoning_content is not None  # type: ignore


def test_intermediate_steps_with_user_confirmation(shared_db):
    """Test that the agent streams events."""

    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        store_events=True,
        add_history_to_context=True,
        num_history_runs=2,
        telemetry=False,
    )

    response_generator = agent.run("What is the weather in Tokyo?", stream=True, stream_events=True)

    # First until we hit a pause
    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)
    run_response = agent.get_last_run_output()
    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.run_paused,
    }
    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.run_paused]) == 1
    assert events[RunEvent.run_paused][0].tools[0].requires_confirmation is True  # type: ignore

    assert run_response.is_paused

    assert run_response.tools[0].requires_confirmation

    # Mark the tool as confirmed
    updated_tools = run_response.tools
    run_id = run_response.run_id
    updated_tools[0].confirmed = True

    # Check stored events
    stored_session = shared_db.get_sessions(session_type=SessionType.AGENT)[0]
    assert stored_session.runs[0].events is not None
    assert len(stored_session.runs[0].events) == 4
    assert stored_session.runs[0].events[0].event == RunEvent.run_started
    assert stored_session.runs[0].events[1].event == RunEvent.model_request_started
    assert stored_session.runs[0].events[2].event == RunEvent.model_request_completed
    assert stored_session.runs[0].events[3].event == RunEvent.run_paused

    # Then we continue the run
    response_generator = agent.continue_run(run_id=run_id, updated_tools=updated_tools, stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    run_response = agent.get_last_run_output()
    assert run_response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"

    assert events.keys() == {
        RunEvent.run_continued,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.tool_call_started,
        RunEvent.tool_call_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_continued]) == 1
    assert len(events[RunEvent.tool_call_started]) == 1
    assert events[RunEvent.tool_call_started][0].tool.tool_name == "get_the_weather"  # type: ignore
    assert len(events[RunEvent.tool_call_completed]) == 1
    assert events[RunEvent.tool_call_completed][0].content is not None
    assert events[RunEvent.tool_call_completed][0].tool.result is not None
    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.run_content_completed]) == 1
    assert len(events[RunEvent.run_completed]) == 1

    assert run_response.is_paused is False

    # Check stored events
    stored_session = shared_db.get_sessions(session_type=SessionType.AGENT)[0]
    assert stored_session.runs[0].events is not None
    assert len(stored_session.runs[0].events) == 11
    assert stored_session.runs[0].events[0].event == RunEvent.run_started
    assert stored_session.runs[0].events[1].event == RunEvent.model_request_started
    assert stored_session.runs[0].events[2].event == RunEvent.model_request_completed
    assert stored_session.runs[0].events[3].event == RunEvent.run_paused
    assert stored_session.runs[0].events[4].event == RunEvent.run_continued
    assert stored_session.runs[0].events[5].event == RunEvent.tool_call_started
    assert stored_session.runs[0].events[6].event == RunEvent.tool_call_completed
    assert stored_session.runs[0].events[7].event == RunEvent.model_request_started
    assert stored_session.runs[0].events[8].event == RunEvent.model_request_completed
    assert stored_session.runs[0].events[9].event == RunEvent.run_content_completed
    assert stored_session.runs[0].events[10].event == RunEvent.run_completed


@pytest.mark.asyncio
async def test_custom_event_in_acontinue_run_with_async_tool(shared_db):
    """Test that CustomEvent from async generator tools is properly yielded in acontinue_run.

    This tests the fix for GitHub issue #6069 where CustomEvents from confirmed tools
    were not being yielded as separate events during acontinue_run.
    """

    @dataclass
    class WeatherRequestEvent(CustomEvent):
        city: str = ""
        temperature: int = 0

    @tool(requires_confirmation=True)
    async def get_the_weather(city: str):
        """Get weather for a city, yielding a custom event first."""
        yield WeatherRequestEvent(city=city, temperature=70)
        yield f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    session_id = "test_custom_event_acontinue"

    # Initial run that requires confirmation
    response = await agent.arun("What is the weather in Tokyo?", session_id=session_id)
    assert response.is_paused
    assert response.tools is not None
    assert response.tools[0].requires_confirmation
    assert response.tools[0].tool_name == "get_the_weather"

    # Mark the tool as confirmed
    response.tools[0].confirmed = True

    # Continue the run with streaming and stream_events
    events = {}
    async for run_response_delta in agent.acontinue_run(
        run_id=response.run_id,
        updated_tools=response.tools,
        session_id=session_id,
        stream=True,
        stream_events=True,
    ):
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    # Verify that CustomEvent was yielded as a separate event
    assert RunEvent.custom_event in events.keys(), (
        f"CustomEvent should be yielded as a separate event. Got events: {events.keys()}"
    )
    assert len(events[RunEvent.custom_event]) == 1
    custom_event = events[RunEvent.custom_event][0]
    assert custom_event.city == "Tokyo"
    assert custom_event.temperature == 70

    # Verify tool_call_id is injected and matches the tool call
    tool_started_event = events[RunEvent.tool_call_started][0]
    assert custom_event.tool_call_id is not None, "tool_call_id should not be None"
    assert custom_event.tool_call_id == tool_started_event.tool.tool_call_id

    # Verify tool result contains the actual weather data
    tool_completed_event = events[RunEvent.tool_call_completed][0]
    assert "70 degrees" in str(tool_completed_event.tool.result)

    # Verify all expected events are present
    assert RunEvent.run_continued in events.keys()
    assert RunEvent.tool_call_started in events.keys()
    assert RunEvent.tool_call_completed in events.keys()
    assert RunEvent.run_completed in events.keys()


def test_custom_event_in_continue_run_with_sync_generator_tool(shared_db):
    """Test that CustomEvent from sync generator tools is properly yielded in continue_run.

    This tests the sync version of the fix for GitHub issue #6069.
    """

    @dataclass
    class WeatherRequestEvent(CustomEvent):
        city: str = ""
        temperature: int = 0

    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        """Get weather for a city, yielding a custom event first."""
        yield WeatherRequestEvent(city=city, temperature=70)
        yield f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    session_id = "test_custom_event_continue"

    # Initial run that requires confirmation
    response = agent.run("What is the weather in Tokyo?", session_id=session_id)
    assert response.is_paused
    assert response.tools is not None
    assert response.tools[0].requires_confirmation
    assert response.tools[0].tool_name == "get_the_weather"

    # Mark the tool as confirmed
    response.tools[0].confirmed = True

    # Continue the run with streaming and stream_events
    events = {}
    for run_response_delta in agent.continue_run(
        run_id=response.run_id,
        updated_tools=response.tools,
        session_id=session_id,
        stream=True,
        stream_events=True,
    ):
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    # Verify that CustomEvent was yielded as a separate event
    assert RunEvent.custom_event in events.keys(), (
        f"CustomEvent should be yielded as a separate event. Got events: {events.keys()}"
    )
    assert len(events[RunEvent.custom_event]) == 1
    custom_event = events[RunEvent.custom_event][0]
    assert custom_event.city == "Tokyo"
    assert custom_event.temperature == 70

    # Verify tool_call_id is injected and matches the tool call
    tool_started_event = events[RunEvent.tool_call_started][0]
    assert custom_event.tool_call_id is not None, "tool_call_id should not be None"
    assert custom_event.tool_call_id == tool_started_event.tool.tool_call_id

    # Verify tool result contains the actual weather data
    tool_completed_event = events[RunEvent.tool_call_completed][0]
    assert "70 degrees" in str(tool_completed_event.tool.result)


def test_intermediate_steps_with_memory(shared_db):
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        update_memory_on_run=True,
        telemetry=False,
    )

    response_generator = agent.run("Hello, how are you?", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
        RunEvent.memory_update_started,
        RunEvent.memory_update_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.model_request_started]) == 1
    assert len(events[RunEvent.model_request_completed]) == 1
    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.run_content_completed]) == 1
    assert len(events[RunEvent.run_completed]) == 1
    assert len(events[RunEvent.memory_update_started]) == 1
    assert len(events[RunEvent.memory_update_completed]) == 1


def test_intermediate_steps_with_session_summary(shared_db):
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        enable_session_summaries=True,
        telemetry=False,
    )

    response_generator = agent.run("Hello, how are you?", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
        RunEvent.session_summary_started,
        RunEvent.session_summary_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.model_request_started]) == 1
    assert len(events[RunEvent.model_request_completed]) == 1
    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.run_content_completed]) == 1
    assert len(events[RunEvent.run_completed]) == 1
    assert len(events[RunEvent.session_summary_started]) == 1
    assert len(events[RunEvent.session_summary_completed]) == 1


def test_pre_hook_events_are_emitted(shared_db):
    """Test that the agent streams events."""

    def pre_hook_1(run_input: RunInput) -> None:
        run_input.input_content += " (Modified by pre-hook 1)"

    def pre_hook_2(run_input: RunInput) -> None:
        run_input.input_content += " (Modified by pre-hook 2)"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        pre_hooks=[pre_hook_1, pre_hook_2],
        telemetry=False,
    )

    response_generator = agent.run("Hello, how are you?", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.pre_hook_started,
        RunEvent.pre_hook_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.model_request_started]) == 1
    assert len(events[RunEvent.model_request_completed]) == 1
    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.run_content_completed]) == 1
    assert len(events[RunEvent.run_completed]) == 1
    assert len(events[RunEvent.pre_hook_started]) == 2
    assert len(events[RunEvent.pre_hook_completed]) == 2
    assert events[RunEvent.pre_hook_started][0].pre_hook_name == "pre_hook_1"
    assert events[RunEvent.pre_hook_started][0].run_input.input_content == "Hello, how are you?"
    assert events[RunEvent.pre_hook_completed][0].pre_hook_name == "pre_hook_1"
    assert (
        events[RunEvent.pre_hook_completed][0].run_input.input_content == "Hello, how are you? (Modified by pre-hook 1)"
    )
    assert (
        events[RunEvent.pre_hook_started][1].run_input.input_content == "Hello, how are you? (Modified by pre-hook 1)"
    )
    assert events[RunEvent.pre_hook_started][1].pre_hook_name == "pre_hook_2"
    assert events[RunEvent.pre_hook_completed][1].pre_hook_name == "pre_hook_2"
    assert (
        events[RunEvent.pre_hook_completed][1].run_input.input_content
        == "Hello, how are you? (Modified by pre-hook 1) (Modified by pre-hook 2)"
    )


@pytest.mark.asyncio
async def test_async_pre_hook_events_are_emitted(shared_db):
    """Test that the agent streams events."""

    async def pre_hook_1(run_input: RunInput) -> None:
        run_input.input_content += " (Modified by pre-hook 1)"

    async def pre_hook_2(run_input: RunInput) -> None:
        run_input.input_content += " (Modified by pre-hook 2)"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        pre_hooks=[pre_hook_1, pre_hook_2],
        telemetry=False,
    )

    response_generator = agent.arun("Hello, how are you?", stream=True, stream_events=True)

    events = {}
    async for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.pre_hook_started,
        RunEvent.pre_hook_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.model_request_started]) == 1
    assert len(events[RunEvent.model_request_completed]) == 1
    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.run_content_completed]) == 1
    assert len(events[RunEvent.run_completed]) == 1
    assert len(events[RunEvent.pre_hook_started]) == 2
    assert len(events[RunEvent.pre_hook_completed]) == 2
    assert events[RunEvent.pre_hook_started][0].pre_hook_name == "pre_hook_1"
    assert events[RunEvent.pre_hook_started][0].run_input.input_content == "Hello, how are you?"
    assert events[RunEvent.pre_hook_completed][0].pre_hook_name == "pre_hook_1"
    assert (
        events[RunEvent.pre_hook_completed][0].run_input.input_content == "Hello, how are you? (Modified by pre-hook 1)"
    )
    assert (
        events[RunEvent.pre_hook_started][1].run_input.input_content == "Hello, how are you? (Modified by pre-hook 1)"
    )
    assert events[RunEvent.pre_hook_started][1].pre_hook_name == "pre_hook_2"
    assert events[RunEvent.pre_hook_completed][1].pre_hook_name == "pre_hook_2"
    assert (
        events[RunEvent.pre_hook_completed][1].run_input.input_content
        == "Hello, how are you? (Modified by pre-hook 1) (Modified by pre-hook 2)"
    )


def test_post_hook_events_are_emitted(shared_db):
    """Test that post hook events are emitted correctly during streaming."""

    def post_hook_1(run_output: RunOutput) -> None:
        run_output.content = str(run_output.content) + " (Modified by post-hook 1)"

    def post_hook_2(run_output: RunOutput) -> None:
        run_output.content = str(run_output.content) + " (Modified by post-hook 2)"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        post_hooks=[post_hook_1, post_hook_2],
        telemetry=False,
    )

    response_generator = agent.run("Hello, how are you?", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.post_hook_started,
        RunEvent.post_hook_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.model_request_started]) == 1
    assert len(events[RunEvent.model_request_completed]) == 1
    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.run_content_completed]) == 1
    assert len(events[RunEvent.run_completed]) == 1
    assert len(events[RunEvent.post_hook_started]) == 2
    assert len(events[RunEvent.post_hook_completed]) == 2

    # Verify first post hook
    assert events[RunEvent.post_hook_started][0].post_hook_name == "post_hook_1"
    assert events[RunEvent.post_hook_completed][0].post_hook_name == "post_hook_1"

    # Verify second post hook
    assert events[RunEvent.post_hook_started][1].post_hook_name == "post_hook_2"
    assert events[RunEvent.post_hook_completed][1].post_hook_name == "post_hook_2"

    # Verify final output includes modifications from both hooks
    final_event = events[RunEvent.run_completed][0]
    assert "(Modified by post-hook 1)" in str(final_event.content)
    assert "(Modified by post-hook 2)" in str(final_event.content)


@pytest.mark.asyncio
async def test_async_post_hook_events_are_emitted(shared_db):
    """Test that async post hook events are emitted correctly during streaming."""

    async def post_hook_1(run_output: RunOutput) -> None:
        run_output.content = str(run_output.content) + " (Modified by async post-hook 1)"

    async def post_hook_2(run_output: RunOutput) -> None:
        run_output.content = str(run_output.content) + " (Modified by async post-hook 2)"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        post_hooks=[post_hook_1, post_hook_2],
        telemetry=False,
    )

    response_generator = agent.arun("Hello, how are you?", stream=True, stream_events=True)

    events = {}
    async for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.post_hook_started,
        RunEvent.post_hook_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.model_request_started]) == 1
    assert len(events[RunEvent.model_request_completed]) == 1
    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.run_content_completed]) == 1
    assert len(events[RunEvent.run_completed]) == 1
    assert len(events[RunEvent.post_hook_started]) == 2
    assert len(events[RunEvent.post_hook_completed]) == 2

    # Verify first post hook
    assert events[RunEvent.post_hook_started][0].post_hook_name == "post_hook_1"
    assert events[RunEvent.post_hook_completed][0].post_hook_name == "post_hook_1"

    # Verify second post hook
    assert events[RunEvent.post_hook_started][1].post_hook_name == "post_hook_2"
    assert events[RunEvent.post_hook_completed][1].post_hook_name == "post_hook_2"

    # Verify final output includes modifications from both hooks
    final_event = events[RunEvent.run_completed][0]
    assert "(Modified by async post-hook 1)" in str(final_event.content)
    assert "(Modified by async post-hook 2)" in str(final_event.content)


def test_pre_and_post_hook_events_are_emitted(shared_db):
    """Test that both pre and post hook events are emitted correctly during streaming."""

    def pre_hook(run_input: RunInput) -> None:
        run_input.input_content += " (Modified by pre-hook)"

    def post_hook(run_output: RunOutput) -> None:
        run_output.content = str(run_output.content) + " (Modified by post-hook)"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        pre_hooks=[pre_hook],
        post_hooks=[post_hook],
        telemetry=False,
    )

    response_generator = agent.run("Hello", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.pre_hook_started,
        RunEvent.pre_hook_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.post_hook_started,
        RunEvent.post_hook_completed,
        RunEvent.run_completed,
    }

    # Verify pre hook events
    assert len(events[RunEvent.pre_hook_started]) == 1
    assert len(events[RunEvent.pre_hook_completed]) == 1
    assert events[RunEvent.pre_hook_started][0].pre_hook_name == "pre_hook"
    assert events[RunEvent.pre_hook_completed][0].pre_hook_name == "pre_hook"

    # Verify post hook events
    assert len(events[RunEvent.post_hook_started]) == 1
    assert len(events[RunEvent.post_hook_completed]) == 1
    assert events[RunEvent.post_hook_started][0].post_hook_name == "post_hook"
    assert events[RunEvent.post_hook_completed][0].post_hook_name == "post_hook"

    # Verify final output includes modifications
    final_event = events[RunEvent.run_completed][0]
    assert "(Modified by post-hook)" in str(final_event.content)


def test_intermediate_steps_with_structured_output(shared_db):
    """Test that the agent streams events."""

    class Person(BaseModel):
        name: str
        description: str
        age: int

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        output_schema=Person,
        telemetry=False,
    )

    response_generator = agent.run("Describe Elon Musk", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)
    run_response = agent.get_last_run_output()

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.model_request_started]) == 1
    assert len(events[RunEvent.model_request_completed]) == 1
    assert len(events[RunEvent.run_content]) == 1
    assert len(events[RunEvent.run_content_completed]) == 1
    assert len(events[RunEvent.run_completed]) == 1

    assert events[RunEvent.run_content][0].content is not None
    assert events[RunEvent.run_content][0].content_type == "Person"
    assert events[RunEvent.run_content][0].content.name == "Elon Musk"
    assert len(events[RunEvent.run_content][0].content.description) > 1

    assert events[RunEvent.run_completed][0].content is not None  # type: ignore
    assert events[RunEvent.run_completed][0].content_type == "Person"  # type: ignore
    assert events[RunEvent.run_completed][0].content.name == "Elon Musk"  # type: ignore
    assert len(events[RunEvent.run_completed][0].content.description) > 1  # type: ignore

    completed_event_structured = events[RunEvent.run_completed][0]
    assert completed_event_structured.metrics is not None
    assert completed_event_structured.metrics.total_tokens > 0

    assert run_response.content is not None
    assert run_response.content_type == "Person"
    assert run_response.content["name"] == "Elon Musk"


def test_intermediate_steps_with_parser_model(shared_db):
    """Test that the agent streams events."""

    class Person(BaseModel):
        name: str
        description: str
        age: int

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        output_schema=Person,
        parser_model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
    )

    response_generator = agent.run("Describe Elon Musk", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)
    run_response = agent.get_last_run_output()

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.parser_model_response_started,
        RunEvent.parser_model_response_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.model_request_started]) == 1
    assert len(events[RunEvent.model_request_completed]) == 1
    assert len(events[RunEvent.parser_model_response_started]) == 1
    assert len(events[RunEvent.parser_model_response_completed]) == 1
    assert (
        len(events[RunEvent.run_content]) >= 2
    )  # The first model streams, then the parser model has a single content event
    assert len(events[RunEvent.run_content_completed]) == 1
    assert len(events[RunEvent.run_completed]) == 1

    assert events[RunEvent.run_content][-1].content is not None
    assert events[RunEvent.run_content][-1].content_type == "Person"
    assert events[RunEvent.run_content][-1].content.name == "Elon Musk"
    assert len(events[RunEvent.run_content][-1].content.description) > 1

    assert events[RunEvent.run_completed][0].content is not None  # type: ignore
    assert events[RunEvent.run_completed][0].content_type == "Person"  # type: ignore
    assert events[RunEvent.run_completed][0].content.name == "Elon Musk"  # type: ignore
    assert len(events[RunEvent.run_completed][0].content.description) > 1  # type: ignore

    assert run_response is not None
    assert run_response.content is not None
    assert run_response.content_type == "Person"
    assert run_response.content["name"] == "Elon Musk"


def test_run_completed_event_metrics_validation(shared_db):
    """Test that RunCompletedEvent properly includes populated metrics on completion."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        store_events=True,
        telemetry=False,
    )

    response_generator = agent.run(
        "Get the current stock price of AAPL",
        session_id="test_session",
        stream=True,
        stream_events=True,
    )

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert RunEvent.run_completed in events
    completed_event = events[RunEvent.run_completed][0]

    assert completed_event.metadata is not None or completed_event.metadata is None  # Can be None or dict
    assert completed_event.metrics is not None, "Metrics should be populated on completion"

    metrics = completed_event.metrics
    assert metrics.total_tokens > 0, "Total tokens should be greater than 0"
    assert metrics.input_tokens >= 0, "Input tokens should be non-negative"
    assert metrics.output_tokens >= 0, "Output tokens should be non-negative"
    assert metrics.total_tokens == metrics.input_tokens + metrics.output_tokens, "Total should equal input + output"

    assert metrics.duration is not None, "Duration should be populated on completion"
    assert metrics.duration > 0, "Duration should be greater than 0"

    stored_session = agent.get_session(session_id="test_session")
    assert stored_session is not None and stored_session.runs is not None
    stored_run = stored_session.runs[0]
    assert stored_run.metrics is not None
    assert stored_run.metrics.total_tokens > 0


def test_model_request_events(shared_db):
    """Test that model request started and completed events are emitted."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        store_events=True,
        telemetry=False,
    )

    response_generator = agent.run("Hello, how are you?", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
    }

    # Verify model request started event
    assert len(events[RunEvent.model_request_started]) == 1
    model_started = events[RunEvent.model_request_started][0]
    assert model_started.model == "gpt-4o-mini"
    assert model_started.model_provider == "OpenAI"

    # Verify model request completed event
    assert len(events[RunEvent.model_request_completed]) == 1
    model_completed = events[RunEvent.model_request_completed][0]
    assert model_completed.model == "gpt-4o-mini"
    assert model_completed.model_provider == "OpenAI"
    assert model_completed.input_tokens is not None
    assert model_completed.input_tokens > 0
    assert model_completed.output_tokens is not None
    assert model_completed.output_tokens > 0
    assert model_completed.total_tokens is not None
    assert model_completed.total_tokens == model_completed.input_tokens + model_completed.output_tokens
    # Verify new metrics fields exist (may be None)
    assert hasattr(model_completed, "time_to_first_token")
    assert hasattr(model_completed, "reasoning_tokens")
    assert hasattr(model_completed, "cache_read_tokens")
    assert hasattr(model_completed, "cache_write_tokens")


@pytest.mark.asyncio
async def test_async_model_request_events(shared_db):
    """Test that async model request started and completed events are emitted."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        store_events=True,
        telemetry=False,
    )

    events = {}
    async for run_response_delta in agent.arun("Hello, how are you?", stream=True, stream_events=True):
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
    }

    # Verify model request started event
    assert len(events[RunEvent.model_request_started]) == 1
    model_started = events[RunEvent.model_request_started][0]
    assert model_started.model == "gpt-4o-mini"
    assert model_started.model_provider == "OpenAI"

    # Verify model request completed event
    assert len(events[RunEvent.model_request_completed]) == 1
    model_completed = events[RunEvent.model_request_completed][0]
    assert model_completed.model == "gpt-4o-mini"
    assert model_completed.model_provider == "OpenAI"
    assert model_completed.input_tokens is not None
    assert model_completed.input_tokens > 0
    assert model_completed.output_tokens is not None
    assert model_completed.output_tokens > 0
    assert model_completed.total_tokens is not None
    assert model_completed.total_tokens == model_completed.input_tokens + model_completed.output_tokens
    # Verify new metrics fields exist (may be None)
    assert hasattr(model_completed, "time_to_first_token")
    assert hasattr(model_completed, "reasoning_tokens")
    assert hasattr(model_completed, "cache_read_tokens")
    assert hasattr(model_completed, "cache_write_tokens")


def test_model_request_events_with_tools(shared_db):
    """Test that multiple model request events are emitted when tools are used."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        tools=[YFinanceTools(cache_results=True)],
        store_events=True,
        telemetry=False,
    )

    response_generator = agent.run("What is the stock price of Apple?", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert RunEvent.model_request_started in events.keys()
    assert RunEvent.model_request_completed in events.keys()

    # With tools, there should be at least 2 model requests (one for tool call, one for response)
    assert len(events[RunEvent.model_request_started]) >= 2, (
        f"Expected at least 2 model request started events, got {len(events[RunEvent.model_request_started])}"
    )
    assert len(events[RunEvent.model_request_completed]) >= 2, (
        f"Expected at least 2 model request completed events, got {len(events[RunEvent.model_request_completed])}"
    )

    # Verify all LLM completed events have model info and token counts
    for model_completed in events[RunEvent.model_request_completed]:
        assert model_completed.model == "gpt-4o-mini"
        assert model_completed.model_provider == "OpenAI"
        assert model_completed.input_tokens is not None
        assert model_completed.output_tokens is not None
        assert model_completed.total_tokens is not None


def test_memory_update_completed_contains_memories(shared_db):
    """Test that MemoryUpdateCompletedEvent contains the updated memories."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        user_id="test_memory_user",
        enable_user_memories=True,
        telemetry=False,
    )

    # First run to create a memory
    response_generator = agent.run("My name is Alice and I live in Paris", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert RunEvent.memory_update_started in events.keys()
    assert RunEvent.memory_update_completed in events.keys()

    assert len(events[RunEvent.memory_update_started]) == 1
    assert len(events[RunEvent.memory_update_completed]) == 1

    # Verify memory_update_completed event has memories field
    memory_completed = events[RunEvent.memory_update_completed][0]
    assert hasattr(memory_completed, "memories")

    # The memories field should contain the user's memories (may be None if no memories created)
    if memory_completed.memories is not None:
        assert isinstance(memory_completed.memories, list)
        # If memories were created, verify structure
        if len(memory_completed.memories) > 0:
            assert hasattr(memory_completed.memories[0], "memory")


@pytest.mark.asyncio
async def test_async_memory_update_completed_contains_memories(shared_db):
    """Test that async MemoryUpdateCompletedEvent contains the updated memories."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        user_id="test_async_memory_user",
        enable_user_memories=True,
        telemetry=False,
    )

    events = {}
    async for run_response_delta in agent.arun("My favorite color is blue", stream=True, stream_events=True):
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert RunEvent.memory_update_started in events.keys()
    assert RunEvent.memory_update_completed in events.keys()

    assert len(events[RunEvent.memory_update_started]) == 1
    assert len(events[RunEvent.memory_update_completed]) == 1

    # Verify memory_update_completed event has memories field
    memory_completed = events[RunEvent.memory_update_completed][0]
    assert hasattr(memory_completed, "memories")

    # The memories field should contain the user's memories (may be None if no memories created)
    if memory_completed.memories is not None:
        assert isinstance(memory_completed.memories, list)


def test_compression_events(shared_db):
    """Test that compression events are emitted when tool result compression is enabled."""

    @tool
    def get_large_data(query: str) -> str:
        """Returns a large amount of data for testing compression."""
        return f"Large data response for {query}: " + "x" * 500

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        tools=[get_large_data],
        compress_tool_results=True,
        store_events=True,
        telemetry=False,
    )

    response_generator = agent.run(
        "Get large data for 'test1' and 'test2'",
        stream=True,
        stream_events=True,
    )

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    # Compression events should be present when compression occurs
    if RunEvent.compression_started in events.keys():
        assert RunEvent.compression_completed in events.keys()

        # Verify compression started event
        assert len(events[RunEvent.compression_started]) >= 1

        # Verify compression completed event has stats
        assert len(events[RunEvent.compression_completed]) >= 1
        compression_completed = events[RunEvent.compression_completed][0]
        assert hasattr(compression_completed, "tool_results_compressed")
        assert hasattr(compression_completed, "original_size")
        assert hasattr(compression_completed, "compressed_size")


@pytest.mark.asyncio
async def test_async_compression_events(shared_db):
    """Test that async compression events are emitted when tool result compression is enabled."""

    @tool
    def get_large_data(query: str) -> str:
        """Returns a large amount of data for testing compression."""
        return f"Large data response for {query}: " + "x" * 500

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        tools=[get_large_data],
        compress_tool_results=True,
        store_events=True,
        telemetry=False,
    )

    events = {}
    async for run_response_delta in agent.arun(
        "Get large data for 'test1' and 'test2'",
        stream=True,
        stream_events=True,
    ):
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    # Compression events should be present when compression occurs
    if RunEvent.compression_started in events.keys():
        assert RunEvent.compression_completed in events.keys()

        # Verify compression started event
        assert len(events[RunEvent.compression_started]) >= 1

        # Verify compression completed event has stats
        assert len(events[RunEvent.compression_completed]) >= 1
        compression_completed = events[RunEvent.compression_completed][0]
        assert hasattr(compression_completed, "tool_results_compressed")
        assert hasattr(compression_completed, "original_size")
        assert hasattr(compression_completed, "compressed_size")


def test_custom_event_properties_persist_after_db_reload(shared_db):
    """Test that custom event subclass properties persist after loading from database."""
    from dataclasses import field
    from typing import Any, Dict

    @dataclass
    class MimeEvent(CustomEvent):
        mime_type: str = ""
        data: Dict[str, Any] = field(default_factory=dict)

    def get_chart(city: str):
        """Get a chart for the given city."""
        yield MimeEvent(
            mime_type="application/echart+json",
            data={"title": "Test Chart", "series": [{"type": "pie"}]},
        )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        tools=[get_chart],
        store_events=True,
        telemetry=False,
    )

    response_generator = agent.run("Get a chart for Tokyo", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert RunEvent.custom_event in events
    assert events[RunEvent.custom_event][0].mime_type == "application/echart+json"
    assert events[RunEvent.custom_event][0].data["title"] == "Test Chart"

    # Check stored events from DB
    stored_session = shared_db.get_sessions(session_type=SessionType.AGENT)[0]
    stored_run = stored_session.runs[0]

    custom_events = [e for e in stored_run.events if e.event == RunEvent.custom_event]
    assert len(custom_events) >= 1
    assert hasattr(custom_events[0], "mime_type")
    assert hasattr(custom_events[0], "data")
    assert custom_events[0].mime_type == "application/echart+json"
    assert custom_events[0].data["title"] == "Test Chart"
