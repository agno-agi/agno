from textwrap import dedent

import pytest
from pydantic import BaseModel

from agno.agent.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.run.response import RunEvent
from agno.tools.decorator import tool
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools


def test_basic_events():
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
        monitoring=False,
    )

    response_generator = agent.run("Hello, how are you?", stream=True, stream_intermediate_steps=False)

    event_counts = {}
    for run_response in response_generator:
        event_counts[run_response.event] = event_counts.get(run_response.event, 0) + 1

    assert event_counts.keys() == {RunEvent.run_response_content}

    assert event_counts[RunEvent.run_response_content] > 1


@pytest.mark.asyncio
async def test_async_basic_events():
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
        monitoring=False,
    )
    response_generator = await agent.arun("Hello, how are you?", stream=True, stream_intermediate_steps=False)

    event_counts = {}
    async for run_response in response_generator:
        event_counts[run_response.event] = event_counts.get(run_response.event, 0) + 1

    assert event_counts.keys() == {RunEvent.run_response_content}

    assert event_counts[RunEvent.run_response_content] > 1


def test_basic_intermediate_steps_events():
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
        monitoring=False,
    )

    response_generator = agent.run("Hello, how are you?", stream=True, stream_intermediate_steps=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {RunEvent.run_started, RunEvent.run_response_content, RunEvent.run_completed}

    assert len(events[RunEvent.run_started]) == 1
    assert events[RunEvent.run_started][0].model == "gpt-4o-mini"
    assert events[RunEvent.run_started][0].model_provider == "OpenAI"
    assert events[RunEvent.run_started][0].session_id is not None
    assert events[RunEvent.run_started][0].agent_id is not None
    assert events[RunEvent.run_started][0].run_id is not None
    assert events[RunEvent.run_started][0].created_at is not None
    assert len(events[RunEvent.run_response_content]) > 1
    assert len(events[RunEvent.run_completed]) == 1


def test_basic_intermediate_steps_events_persisted(agent_storage):
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
        store_events=True,
        telemetry=False,
        monitoring=False,
    )

    response_generator = agent.run("Hello, how are you?", stream=True, stream_intermediate_steps=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {RunEvent.run_started, RunEvent.run_response_content, RunEvent.run_completed}

    run_response_from_storage = agent_storage.get_all_sessions()[0].memory["runs"][0]

    assert run_response_from_storage["events"] is not None
    assert len(run_response_from_storage["events"]) == 2, "We should only have the run started and run completed events"
    assert run_response_from_storage["events"][0]["event"] == RunEvent.run_started
    assert run_response_from_storage["events"][1]["event"] == RunEvent.run_completed


def test_intermediate_steps_with_tools():
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[YFinanceTools(cache_results=True)],
        telemetry=False,
        monitoring=False,
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
        RunEvent.run_response_content,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.run_response_content]) > 1
    assert len(events[RunEvent.run_completed]) == 1
    assert len(events[RunEvent.tool_call_started]) == 1
    assert events[RunEvent.tool_call_started][0].tool.tool_name == "get_current_stock_price"
    assert len(events[RunEvent.tool_call_completed]) == 1
    assert events[RunEvent.tool_call_completed][0].content is not None
    assert events[RunEvent.tool_call_completed][0].tool.result is not None


def test_intermediate_steps_with_tools_events_persisted(agent_storage):
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[YFinanceTools(cache_results=True)],
        storage=agent_storage,
        store_events=True,
        telemetry=False,
        monitoring=False,
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
        RunEvent.run_response_content,
        RunEvent.run_completed,
    }

    run_response_from_storage = agent_storage.get_all_sessions()[0].memory["runs"][0]

    assert run_response_from_storage["events"] is not None
    assert len(run_response_from_storage["events"]) == 4
    assert run_response_from_storage["events"][0]["event"] == RunEvent.run_started
    assert run_response_from_storage["events"][1]["event"] == RunEvent.tool_call_started
    assert run_response_from_storage["events"][2]["event"] == RunEvent.tool_call_completed
    assert run_response_from_storage["events"][3]["event"] == RunEvent.run_completed


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
        monitoring=False,
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
        RunEvent.run_response_content,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.run_response_content]) > 1
    assert len(events[RunEvent.run_completed]) == 1
    assert len(events[RunEvent.tool_call_started]) > 1
    assert len(events[RunEvent.tool_call_completed]) > 1
    assert len(events[RunEvent.reasoning_started]) == 1
    assert len(events[RunEvent.reasoning_completed]) == 1
    assert events[RunEvent.reasoning_completed][0].content is not None
    assert events[RunEvent.reasoning_completed][0].content_type == "ReasoningSteps"
    assert len(events[RunEvent.reasoning_step]) > 1
    assert events[RunEvent.reasoning_step][0].content is not None
    assert events[RunEvent.reasoning_step][0].content_type == "ReasoningStep"
    assert events[RunEvent.reasoning_step][0].reasoning_content is not None


def test_intermediate_steps_with_user_confirmation(agent_storage):
    """Test that the agent streams events."""

    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        storage=agent_storage,
        store_events=True,
        add_history_to_messages=True,
        num_history_responses=2,
        telemetry=False,
        monitoring=False,
    )

    response_generator = agent.run("What is the weather in Tokyo?", stream=True, stream_intermediate_steps=True)

    # First until we hit a pause
    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {RunEvent.run_started, RunEvent.run_paused}

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.run_paused]) == 1
    assert events[RunEvent.run_paused][0].tools[0].requires_confirmation is True

    assert agent.is_paused

    assert agent.run_response.tools[0].requires_confirmation

    # Mark the tool as confirmed
    updated_tools = agent.run_response.tools
    run_id = agent.run_response.run_id
    updated_tools[0].confirmed = True

    # Check stored events
    stored_session = agent_storage.get_all_sessions()[0]
    assert stored_session.memory["runs"][0]["events"] is not None
    assert len(stored_session.memory["runs"][0]["events"]) == 2
    assert stored_session.memory["runs"][0]["events"][0]["event"] == RunEvent.run_started
    assert stored_session.memory["runs"][0]["events"][1]["event"] == RunEvent.run_paused

    # Then we continue the run
    response_generator = agent.continue_run(
        run_id=run_id, updated_tools=updated_tools, stream=True, stream_intermediate_steps=True
    )

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert agent.run_response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"

    assert events.keys() == {
        RunEvent.run_continued,
        RunEvent.tool_call_started,
        RunEvent.tool_call_completed,
        RunEvent.run_response_content,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_continued]) == 1
    assert len(events[RunEvent.tool_call_started]) == 1
    assert events[RunEvent.tool_call_started][0].tool.tool_name == "get_the_weather"
    assert len(events[RunEvent.tool_call_completed]) == 1
    assert events[RunEvent.tool_call_completed][0].content is not None
    assert events[RunEvent.tool_call_completed][0].tool.result is not None
    assert len(events[RunEvent.run_response_content]) > 1
    assert len(events[RunEvent.run_completed]) == 1

    assert agent.run_response.is_paused is False

    # Check stored events
    stored_session = agent_storage.get_all_sessions()[0]
    assert stored_session.memory["runs"][0]["events"] is not None
    assert len(stored_session.memory["runs"][0]["events"]) == 6
    assert stored_session.memory["runs"][0]["events"][0]["event"] == RunEvent.run_started
    assert stored_session.memory["runs"][0]["events"][1]["event"] == RunEvent.run_paused
    assert stored_session.memory["runs"][0]["events"][2]["event"] == RunEvent.run_continued
    assert stored_session.memory["runs"][0]["events"][3]["event"] == RunEvent.tool_call_started
    assert stored_session.memory["runs"][0]["events"][4]["event"] == RunEvent.tool_call_completed
    assert stored_session.memory["runs"][0]["events"][5]["event"] == RunEvent.run_completed


def test_intermediate_steps_with_memory(agent_storage, memory):
    """Test that the agent streams events."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        memory=memory,
        storage=agent_storage,
        enable_user_memories=True,
        telemetry=False,
        monitoring=False,
    )

    response_generator = agent.run("Hello, how are you?", stream=True, stream_intermediate_steps=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.run_response_content,
        RunEvent.run_completed,
        RunEvent.memory_update_started,
        RunEvent.memory_update_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.run_response_content]) > 1
    assert len(events[RunEvent.run_completed]) == 1
    assert len(events[RunEvent.memory_update_started]) == 1
    assert len(events[RunEvent.memory_update_completed]) == 1


def test_intermediate_steps_with_structured_output(agent_storage):
    """Test that the agent streams events."""

    class Person(BaseModel):
        name: str
        description: str
        age: int

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
        response_model=Person,
        telemetry=False,
        monitoring=False,
    )

    response_generator = agent.run("Describe Elon Musk", stream=True, stream_intermediate_steps=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.run_response_content,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.run_response_content]) == 1
    assert len(events[RunEvent.run_completed]) == 1

    assert events[RunEvent.run_response_content][0].content is not None
    assert events[RunEvent.run_response_content][0].content_type == "Person"
    assert events[RunEvent.run_response_content][0].content.name == "Elon Musk"
    assert len(events[RunEvent.run_response_content][0].content.description) > 1

    assert events[RunEvent.run_completed][0].content is not None
    assert events[RunEvent.run_completed][0].content_type == "Person"
    assert events[RunEvent.run_completed][0].content.name == "Elon Musk"
    assert len(events[RunEvent.run_completed][0].content.description) > 1

    assert agent.run_response.content is not None
    assert agent.run_response.content_type == "Person"
    assert agent.run_response.content.name == "Elon Musk"


def test_intermediate_steps_with_parser_model(agent_storage):
    """Test that the agent streams events."""

    class Person(BaseModel):
        name: str
        description: str
        age: int

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
        response_model=Person,
        parser_model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
        monitoring=False,
    )

    response_generator = agent.run("Describe Elon Musk", stream=True, stream_intermediate_steps=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        RunEvent.run_started,
        RunEvent.parser_model_response_started,
        RunEvent.parser_model_response_completed,
        RunEvent.run_response_content,
        RunEvent.run_completed,
    }

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.parser_model_response_started]) == 1
    assert len(events[RunEvent.parser_model_response_completed]) == 1
    assert (
        len(events[RunEvent.run_response_content]) >= 2
    )  # The first model streams, then the parser model has a single content event
    assert len(events[RunEvent.run_completed]) == 1

    assert events[RunEvent.run_response_content][-1].content is not None
    assert events[RunEvent.run_response_content][-1].content_type == "Person"
    assert events[RunEvent.run_response_content][-1].content.name == "Elon Musk"
    assert len(events[RunEvent.run_response_content][-1].content.description) > 1

    assert events[RunEvent.run_completed][0].content is not None
    assert events[RunEvent.run_completed][0].content_type == "Person"
    assert events[RunEvent.run_completed][0].content.name == "Elon Musk"
    assert len(events[RunEvent.run_completed][0].content.description) > 1

    assert agent.run_response.content is not None
    assert agent.run_response.content_type == "Person"
    assert agent.run_response.content.name == "Elon Musk"
