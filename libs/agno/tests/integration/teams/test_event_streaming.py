from textwrap import dedent

import pytest
from pydantic import BaseModel

from agno.agent import RunEvent
from agno.agent.agent import Agent
from agno.db.in_memory.in_memory_db import InMemoryDb
from agno.models.openai.chat import OpenAIChat
from agno.run.team import TeamRunInput, TeamRunOutput
from agno.team import Team, TeamRunEvent
from agno.tools.calculator import CalculatorTools
from agno.tools.decorator import tool
from agno.tools.reasoning import ReasoningTools
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools


def test_basic_events():
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        telemetry=False,
    )

    response_generator = team.run("Hello, how are you?", stream=True, stream_events=False)

    event_counts = {}
    for run_response in response_generator:
        event_counts[run_response.event] = event_counts.get(run_response.event, 0) + 1

    assert event_counts.keys() == {TeamRunEvent.run_content}

    assert event_counts[TeamRunEvent.run_content] > 1


@pytest.mark.asyncio
async def test_async_basic_events():
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        telemetry=False,
    )
    event_counts = {}
    async for run_response in team.arun("Hello, how are you?", stream=True, stream_events=False):
        event_counts[run_response.event] = event_counts.get(run_response.event, 0) + 1

    assert event_counts.keys() == {TeamRunEvent.run_content}

    assert event_counts[TeamRunEvent.run_content] > 1


def test_basic_intermediate_steps_events(shared_db):
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        db=shared_db,
        store_events=True,
        telemetry=False,
    )

    response_generator = team.run("Hello, how are you?", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        TeamRunEvent.run_started,
        TeamRunEvent.model_request_started,
        TeamRunEvent.model_request_completed,
        TeamRunEvent.run_content,
        TeamRunEvent.run_content_completed,
        TeamRunEvent.run_completed,
    }

    assert len(events[TeamRunEvent.run_started]) == 1
    assert events[TeamRunEvent.run_started][0].model == "gpt-4o-mini"
    assert events[TeamRunEvent.run_started][0].model_provider == "OpenAI"
    assert events[TeamRunEvent.run_started][0].session_id is not None
    assert events[TeamRunEvent.run_started][0].team_id is not None
    assert events[TeamRunEvent.run_started][0].run_id is not None
    assert events[TeamRunEvent.run_started][0].created_at is not None
    assert len(events[TeamRunEvent.run_content]) > 1
    assert len(events[TeamRunEvent.run_content_completed]) == 1
    assert len(events[TeamRunEvent.run_completed]) == 1

    team_completed_event = events[TeamRunEvent.run_completed][0]
    assert hasattr(team_completed_event, "metadata")
    assert hasattr(team_completed_event, "metrics")

    assert team_completed_event.metrics is not None
    assert team_completed_event.metrics.total_tokens > 0

    run_response_from_storage = team.get_last_run_output()

    assert run_response_from_storage is not None
    assert run_response_from_storage.events is not None
    assert len(run_response_from_storage.events) == 5, (
        "We should have run_started, model_request_started, model_request_completed, run_content_completed, and run_completed events"
    )
    assert run_response_from_storage.events[0].event == TeamRunEvent.run_started
    assert run_response_from_storage.events[1].event == TeamRunEvent.model_request_started
    assert run_response_from_storage.events[2].event == TeamRunEvent.model_request_completed
    assert run_response_from_storage.events[3].event == TeamRunEvent.run_content_completed
    assert run_response_from_storage.events[4].event == TeamRunEvent.run_completed

    persisted_team_completed_event = run_response_from_storage.events[4]
    assert hasattr(persisted_team_completed_event, "metadata")
    assert hasattr(persisted_team_completed_event, "metrics")

    assert persisted_team_completed_event.metrics is not None
    assert persisted_team_completed_event.metrics.total_tokens > 0


def test_intermediate_steps_with_tools(shared_db):
    team = Team(
        model=OpenAIChat(id="o3-mini"),
        members=[],
        tools=[YFinanceTools(cache_results=True)],
        db=shared_db,
        store_events=True,
        telemetry=False,
    )

    events = {}
    for run_response_delta in team.run("What is the stock price of Apple?", stream=True, stream_events=True):
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        TeamRunEvent.run_started,
        TeamRunEvent.model_request_started,
        TeamRunEvent.model_request_completed,
        TeamRunEvent.tool_call_started,
        TeamRunEvent.tool_call_completed,
        TeamRunEvent.run_content,
        TeamRunEvent.run_content_completed,
        TeamRunEvent.run_completed,
    }

    assert len(events[TeamRunEvent.tool_call_started]) >= 1
    # The team may first try to delegate the task to a member, then call the tool directly
    tool_names = [event.tool.tool_name for event in events[TeamRunEvent.tool_call_started]]
    assert "get_current_stock_price" in tool_names or "delegate_task_to_member" in tool_names
    assert len(events[TeamRunEvent.tool_call_completed]) >= 1
    # Check that at least one tool call completed successfully
    completed_tools = [event for event in events[TeamRunEvent.tool_call_completed] if event.content is not None]
    assert len(completed_tools) >= 1
    assert any(event.tool.result is not None for event in events[TeamRunEvent.tool_call_completed])

    run_response_from_storage = team.get_last_run_output()

    assert run_response_from_storage is not None
    assert run_response_from_storage.events is not None
    assert len(run_response_from_storage.events) >= 4
    # Check that we have the essential events (may have more due to member delegation)
    event_types = [event.event for event in run_response_from_storage.events]
    assert TeamRunEvent.run_started in event_types
    assert TeamRunEvent.tool_call_started in event_types
    assert TeamRunEvent.tool_call_completed in event_types
    assert TeamRunEvent.run_content_completed in event_types
    assert TeamRunEvent.run_completed in event_types


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
    )

    response_generator = team.run(
        "What is the sum of the first 10 natural numbers?",
        stream=True,
        stream_events=True,
    )

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        TeamRunEvent.run_started,
        TeamRunEvent.model_request_started,
        TeamRunEvent.model_request_completed,
        TeamRunEvent.tool_call_started,
        TeamRunEvent.tool_call_completed,
        TeamRunEvent.reasoning_started,
        TeamRunEvent.reasoning_completed,
        TeamRunEvent.reasoning_step,
        TeamRunEvent.run_content,
        TeamRunEvent.run_content_completed,
        TeamRunEvent.run_completed,
    }

    assert len(events[TeamRunEvent.run_started]) == 1
    assert len(events[TeamRunEvent.run_content]) > 1
    assert len(events[TeamRunEvent.run_content_completed]) == 1
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
    )

    response_generator = team.run("What is the weather in Tokyo?", stream=True, stream_events=True)

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
    response_generator = team.continue_run(run_id=run_id, updated_tools=updated_tools, stream=True, stream_events=True)

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
        TeamRunEvent.run_content,
        TeamRunEvent.run_completed,
    }

    assert len(events[TeamRunEvent.run_continued]) == 1
    assert len(events[TeamRunEvent.tool_call_started]) == 1
    assert events[TeamRunEvent.tool_call_started][0].tool.tool_name == "get_the_weather"
    assert len(events[TeamRunEvent.tool_call_completed]) == 1
    assert events[TeamRunEvent.tool_call_completed][0].content is not None
    assert events[TeamRunEvent.tool_call_completed][0].tool.result is not None
    assert len(events[TeamRunEvent.run_content]) > 1
    assert len(events[TeamRunEvent.run_completed]) == 1

    assert team.run_response.is_paused is False


def test_intermediate_steps_with_memory(shared_db):
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        db=shared_db,
        update_memory_on_run=True,
        telemetry=False,
    )

    response_generator = team.run("Hello, how are you?", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        TeamRunEvent.run_started,
        TeamRunEvent.model_request_started,
        TeamRunEvent.model_request_completed,
        TeamRunEvent.run_content,
        TeamRunEvent.run_content_completed,
        TeamRunEvent.run_completed,
        TeamRunEvent.memory_update_started,
        TeamRunEvent.memory_update_completed,
    }

    assert len(events[TeamRunEvent.run_started]) == 1
    assert len(events[TeamRunEvent.run_content]) > 1
    assert len(events[TeamRunEvent.run_content_completed]) == 1
    assert len(events[TeamRunEvent.run_completed]) == 1
    assert len(events[TeamRunEvent.memory_update_started]) == 1
    assert len(events[TeamRunEvent.memory_update_completed]) == 1


def test_intermediate_steps_with_session_summary(shared_db):
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        db=shared_db,
        enable_session_summaries=True,
        telemetry=False,
    )

    response_generator = team.run("Hello, how are you?", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        TeamRunEvent.run_started,
        TeamRunEvent.model_request_started,
        TeamRunEvent.model_request_completed,
        TeamRunEvent.run_content,
        TeamRunEvent.run_content_completed,
        TeamRunEvent.run_completed,
        TeamRunEvent.session_summary_started,
        TeamRunEvent.session_summary_completed,
    }

    assert len(events[TeamRunEvent.run_started]) == 1
    assert len(events[TeamRunEvent.run_content]) > 1
    assert len(events[TeamRunEvent.run_content_completed]) == 1
    assert len(events[TeamRunEvent.run_completed]) == 1
    assert len(events[TeamRunEvent.session_summary_started]) == 1
    assert len(events[TeamRunEvent.session_summary_completed]) == 1


def test_pre_hook_events_are_emitted(shared_db):
    """Test that the agent streams events."""

    def pre_hook_1(run_input: TeamRunInput) -> None:
        run_input.input_content += " (Modified by pre-hook 1)"

    def pre_hook_2(run_input: TeamRunInput) -> None:
        run_input.input_content += " (Modified by pre-hook 2)"

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        pre_hooks=[pre_hook_1, pre_hook_2],
        db=shared_db,
        telemetry=False,
    )

    response_generator = team.run("Hello, how are you?", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        TeamRunEvent.run_started,
        TeamRunEvent.model_request_started,
        TeamRunEvent.model_request_completed,
        TeamRunEvent.pre_hook_started,
        TeamRunEvent.pre_hook_completed,
        TeamRunEvent.run_content,
        TeamRunEvent.run_content_completed,
        TeamRunEvent.run_completed,
    }

    assert len(events[TeamRunEvent.run_started]) == 1
    assert len(events[TeamRunEvent.run_content]) > 1
    assert len(events[TeamRunEvent.run_content_completed]) == 1
    assert len(events[TeamRunEvent.run_completed]) == 1
    assert len(events[TeamRunEvent.pre_hook_started]) == 2
    assert len(events[TeamRunEvent.pre_hook_completed]) == 2
    assert events[TeamRunEvent.pre_hook_started][0].pre_hook_name == "pre_hook_1"
    assert events[TeamRunEvent.pre_hook_started][0].run_input.input_content == "Hello, how are you?"
    assert events[TeamRunEvent.pre_hook_completed][0].pre_hook_name == "pre_hook_1"
    assert (
        events[TeamRunEvent.pre_hook_completed][0].run_input.input_content
        == "Hello, how are you? (Modified by pre-hook 1)"
    )
    assert (
        events[TeamRunEvent.pre_hook_started][1].run_input.input_content
        == "Hello, how are you? (Modified by pre-hook 1)"
    )
    assert events[TeamRunEvent.pre_hook_started][1].pre_hook_name == "pre_hook_2"
    assert events[TeamRunEvent.pre_hook_completed][1].pre_hook_name == "pre_hook_2"
    assert (
        events[TeamRunEvent.pre_hook_completed][1].run_input.input_content
        == "Hello, how are you? (Modified by pre-hook 1) (Modified by pre-hook 2)"
    )


@pytest.mark.asyncio
async def test_async_pre_hook_events_are_emitted(shared_db):
    """Test that the agent streams events."""

    async def pre_hook_1(run_input: TeamRunInput) -> None:
        run_input.input_content += " (Modified by pre-hook 1)"

    async def pre_hook_2(run_input: TeamRunInput) -> None:
        run_input.input_content += " (Modified by pre-hook 2)"

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        pre_hooks=[pre_hook_1, pre_hook_2],
        db=shared_db,
        telemetry=False,
    )

    response_generator = team.arun("Hello, how are you?", stream=True, stream_events=True)

    events = {}
    async for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        TeamRunEvent.run_started,
        TeamRunEvent.model_request_started,
        TeamRunEvent.model_request_completed,
        TeamRunEvent.pre_hook_started,
        TeamRunEvent.pre_hook_completed,
        TeamRunEvent.run_content,
        TeamRunEvent.run_content_completed,
        TeamRunEvent.run_completed,
    }

    assert len(events[TeamRunEvent.run_started]) == 1
    assert len(events[TeamRunEvent.run_content]) > 1
    assert len(events[TeamRunEvent.run_content_completed]) == 1
    assert len(events[TeamRunEvent.run_completed]) == 1
    assert len(events[TeamRunEvent.pre_hook_started]) == 2
    assert len(events[TeamRunEvent.pre_hook_completed]) == 2
    assert events[TeamRunEvent.pre_hook_started][0].pre_hook_name == "pre_hook_1"
    assert events[TeamRunEvent.pre_hook_started][0].run_input.input_content == "Hello, how are you?"
    assert events[TeamRunEvent.pre_hook_completed][0].pre_hook_name == "pre_hook_1"
    assert (
        events[TeamRunEvent.pre_hook_completed][0].run_input.input_content
        == "Hello, how are you? (Modified by pre-hook 1)"
    )
    assert (
        events[TeamRunEvent.pre_hook_started][1].run_input.input_content
        == "Hello, how are you? (Modified by pre-hook 1)"
    )
    assert events[TeamRunEvent.pre_hook_started][1].pre_hook_name == "pre_hook_2"
    assert events[TeamRunEvent.pre_hook_completed][1].pre_hook_name == "pre_hook_2"
    assert (
        events[TeamRunEvent.pre_hook_completed][1].run_input.input_content
        == "Hello, how are you? (Modified by pre-hook 1) (Modified by pre-hook 2)"
    )


def test_post_hook_events_are_emitted(shared_db):
    """Test that post hook events are emitted correctly during streaming."""

    def post_hook_1(run_output: TeamRunOutput) -> None:
        run_output.content = str(run_output.content) + " (Modified by post-hook 1)"

    def post_hook_2(run_output: TeamRunOutput) -> None:
        run_output.content = str(run_output.content) + " (Modified by post-hook 2)"

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        post_hooks=[post_hook_1, post_hook_2],
        db=shared_db,
        telemetry=False,
    )

    response_generator = team.run("Hello, how are you?", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        TeamRunEvent.run_started,
        TeamRunEvent.model_request_started,
        TeamRunEvent.model_request_completed,
        TeamRunEvent.run_content,
        TeamRunEvent.run_content_completed,
        TeamRunEvent.post_hook_started,
        TeamRunEvent.post_hook_completed,
        TeamRunEvent.run_completed,
    }

    assert len(events[TeamRunEvent.run_started]) == 1
    assert len(events[TeamRunEvent.run_content]) > 1
    assert len(events[TeamRunEvent.run_content_completed]) == 1
    assert len(events[TeamRunEvent.run_completed]) == 1
    assert len(events[TeamRunEvent.post_hook_started]) == 2
    assert len(events[TeamRunEvent.post_hook_completed]) == 2

    # Verify first post hook
    assert events[TeamRunEvent.post_hook_started][0].post_hook_name == "post_hook_1"
    assert events[TeamRunEvent.post_hook_completed][0].post_hook_name == "post_hook_1"

    # Verify second post hook
    assert events[TeamRunEvent.post_hook_started][1].post_hook_name == "post_hook_2"
    assert events[TeamRunEvent.post_hook_completed][1].post_hook_name == "post_hook_2"

    # Verify final output includes modifications from both hooks
    final_event = events[TeamRunEvent.run_completed][0]
    assert "(Modified by post-hook 1)" in str(final_event.content)
    assert "(Modified by post-hook 2)" in str(final_event.content)


@pytest.mark.asyncio
async def test_async_post_hook_events_are_emitted(shared_db):
    """Test that async post hook events are emitted correctly during streaming."""

    async def post_hook_1(run_output: TeamRunOutput) -> None:
        run_output.content = str(run_output.content) + " (Modified by async post-hook 1)"

    async def post_hook_2(run_output: TeamRunOutput) -> None:
        run_output.content = str(run_output.content) + " (Modified by async post-hook 2)"

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        post_hooks=[post_hook_1, post_hook_2],
        db=shared_db,
        telemetry=False,
    )

    response_generator = team.arun("Hello, how are you?", stream=True, stream_events=True)

    events = {}
    async for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        TeamRunEvent.run_started,
        TeamRunEvent.model_request_started,
        TeamRunEvent.model_request_completed,
        TeamRunEvent.run_content,
        TeamRunEvent.run_content_completed,
        TeamRunEvent.post_hook_started,
        TeamRunEvent.post_hook_completed,
        TeamRunEvent.run_completed,
    }

    assert len(events[TeamRunEvent.run_started]) == 1
    assert len(events[TeamRunEvent.run_content]) > 1
    assert len(events[TeamRunEvent.run_content_completed]) == 1
    assert len(events[TeamRunEvent.run_completed]) == 1
    assert len(events[TeamRunEvent.post_hook_started]) == 2
    assert len(events[TeamRunEvent.post_hook_completed]) == 2

    # Verify first post hook
    assert events[TeamRunEvent.post_hook_started][0].post_hook_name == "post_hook_1"
    assert events[TeamRunEvent.post_hook_completed][0].post_hook_name == "post_hook_1"

    # Verify second post hook
    assert events[TeamRunEvent.post_hook_started][1].post_hook_name == "post_hook_2"
    assert events[TeamRunEvent.post_hook_completed][1].post_hook_name == "post_hook_2"

    # Verify final output includes modifications from both hooks
    final_event = events[TeamRunEvent.run_completed][0]
    assert "(Modified by async post-hook 1)" in str(final_event.content)
    assert "(Modified by async post-hook 2)" in str(final_event.content)


def test_pre_and_post_hook_events_are_emitted(shared_db):
    """Test that both pre and post hook events are emitted correctly during streaming."""

    def pre_hook(run_input: TeamRunInput) -> None:
        run_input.input_content += " (Modified by pre-hook)"

    def post_hook(run_output: TeamRunOutput) -> None:
        run_output.content = str(run_output.content) + " (Modified by post-hook)"

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        pre_hooks=[pre_hook],
        post_hooks=[post_hook],
        db=shared_db,
        telemetry=False,
    )

    response_generator = team.run("Hello", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        TeamRunEvent.run_started,
        TeamRunEvent.model_request_started,
        TeamRunEvent.model_request_completed,
        TeamRunEvent.pre_hook_started,
        TeamRunEvent.pre_hook_completed,
        TeamRunEvent.run_content,
        TeamRunEvent.run_content_completed,
        TeamRunEvent.post_hook_started,
        TeamRunEvent.post_hook_completed,
        TeamRunEvent.run_completed,
    }

    # Verify pre hook events
    assert len(events[TeamRunEvent.pre_hook_started]) == 1
    assert len(events[TeamRunEvent.pre_hook_completed]) == 1
    assert events[TeamRunEvent.pre_hook_started][0].pre_hook_name == "pre_hook"
    assert events[TeamRunEvent.pre_hook_completed][0].pre_hook_name == "pre_hook"

    # Verify post hook events
    assert len(events[TeamRunEvent.post_hook_started]) == 1
    assert len(events[TeamRunEvent.post_hook_completed]) == 1
    assert events[TeamRunEvent.post_hook_started][0].post_hook_name == "post_hook"
    assert events[TeamRunEvent.post_hook_completed][0].post_hook_name == "post_hook"

    # Verify final output includes modifications
    final_event = events[TeamRunEvent.run_completed][0]
    assert "(Modified by post-hook)" in str(final_event.content)


def test_intermediate_steps_with_structured_output(shared_db):
    """Test that the agent streams events."""

    class Person(BaseModel):
        name: str
        description: str
        age: int

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        db=shared_db,
        output_schema=Person,
        instructions="You have no members, answer directly",
        telemetry=False,
    )

    response_generator = team.run("Describe Elon Musk", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        TeamRunEvent.run_started,
        TeamRunEvent.model_request_started,
        TeamRunEvent.model_request_completed,
        TeamRunEvent.run_content,
        TeamRunEvent.run_content_completed,
        TeamRunEvent.run_completed,
    }

    assert len(events[TeamRunEvent.run_started]) == 1
    assert len(events[TeamRunEvent.run_content]) == 1
    assert len(events[TeamRunEvent.run_content_completed]) == 1
    assert len(events[TeamRunEvent.run_completed]) == 1

    assert events[TeamRunEvent.run_content][0].content is not None
    assert events[TeamRunEvent.run_content][0].content_type == "Person"
    assert events[TeamRunEvent.run_content][0].content.name == "Elon Musk"
    assert len(events[TeamRunEvent.run_content][0].content.description) > 1

    assert events[TeamRunEvent.run_completed][0].content is not None
    assert events[TeamRunEvent.run_completed][0].content_type == "Person"
    assert events[TeamRunEvent.run_completed][0].content.name == "Elon Musk"
    assert len(events[TeamRunEvent.run_completed][0].content.description) > 1

    team_completed_event_structured = events[TeamRunEvent.run_completed][0]
    assert team_completed_event_structured.metrics is not None
    assert team_completed_event_structured.metrics.total_tokens > 0


def test_intermediate_steps_with_parser_model(shared_db):
    """Test that the agent streams events."""

    class Person(BaseModel):
        name: str
        description: str
        age: int

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        db=shared_db,
        output_schema=Person,
        parser_model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You have no members, answer directly",
        telemetry=False,
    )

    response_generator = team.run("Describe Elon Musk", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    run_response = team.get_last_run_output()

    assert events.keys() == {
        TeamRunEvent.run_started,
        TeamRunEvent.model_request_started,
        TeamRunEvent.model_request_completed,
        TeamRunEvent.parser_model_response_started,
        TeamRunEvent.parser_model_response_completed,
        TeamRunEvent.run_content,
        TeamRunEvent.run_content_completed,
        TeamRunEvent.run_completed,
    }

    assert len(events[TeamRunEvent.run_started]) == 1
    assert len(events[TeamRunEvent.parser_model_response_started]) == 1
    assert len(events[TeamRunEvent.parser_model_response_completed]) == 1
    assert (
        len(events[TeamRunEvent.run_content]) >= 2
    )  # The first model streams, then the parser model has a single content event
    assert len(events[TeamRunEvent.run_content_completed]) == 1
    assert len(events[TeamRunEvent.run_completed]) == 1

    assert events[TeamRunEvent.run_content][-1].content is not None
    assert events[TeamRunEvent.run_content][-1].content_type == "Person"
    # Handle both dict and Pydantic model cases
    content = events[TeamRunEvent.run_content][-1].content
    if isinstance(content, dict):
        assert content["name"] == "Elon Musk"
        assert len(content["description"]) > 1
    else:
        assert content.name == "Elon Musk"
        assert len(content.description) > 1

    assert events[TeamRunEvent.run_completed][0].content is not None
    assert events[TeamRunEvent.run_completed][0].content_type == "Person"
    # Handle both dict and Pydantic model cases
    completed_content = events[TeamRunEvent.run_completed][0].content
    if isinstance(completed_content, dict):
        assert completed_content["name"] == "Elon Musk"
        assert len(completed_content["description"]) > 1
    else:
        assert completed_content.name == "Elon Musk"
        assert len(completed_content.description) > 1

    assert run_response.content is not None
    assert run_response.content_type == "Person"
    # Handle both dict and Pydantic model cases
    response_content = run_response.content
    if isinstance(response_content, dict):
        assert response_content["name"] == "Elon Musk"
        assert len(response_content["description"]) > 1
    else:
        assert response_content.name == "Elon Musk"
        assert len(response_content.description) > 1


def test_intermediate_steps_with_member_agents():
    agent_1 = Agent(
        name="Analyst",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are an expert problem-solving assistant with strong analytical skills! 🧠",
        tools=[ReasoningTools(add_instructions=True)],
    )
    agent_2 = Agent(
        name="Math Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You can do Math!",
        tools=[CalculatorTools()],
    )
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent_1, agent_2],
        telemetry=False,
    )

    response_generator = team.run(
        "Analyse and then solve the problem: 'solve 10 factorial'", stream=True, stream_events=True
    )

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        TeamRunEvent.run_started,
        TeamRunEvent.model_request_started,
        TeamRunEvent.model_request_completed,
        TeamRunEvent.tool_call_started,
        RunEvent.run_started,
        RunEvent.model_request_started,
        RunEvent.model_request_completed,
        RunEvent.tool_call_started,
        RunEvent.tool_call_completed,
        RunEvent.reasoning_started,
        RunEvent.reasoning_step,
        RunEvent.reasoning_completed,
        RunEvent.run_content,
        RunEvent.run_content_completed,
        RunEvent.run_completed,
        TeamRunEvent.tool_call_completed,
        TeamRunEvent.run_content,
        TeamRunEvent.run_content_completed,
        TeamRunEvent.run_completed,
    }

    assert len(events[TeamRunEvent.run_started]) == 1
    # Transfer twice, from team to member agents
    assert len(events[TeamRunEvent.tool_call_started]) == 2
    assert events[TeamRunEvent.tool_call_started][0].tool.tool_name == "delegate_task_to_member"
    assert events[TeamRunEvent.tool_call_started][0].tool.tool_args["member_id"] == "analyst"
    assert events[TeamRunEvent.tool_call_started][1].tool.tool_name == "delegate_task_to_member"
    assert events[TeamRunEvent.tool_call_started][1].tool.tool_args["member_id"] == "math-agent"
    assert len(events[TeamRunEvent.tool_call_completed]) == 2
    assert events[TeamRunEvent.tool_call_completed][0].tool.tool_name == "delegate_task_to_member"
    assert events[TeamRunEvent.tool_call_completed][0].tool.result is not None
    assert events[TeamRunEvent.tool_call_completed][1].tool.tool_name == "delegate_task_to_member"
    assert events[TeamRunEvent.tool_call_completed][1].tool.result is not None
    assert len(events[TeamRunEvent.run_content]) > 1
    assert len(events[TeamRunEvent.run_content_completed]) == 1
    assert len(events[TeamRunEvent.run_completed]) == 1
    # Two member agents
    assert len(events[RunEvent.run_started]) == 2
    assert events[RunEvent.run_started][0].parent_run_id == events[TeamRunEvent.run_started][0].run_id
    assert events[RunEvent.run_started][1].parent_run_id == events[TeamRunEvent.run_started][0].run_id
    assert len(events[RunEvent.run_completed]) == 2
    assert events[RunEvent.run_completed][0].parent_run_id == events[TeamRunEvent.run_completed][0].run_id
    assert events[RunEvent.run_completed][1].parent_run_id == events[TeamRunEvent.run_completed][0].run_id
    # Lots of member tool calls
    assert len(events[RunEvent.tool_call_started]) > 1
    assert len(events[RunEvent.tool_call_completed]) > 1
    assert len(events[RunEvent.reasoning_started]) == 1
    assert len(events[RunEvent.reasoning_completed]) == 1
    assert len(events[RunEvent.reasoning_step]) > 1
    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.run_content_completed]) >= 1


def test_intermediate_steps_with_member_agents_only_member_events():
    agent_math = Agent(
        name="Math Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You can do Math!",
        tools=[CalculatorTools()],
    )
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent_math],
        telemetry=False,
        stream_member_events=True,
    )

    response_generator = team.run(
        "Analyse and then solve the problem: 'solve 10 factorial'",
        stream=True,
        stream_events=False,  # stream_events=False to only stream member events
    )

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
        TeamRunEvent.run_content,
    }

    # Agent content restreamed as team content
    assert len(events[TeamRunEvent.run_content]) > 1

    assert len(events[RunEvent.run_started]) == 1
    assert len(events[RunEvent.tool_call_started]) == 1
    assert len(events[RunEvent.tool_call_completed]) == 1
    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.run_content_completed]) == 1
    assert len(events[RunEvent.run_completed]) == 1
    # Two member agents
    assert len(events[RunEvent.run_started]) == 1
    assert events[RunEvent.run_started][0].parent_run_id == events[TeamRunEvent.run_content][0].run_id
    assert len(events[RunEvent.run_completed]) == 1
    assert events[RunEvent.run_completed][0].parent_run_id == events[TeamRunEvent.run_content][0].run_id
    # Lots of member tool calls
    assert len(events[RunEvent.tool_call_started]) == 1
    assert len(events[RunEvent.tool_call_completed]) == 1
    assert len(events[RunEvent.run_content]) > 1
    assert len(events[RunEvent.run_content_completed]) == 1


def test_intermediate_steps_with_member_agents_nested_team():
    agent_1 = Agent(
        name="Finance Analyst",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are an expert finance analyst with strong analytical skills! 🧠",
        tools=[YFinanceTools(cache_results=True)],
    )
    sub_team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        name="News Team",
        members=[],
        tools=[WebSearchTools(cache_results=True)],
        telemetry=False,
    )
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent_1, sub_team],
        tools=[ReasoningTools(add_instructions=True)],
        telemetry=False,
    )

    response_generator = team.run("Do a stock market analysis for Apple.", stream=True, stream_events=True)

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    # Core events that must always be present
    required_events = {
        TeamRunEvent.run_started.value,
        TeamRunEvent.model_request_started.value,
        TeamRunEvent.model_request_completed.value,
        TeamRunEvent.tool_call_started.value,
        TeamRunEvent.tool_call_completed.value,
        RunEvent.run_started.value,
        RunEvent.model_request_started.value,
        RunEvent.model_request_completed.value,
        RunEvent.run_content.value,
        RunEvent.run_content_completed.value,
        RunEvent.run_completed.value,
        TeamRunEvent.run_content.value,
        TeamRunEvent.run_content_completed.value,
        TeamRunEvent.run_completed.value,
    }
    # Reasoning events are optional - model may or may not use the reasoning tool
    optional_reasoning_events = {
        TeamRunEvent.reasoning_started.value,
        TeamRunEvent.reasoning_step.value,
        TeamRunEvent.reasoning_completed.value,
    }
    # Member agent tool events are optional - depends on delegation
    optional_member_tool_events = {
        RunEvent.tool_call_started.value,
        RunEvent.tool_call_completed.value,
    }

    actual_events = set(events.keys())
    # Check that all required events are present
    assert required_events.issubset(actual_events), f"Missing required events: {required_events - actual_events}"
    # Check that actual events are within the expected set (required + optional)
    all_expected = required_events | optional_reasoning_events | optional_member_tool_events
    unexpected_events = actual_events - all_expected
    assert not unexpected_events, f"Unexpected events: {unexpected_events}"


def test_intermediate_steps_with_member_agents_streaming_off():
    agent_1 = Agent(
        name="Analyst",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are an expert problem-solving assistant with strong analytical skills! 🧠",
        tools=[ReasoningTools(add_instructions=True)],
    )
    agent_2 = Agent(
        name="Math Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You can do Math!",
        tools=[CalculatorTools()],
    )
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent_1, agent_2],
        telemetry=False,
        stream_member_events=False,
    )

    response_generator = team.run(
        "Analyse and then solve the problem: 'solve 10 factorial'", stream=True, stream_events=True
    )

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert events.keys() == {
        TeamRunEvent.run_started,
        TeamRunEvent.model_request_started,
        TeamRunEvent.model_request_completed,
        TeamRunEvent.tool_call_started,
        TeamRunEvent.tool_call_completed,
        TeamRunEvent.run_content,
        TeamRunEvent.run_content_completed,
        TeamRunEvent.run_completed,
    }

    assert len(events[TeamRunEvent.run_started]) == 1
    # Transfer twice, from team to member agents
    assert len(events[TeamRunEvent.tool_call_started]) == 2
    assert events[TeamRunEvent.tool_call_started][0].tool.tool_name == "delegate_task_to_member"
    assert events[TeamRunEvent.tool_call_started][0].tool.tool_args["member_id"] == "analyst"
    assert events[TeamRunEvent.tool_call_started][1].tool.tool_name == "delegate_task_to_member"
    assert events[TeamRunEvent.tool_call_started][1].tool.tool_args["member_id"] == "math-agent"
    assert len(events[TeamRunEvent.tool_call_completed]) == 2
    assert events[TeamRunEvent.tool_call_completed][0].tool.tool_name == "delegate_task_to_member"
    assert events[TeamRunEvent.tool_call_completed][0].tool.result is not None
    assert events[TeamRunEvent.tool_call_completed][1].tool.tool_name == "delegate_task_to_member"
    assert events[TeamRunEvent.tool_call_completed][1].tool.result is not None
    assert len(events[TeamRunEvent.run_content]) > 1
    assert len(events[TeamRunEvent.run_completed]) == 1


def test_intermediate_steps_with_member_agents_delegate_to_all_members():
    def get_news_from_hackernews(query: str):
        return "The best way to learn to code is to use the Hackernews API."

    def get_news_from_duckduckgo(query: str):
        return "The best way to learn to code is to use the DuckDuckGo API."

    agent_1 = Agent(
        name="Web Researcher",
        model=OpenAIChat(id="o3-mini"),
        instructions="You are an expert web researcher with strong analytical skills! Use your tools to find answers to questions.",
        tools=[get_news_from_duckduckgo],
        stream_events=True,
    )
    agent_2 = Agent(
        name="Hackernews Researcher",
        model=OpenAIChat(id="o3-mini"),
        instructions="You are an expert hackernews researcher with strong analytical skills! Use your tools to find answers to questions.",
        tools=[get_news_from_hackernews],
        stream_events=True,
    )
    team = Team(
        model=OpenAIChat(id="o3-mini"),
        members=[agent_1, agent_2],
        telemetry=False,
        delegate_to_all_members=True,
        instructions="You are a discussion master. Forward the task to the member agents.",
    )

    response_generator = team.run(
        input="Start the discussion on the topic: 'What is the best way to learn to code?'",
        stream=True,
        stream_events=True,
    )

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert len(events[TeamRunEvent.run_started]) == 1

    # Assert expected events from team
    assert len(events[TeamRunEvent.tool_call_started]) == 1
    assert len(events[TeamRunEvent.run_content]) > 1
    assert len(events[TeamRunEvent.run_completed]) == 1

    # Assert expected tool call events
    assert events[TeamRunEvent.tool_call_started][0].tool.tool_name == "delegate_task_to_members"
    assert len(events[TeamRunEvent.tool_call_completed]) == 1
    assert events[TeamRunEvent.tool_call_completed][0].tool.tool_name == "delegate_task_to_members"
    assert events[TeamRunEvent.tool_call_completed][0].tool.result is not None

    # Assert expected events from members
    assert len(events[RunEvent.run_started]) == 2
    assert len(events[RunEvent.run_completed]) == 2
    assert len(events[RunEvent.run_content]) > 1


def test_tool_parent_run_id():
    agent_1 = Agent(
        name="Big questions agent",
        model=OpenAIChat(id="gpt-5-mini"),
        instructions="You answer big questions.",
    )
    team = Team(
        model=OpenAIChat(id="gpt-5-mini"),
        members=[agent_1],
        db=InMemoryDb(),
        instructions="Delegate to your member agents to answer the question.",
    )

    response_generator = team.run(
        input="What is the meaning of life?",
        session_id="test_session",
        stream=True,
        stream_events=True,
    )

    events = {}
    for run_response_delta in response_generator:
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert len(events[TeamRunEvent.run_started]) == 1
    assert len(events[TeamRunEvent.run_completed]) == 1

    # Model may delegate multiple times depending on its behavior
    assert len(events[TeamRunEvent.tool_call_started]) >= 1
    assert len(events[TeamRunEvent.tool_call_completed]) >= 1

    team_session = team.get_session(session_id="test_session")
    assert team_session is not None
    team_run = team_session.get_run(run_id=events[TeamRunEvent.run_started][0].run_id)
    assert team_run is not None
    member_run = team_session.get_run(run_id=events[RunEvent.run_started][0].run_id)
    assert member_run is not None
    assert member_run.parent_run_id == team_run.run_id

    # Assert expected tool call events - check the first delegate call
    assert events[TeamRunEvent.tool_call_started][0].tool.tool_name == "delegate_task_to_member"
    assert events[TeamRunEvent.tool_call_started][0].run_id == member_run.parent_run_id
    assert events[TeamRunEvent.tool_call_completed][0].tool.tool_name == "delegate_task_to_member"
    assert events[TeamRunEvent.tool_call_completed][0].run_id == member_run.parent_run_id
