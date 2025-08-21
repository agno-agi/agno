from textwrap import dedent

import pytest
from pydantic import BaseModel

from agno.agent.agent import Agent
from agno.db.base import SessionType
from agno.models.openai.chat import OpenAIChat
from agno.run.agent import RunEvent
from agno.tools.decorator import tool
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools


def test_basic_events():
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
    )

    response_generator = agent.run("Hello, how are you?", stream=True, stream_intermediate_steps=False)

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
    async for run_response in agent.arun("Hello, how are you?", stream=True, stream_intermediate_steps=False):
        event_counts[run_response.event] = event_counts.get(run_response.event, 0) + 1

    assert event_counts.keys() == {RunEvent.run_content}

    assert event_counts[RunEvent.run_content] > 1


def test_basic_intermediate_steps_events():
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
    )

    response_generator = agent.run("Hello, how are you?", stream=True, stream_intermediate_steps=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {RunEvent.run_started, RunEvent.run_content, RunEvent.run_completed}

    assert len(events[RunEvent.run_started]) == 1
    assert events[RunEvent.run_started][0].model == "gpt-4o-mini"
    assert events[RunEvent.run_started][0].model_provider == "OpenAI"
    assert events[RunEvent.run_started][0].session_id is not None
    assert events[RunEvent.run_started][0].agent_id is not None
    assert events[RunEvent.run_started][0].run_id is not None
    assert events[RunEvent.run_started][0].created_at is not None
    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.run_completed]) == 1


def test_basic_intermediate_steps_events_persisted(shared_db):
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        store_events=True,
        telemetry=False,
    )

    response_generator = agent.run("Hello, how are you?", stream=True, stream_intermediate_steps=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {RunEvent.run_started, RunEvent.run_content, RunEvent.run_completed}

    run_response_from_storage = shared_db.get_sessions(session_type=SessionType.AGENT)[0].runs[0]

    assert run_response_from_storage.events is not None
    assert len(run_response_from_storage.events) == 2, "We should only have the run started and run completed events"
    assert run_response_from_storage.events[0].event == RunEvent.run_started
    assert run_response_from_storage.events[1].event == RunEvent.run_completed


def test_intermediate_steps_with_tools():
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[YFinanceTools(cache_results=True)],
        telemetry=False,
    )

    response_generator = agent.run("What is the stock price of Apple?", stream=True, stream_intermediate_steps=True)

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
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.run_completed]) == 1
    assert len(events[RunEvent.tool_call_started]) == 1
    assert events[RunEvent.tool_call_started][0].tool.tool_name == "get_current_stock_price"  # type: ignore
    assert len(events[RunEvent.tool_call_completed]) == 1
    assert events[RunEvent.tool_call_completed][0].content is not None  # type: ignore
    assert events[RunEvent.tool_call_completed][0].tool.result is not None  # type: ignore


def test_intermediate_steps_with_tools_events_persisted(shared_db):
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[YFinanceTools(cache_results=True)],
        db=shared_db,
        store_events=True,
        telemetry=False,
    )

    response_generator = agent.run("What is the stock price of Apple?", stream=True, stream_intermediate_steps=True)

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
        RunEvent.run_completed,
    }

    run_response_from_storage = shared_db.get_sessions(session_type=SessionType.AGENT)[0].runs[0]

    assert run_response_from_storage.events is not None
    assert len(run_response_from_storage.events) == 4
    assert run_response_from_storage.events[0].event == RunEvent.run_started
    assert run_response_from_storage.events[1].event == RunEvent.tool_call_started
    assert run_response_from_storage.events[2].event == RunEvent.tool_call_completed
    assert run_response_from_storage.events[3].event == RunEvent.run_completed


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

    response_generator = agent.run(
        "What is the sum of the first 10 natural numbers?", stream=True, stream_intermediate_steps=True
    )

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
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.run_content]) > 1
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

    response_generator = agent.run("What is the weather in Tokyo?", stream=True, stream_intermediate_steps=True)

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
    response_generator = agent.continue_run(
        run_id=run_id, updated_tools=updated_tools, stream=True, stream_intermediate_steps=True
    )

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
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_continued]) == 1
    assert len(events[RunEvent.tool_call_started]) == 1
    assert events[RunEvent.tool_call_started][0].tool.tool_name == "get_the_weather"  # type: ignore
    assert len(events[RunEvent.tool_call_completed]) == 1
    assert events[RunEvent.tool_call_completed][0].content is not None
    assert events[RunEvent.tool_call_completed][0].tool.result is not None
    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.run_completed]) == 1

    assert run_response.is_paused is False

    # Check stored events
    stored_session = shared_db.get_sessions(session_type=SessionType.AGENT)[0]
    assert stored_session.runs[0].events is not None
    assert len(stored_session.runs[0].events) == 6
    assert stored_session.runs[0].events[0].event == RunEvent.run_started
    assert stored_session.runs[0].events[1].event == RunEvent.run_paused
    assert stored_session.runs[0].events[2].event == RunEvent.run_continued
    assert stored_session.runs[0].events[3].event == RunEvent.tool_call_started
    assert stored_session.runs[0].events[4].event == RunEvent.tool_call_completed
    assert stored_session.runs[0].events[5].event == RunEvent.run_completed


def test_intermediate_steps_with_memory(shared_db):
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        enable_user_memories=True,
        telemetry=False,
    )

    response_generator = agent.run("Hello, how are you?", stream=True, stream_intermediate_steps=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.run_content,
        RunEvent.run_completed,
        RunEvent.memory_update_started,
        RunEvent.memory_update_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.run_completed]) == 1
    assert len(events[RunEvent.memory_update_started]) == 1
    assert len(events[RunEvent.memory_update_completed]) == 1


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

    response_generator = agent.run("Describe Elon Musk", stream=True, stream_intermediate_steps=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)
    run_response = agent.get_last_run_output()

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.run_content,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.run_content]) == 1
    assert len(events[RunEvent.run_completed]) == 1

    assert events[RunEvent.run_content][0].content is not None
    assert events[RunEvent.run_content][0].content_type == "Person"
    assert events[RunEvent.run_content][0].content.name == "Elon Musk"
    assert len(events[RunEvent.run_content][0].content.description) > 1

    assert events[RunEvent.run_completed][0].content is not None  # type: ignore
    assert events[RunEvent.run_completed][0].content_type == "Person"  # type: ignore
    assert events[RunEvent.run_completed][0].content.name == "Elon Musk"  # type: ignore
    assert len(events[RunEvent.run_completed][0].content.description) > 1  # type: ignore

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

    response_generator = agent.run("Describe Elon Musk", stream=True, stream_intermediate_steps=True)

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
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.parser_model_response_started]) == 1
    assert len(events[RunEvent.parser_model_response_completed]) == 1
    assert (
        len(events[RunEvent.run_content]) >= 2
    )  # The first model streams, then the parser model has a single content event
    assert len(events[RunEvent.run_completed]) == 1

    assert events[RunEvent.run_content][-1].content is not None
    assert events[RunEvent.run_content][-1].content_type == "Person"
    assert events[RunEvent.run_content][-1].content.name == "Elon Musk"
    assert len(events[RunEvent.run_content][-1].content.description) > 1

    assert events[RunEvent.run_completed][0].content is not None  # type: ignore
    assert events[RunEvent.run_completed][0].content_type == "Person"  # type: ignore
    assert events[RunEvent.run_completed][0].content.name == "Elon Musk"  # type: ignore
    assert len(events[RunEvent.run_completed][0].content.description) > 1  # type: ignore

    assert run_response.content is not None
    assert run_response.content_type == "Person"
    assert run_response.content["name"] == "Elon Musk"
