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
    assert len(run_response_from_storage.events) == 3, "We should only have the run started and run completed events"
    assert run_response_from_storage.events[0].event == RunEvent.run_started
    assert run_response_from_storage.events[1].event == RunEvent.run_content_completed
    assert run_response_from_storage.events[2].event == RunEvent.run_completed

    persisted_completed_event = run_response_from_storage.events[2]
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
        RunEvent.tool_call_started,
        RunEvent.tool_call_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
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
    assert len(run_response_from_storage.events) == 5
    assert run_response_from_storage.events[0].event == RunEvent.run_started
    assert run_response_from_storage.events[1].event == RunEvent.tool_call_started
    assert run_response_from_storage.events[2].event == RunEvent.tool_call_completed
    assert run_response_from_storage.events[3].event == RunEvent.run_content_completed
    assert run_response_from_storage.events[4].event == RunEvent.run_completed


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
    assert events.keys() == {RunEvent.run_started, RunEvent.run_paused}
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
    assert len(stored_session.runs[0].events) == 2
    assert stored_session.runs[0].events[0].event == RunEvent.run_started
    assert stored_session.runs[0].events[1].event == RunEvent.run_paused

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
    assert len(stored_session.runs[0].events) == 7
    assert stored_session.runs[0].events[0].event == RunEvent.run_started
    assert stored_session.runs[0].events[1].event == RunEvent.run_paused
    assert stored_session.runs[0].events[2].event == RunEvent.run_continued
    assert stored_session.runs[0].events[3].event == RunEvent.tool_call_started
    assert stored_session.runs[0].events[4].event == RunEvent.tool_call_completed
    assert stored_session.runs[0].events[5].event == RunEvent.run_content_completed
    assert stored_session.runs[0].events[6].event == RunEvent.run_completed


def test_intermediate_steps_with_memory(shared_db):
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        enable_user_memories=True,
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
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
        RunEvent.memory_update_started,
        RunEvent.memory_update_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
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
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
        RunEvent.session_summary_started,
        RunEvent.session_summary_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
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
        RunEvent.pre_hook_started,
        RunEvent.pre_hook_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
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
        RunEvent.pre_hook_started,
        RunEvent.pre_hook_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
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
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.post_hook_started,
        RunEvent.post_hook_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
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
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.post_hook_started,
        RunEvent.post_hook_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
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
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
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
        RunEvent.parser_model_response_started,
        RunEvent.parser_model_response_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
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
