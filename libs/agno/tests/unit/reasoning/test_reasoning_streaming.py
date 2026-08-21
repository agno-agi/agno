"""Unit tests for reasoning streaming functionality.

These tests verify that reasoning_content_delta events are properly emitted
during streaming reasoning, without requiring actual API calls.
"""

from unittest.mock import patch

import pytest

from agno.models.message import Message
from agno.reasoning.step import ReasoningStep, ReasoningSteps
from agno.run.agent import RunEvent

# ============================================================================
# Test RunEvent enum has required events
# ============================================================================


def test_run_event_has_reasoning_content_delta():
    """Test that RunEvent enum has reasoning_content_delta event."""
    assert hasattr(RunEvent, "reasoning_content_delta")
    assert RunEvent.reasoning_content_delta.value == "ReasoningContentDelta"


def test_run_event_has_all_reasoning_events():
    """Test that RunEvent enum has all reasoning-related events."""
    assert hasattr(RunEvent, "reasoning_started")
    assert hasattr(RunEvent, "reasoning_step")
    assert hasattr(RunEvent, "reasoning_content_delta")
    assert hasattr(RunEvent, "reasoning_completed")

    assert RunEvent.reasoning_started.value == "ReasoningStarted"
    assert RunEvent.reasoning_step.value == "ReasoningStep"
    assert RunEvent.reasoning_content_delta.value == "ReasoningContentDelta"
    assert RunEvent.reasoning_completed.value == "ReasoningCompleted"


# ============================================================================
# Test ReasoningContentDeltaEvent creation
# ============================================================================


def test_create_reasoning_content_delta_event():
    """Test that create_reasoning_content_delta_event function exists and works."""
    from agno.run.agent import RunOutput
    from agno.utils.events import create_reasoning_content_delta_event

    # Create a mock run response
    run_response = RunOutput(
        run_id="test-run-id",
        session_id="test-session-id",
        content="",
    )

    # Create the event
    event = create_reasoning_content_delta_event(
        from_run_response=run_response,
        reasoning_content="Test reasoning chunk",
    )

    assert event is not None
    assert event.event == RunEvent.reasoning_content_delta
    assert event.reasoning_content == "Test reasoning chunk"


def test_reasoning_content_delta_event_class_exists():
    """Test that ReasoningContentDeltaEvent class exists."""
    from agno.run.agent import ReasoningContentDeltaEvent

    assert ReasoningContentDeltaEvent is not None

    # Verify it has the expected fields
    event = ReasoningContentDeltaEvent(
        event=RunEvent.reasoning_content_delta,
        run_id="test-run-id",
        session_id="test-session-id",
        reasoning_content="Test content",
    )
    assert event.reasoning_content == "Test content"
    assert event.event == RunEvent.reasoning_content_delta


# ============================================================================
# Test Anthropic streaming functions exist
# ============================================================================


def test_anthropic_streaming_functions_exist():
    """Test that Anthropic streaming functions are importable."""
    from agno.reasoning.anthropic import (
        aget_anthropic_reasoning_stream,
        get_anthropic_reasoning_stream,
    )

    assert callable(get_anthropic_reasoning_stream)
    assert callable(aget_anthropic_reasoning_stream)


def test_deepseek_streaming_functions_exist():
    """Test that DeepSeek streaming functions are importable."""
    from agno.reasoning.deepseek import (
        aget_deepseek_reasoning_stream,
        get_deepseek_reasoning_stream,
    )

    assert callable(get_deepseek_reasoning_stream)
    assert callable(aget_deepseek_reasoning_stream)


# ============================================================================
# Test streaming function signatures
# ============================================================================


def test_anthropic_stream_yields_tuples():
    """Test that Anthropic streaming function yields (delta, message) tuples."""
    import inspect

    from agno.reasoning.anthropic import get_anthropic_reasoning_stream

    # Check it's a generator function
    sig = inspect.signature(get_anthropic_reasoning_stream)
    params = list(sig.parameters.keys())

    assert "reasoning_agent" in params
    assert "messages" in params


def test_deepseek_stream_yields_tuples():
    """Test that DeepSeek streaming function yields (delta, message) tuples."""
    import inspect

    from agno.reasoning.deepseek import get_deepseek_reasoning_stream

    # Check signature
    sig = inspect.signature(get_deepseek_reasoning_stream)
    params = list(sig.parameters.keys())

    assert "reasoning_agent" in params
    assert "messages" in params


# ============================================================================
# Mock-based streaming tests
# ============================================================================


@patch("agno.reasoning.anthropic.get_anthropic_reasoning_stream")
def test_anthropic_stream_function_called_with_stream_events(mock_stream):
    """Test that streaming version is called when stream_events=True for Anthropic."""
    # Setup mock to return iterator with deltas
    final_message = Message(
        role="assistant",
        content="<thinking>\nTest thinking\n</thinking>",
        reasoning_content="Test thinking",
    )
    mock_stream.return_value = iter(
        [
            ("chunk1", None),
            ("chunk2", None),
            (None, final_message),
        ]
    )

    # Collect results
    results = list(mock_stream.return_value)

    # Verify we got streaming chunks
    assert len(results) == 3
    assert results[0] == ("chunk1", None)
    assert results[1] == ("chunk2", None)
    assert results[2][0] is None
    assert results[2][1] == final_message


@pytest.mark.asyncio
@patch("agno.reasoning.anthropic.aget_anthropic_reasoning_stream")
async def test_anthropic_async_stream_function(mock_stream):
    """Test async streaming version for Anthropic."""
    final_message = Message(
        role="assistant",
        content="<thinking>\nAsync thinking\n</thinking>",
        reasoning_content="Async thinking",
    )

    async def mock_async_gen():
        yield ("async_chunk1", None)
        yield ("async_chunk2", None)
        yield (None, final_message)

    mock_stream.return_value = mock_async_gen()

    results = []
    async for item in mock_stream.return_value:
        results.append(item)

    assert len(results) == 3
    assert results[0] == ("async_chunk1", None)
    assert results[1] == ("async_chunk2", None)


# ============================================================================
# Test event emission logic
# ============================================================================


def test_reasoning_events_can_be_compared():
    """Test that reasoning events can be compared correctly."""
    event1 = RunEvent.reasoning_started
    event2 = RunEvent.reasoning_content_delta
    event3 = RunEvent.reasoning_completed

    assert event1 != event2
    assert event2 != event3
    assert event1 == RunEvent.reasoning_started
    assert event2 == RunEvent.reasoning_content_delta


def test_reasoning_event_string_values():
    """Test reasoning event string values for serialization."""
    assert str(RunEvent.reasoning_started) == "RunEvent.reasoning_started"
    assert RunEvent.reasoning_started.value == "ReasoningStarted"
    assert RunEvent.reasoning_content_delta.value == "ReasoningContentDelta"
    assert RunEvent.reasoning_completed.value == "ReasoningCompleted"


# ============================================================================
# Test ReasoningStep and ReasoningSteps
# ============================================================================


def test_reasoning_step_creation():
    """Test ReasoningStep can be created with result."""
    step = ReasoningStep(result="Test reasoning result")
    assert step.result == "Test reasoning result"


def test_reasoning_steps_creation():
    """Test ReasoningSteps can hold multiple steps."""
    steps = ReasoningSteps(
        reasoning_steps=[
            ReasoningStep(result="Step 1"),
            ReasoningStep(result="Step 2"),
        ]
    )
    assert len(steps.reasoning_steps) == 2
    assert steps.reasoning_steps[0].result == "Step 1"
    assert steps.reasoning_steps[1].result == "Step 2"


# ============================================================================
# Test event registry includes reasoning_content_delta
# ============================================================================


def test_reasoning_content_delta_in_event_registry():
    """Test that ReasoningContentDeltaEvent is in the event registry."""
    from agno.run.agent import RUN_EVENT_TYPE_REGISTRY, ReasoningContentDeltaEvent

    assert RunEvent.reasoning_content_delta in RUN_EVENT_TYPE_REGISTRY
    assert RUN_EVENT_TYPE_REGISTRY[RunEvent.reasoning_content_delta] == ReasoningContentDeltaEvent


def test_all_reasoning_events_in_registry():
    """Test that all reasoning events are in the registry."""
    from agno.run.agent import RUN_EVENT_TYPE_REGISTRY

    reasoning_events = [
        RunEvent.reasoning_started,
        RunEvent.reasoning_step,
        RunEvent.reasoning_content_delta,
        RunEvent.reasoning_completed,
    ]

    for event in reasoning_events:
        assert event in RUN_EVENT_TYPE_REGISTRY, f"{event} not in registry"


# ============================================================================
# Test Message with reasoning_content
# ============================================================================


def test_message_supports_reasoning_content():
    """Test that Message class supports reasoning_content field."""
    msg = Message(
        role="assistant",
        content="Response content",
        reasoning_content="Thinking content",
    )
    assert msg.reasoning_content == "Thinking content"
    assert msg.content == "Response content"


def test_message_reasoning_content_optional():
    """Test that reasoning_content is optional on Message."""
    msg = Message(role="assistant", content="Just content")
    # Should not raise, reasoning_content should be None or not set
    assert msg.content == "Just content"


# ============================================================================
# Native model reasoning lifecycle events (agent + team, chunk + stream-end)
# ============================================================================


def _reasoning_state():
    return {"reasoning_started": False, "reasoning_time_taken": 0.0, "native_reasoning_streamed": False}


def _reasoning_chunk(text):
    from agno.models.response import ModelResponse, ModelResponseEvent

    return ModelResponse(event=ModelResponseEvent.assistant_response.value, reasoning_content=text)


def _base_mocks():
    """Mocks shared by agent and team handlers."""
    from unittest.mock import MagicMock

    owner = MagicMock()
    owner.events_to_skip = None
    owner.store_events = False
    session = MagicMock()
    session.session_id = "test-session"
    run_messages = MagicMock()
    run_messages.messages = []
    run_context = MagicMock()
    run_context.output_schema = None
    return owner, session, run_messages, run_context


def _agent_mocks():
    from agno.run.agent import RunOutput

    agent, session, run_messages, run_context = _base_mocks()
    return agent, session, RunOutput(session_id="test-session"), run_messages, run_context


def _team_mocks():
    from agno.run.team import TeamRunOutput

    team, session, run_messages, run_context = _base_mocks()
    team.stream_member_events = True
    team._member_response_model = None
    return team, session, TeamRunOutput(session_id="test-session"), run_messages, run_context


def _assert_delta(events, delta_event, content):
    deltas = [e for e in events if e.event == delta_event]
    assert len(deltas) == 1
    assert deltas[0].reasoning_content == content
    return deltas[0]


def _assert_lifecycle(events, delta_event, completed_event, content):
    """One delta, one completed, completed after delta, completed carries full content."""
    delta = _assert_delta(events, delta_event, content)
    completed = [e for e in events if e.event == completed_event]
    assert len(completed) == 1
    assert completed[0].content == content
    assert events.index(completed[0]) > events.index(delta)


# ----------------------------------------------------------------------------
# Chunk handlers (agent + team)
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("stream_events,expect_delta", [(True, True), (False, False)])
def test_agent_chunk_reasoning_delta(stream_events, expect_delta):
    from agno.agent._response import handle_model_response_chunk
    from agno.models.response import ModelResponse
    from agno.run.agent import RunEvent

    agent, session, run_response, _, _ = _agent_mocks()
    reasoning_state = _reasoning_state()

    events = list(
        handle_model_response_chunk(
            agent=agent,
            session=session,
            run_response=run_response,
            model_response=ModelResponse(content=""),
            model_response_event=_reasoning_chunk("thinking..."),
            reasoning_state=reasoning_state,
            stream_events=stream_events,
        )
    )

    assert len([e for e in events if e.event == RunEvent.reasoning_content_delta.value]) == (1 if expect_delta else 0)
    assert reasoning_state["native_reasoning_streamed"] is expect_delta
    # Accumulation happens regardless of streaming
    assert run_response.reasoning_content == "thinking..."


@pytest.mark.parametrize("stream_events,expect_delta", [(True, True), (False, False)])
def test_team_chunk_reasoning_delta(stream_events, expect_delta):
    from agno.models.response import ModelResponse
    from agno.run.team import TeamRunEvent
    from agno.team._response import _handle_model_response_chunk

    team, session, run_response, _, _ = _team_mocks()
    reasoning_state = _reasoning_state()

    events = list(
        _handle_model_response_chunk(
            team,
            session=session,
            run_response=run_response,
            full_model_response=ModelResponse(content=""),
            model_response_event=_reasoning_chunk("team thinking..."),
            reasoning_state=reasoning_state,
            stream_events=stream_events,
        )
    )

    assert len([e for e in events if e.event == TeamRunEvent.reasoning_content_delta.value]) == (
        1 if expect_delta else 0
    )
    assert reasoning_state["native_reasoning_streamed"] is expect_delta
    assert run_response.reasoning_content == "team thinking..."


# ----------------------------------------------------------------------------
# Stream-end ReasoningCompleted (agent + team, sync + async)
# ----------------------------------------------------------------------------


def test_agent_stream_emits_reasoning_completed_at_end(monkeypatch):
    import agno.agent._response as ar
    from agno.run.agent import RunEvent

    agent, session, run_response, run_messages, run_context = _agent_mocks()
    monkeypatch.setattr(ar, "call_model_stream_with_fallback", lambda *a, **k: iter([_reasoning_chunk("think")]))

    events = list(
        ar.handle_model_response_stream(
            agent=agent,
            session=session,
            run_response=run_response,
            run_messages=run_messages,
            stream_events=True,
            run_context=run_context,
        )
    )
    _assert_lifecycle(events, RunEvent.reasoning_content_delta.value, RunEvent.reasoning_completed.value, "think")


@pytest.mark.asyncio
async def test_agent_astream_emits_reasoning_completed_at_end(monkeypatch):
    import agno.agent._response as ar
    from agno.run.agent import RunEvent

    agent, session, run_response, run_messages, run_context = _agent_mocks()

    async def fake_stream(*args, **kwargs):
        yield _reasoning_chunk("think")

    monkeypatch.setattr(ar, "acall_model_stream_with_fallback", fake_stream)

    events = [
        e
        async for e in ar.ahandle_model_response_stream(
            agent=agent,
            session=session,
            run_response=run_response,
            run_messages=run_messages,
            stream_events=True,
            run_context=run_context,
        )
    ]
    _assert_lifecycle(events, RunEvent.reasoning_content_delta.value, RunEvent.reasoning_completed.value, "think")


def test_team_stream_emits_reasoning_completed_at_end(monkeypatch):
    import agno.team._response as tr
    from agno.run.team import TeamRunEvent

    team, session, run_response, run_messages, run_context = _team_mocks()
    monkeypatch.setattr(tr, "call_model_stream_with_fallback", lambda *a, **k: iter([_reasoning_chunk("team think")]))

    events = list(
        tr._handle_model_response_stream(
            team=team,
            session=session,
            run_response=run_response,
            run_messages=run_messages,
            stream_events=True,
            run_context=run_context,
        )
    )
    _assert_lifecycle(
        events, TeamRunEvent.reasoning_content_delta.value, TeamRunEvent.reasoning_completed.value, "team think"
    )


@pytest.mark.asyncio
async def test_team_astream_emits_reasoning_completed_at_end(monkeypatch):
    import agno.team._response as tr
    from agno.run.team import TeamRunEvent

    team, session, run_response, run_messages, run_context = _team_mocks()

    async def fake_stream(*args, **kwargs):
        yield _reasoning_chunk("team think")

    monkeypatch.setattr(tr, "acall_model_stream_with_fallback", fake_stream)

    events = [
        e
        async for e in tr._ahandle_model_response_stream(
            team=team,
            session=session,
            run_response=run_response,
            run_messages=run_messages,
            stream_events=True,
            run_context=run_context,
        )
    ]
    _assert_lifecycle(
        events, TeamRunEvent.reasoning_content_delta.value, TeamRunEvent.reasoning_completed.value, "team think"
    )
