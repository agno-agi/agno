"""Unit tests for reasoning streaming functionality.

These tests verify that reasoning_content_delta events are properly emitted
during streaming reasoning, without requiring actual API calls.
"""

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
