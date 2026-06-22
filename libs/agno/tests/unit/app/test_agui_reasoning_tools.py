import pytest
from ag_ui.core import EventType

from agno.os.interfaces.agui.utils import async_stream_agno_response_as_agui_events
from agno.reasoning.step import ReasoningStep
from agno.run.agent import (
    ReasoningCompletedEvent,
    ReasoningContentDeltaEvent,
    ReasoningStartedEvent,
    ReasoningStepEvent,
    RunCompletedEvent,
    RunContentEvent,
)


def _check_no_reasoning_inside_text_message(event_types: list) -> None:
    """Verify REASONING_START never occurs between TEXT_MESSAGE_START and TEXT_MESSAGE_END."""
    text_start_indices = [i for i, t in enumerate(event_types) if t == EventType.TEXT_MESSAGE_START]
    text_end_indices = [i for i, t in enumerate(event_types) if t == EventType.TEXT_MESSAGE_END]
    reasoning_start_indices = [i for i, t in enumerate(event_types) if t == EventType.REASONING_START]

    for text_start_idx in text_start_indices:
        matching_end_indices = [i for i in text_end_indices if i > text_start_idx]
        if matching_end_indices:
            text_end_idx = min(matching_end_indices)
            violating = [i for i in reasoning_start_indices if text_start_idx < i < text_end_idx]
            assert not violating, f"REASONING_START at {violating} between TEXT_MESSAGE_START and END"


@pytest.mark.asyncio
async def test_reasoning_started_closes_open_text_message():
    async def mock_stream():
        text1 = RunContentEvent()
        text1.content = "Let me think..."
        yield text1

        yield ReasoningStartedEvent()

        step = ReasoningStepEvent()
        step.content = ReasoningStep(title="Analyze", reasoning="Thinking...")
        step.reasoning_content = "## Analyze\nThinking..."
        yield step

        yield ReasoningCompletedEvent()

        text2 = RunContentEvent()
        text2.content = "The answer is 42."
        yield text2

        yield RunCompletedEvent()

    events = []
    async for event in async_stream_agno_response_as_agui_events(mock_stream(), "thread_1", "run_1"):
        events.append(event)

    event_types = [e.type for e in events]

    assert EventType.REASONING_START in event_types
    assert EventType.TEXT_MESSAGE_START in event_types
    assert EventType.TEXT_MESSAGE_END in event_types

    _check_no_reasoning_inside_text_message(event_types)


@pytest.mark.asyncio
async def test_reasoning_content_delta_closes_open_text_message():
    async def mock_stream():
        text1 = RunContentEvent()
        text1.content = "Processing..."
        yield text1

        delta = ReasoningContentDeltaEvent()
        delta.reasoning_content = "Thinking about the problem..."
        yield delta

        yield ReasoningCompletedEvent()

        text2 = RunContentEvent()
        text2.content = "Done."
        yield text2

        yield RunCompletedEvent()

    events = []
    async for event in async_stream_agno_response_as_agui_events(mock_stream(), "thread_1", "run_1"):
        events.append(event)

    event_types = [e.type for e in events]

    assert EventType.REASONING_START in event_types
    _check_no_reasoning_inside_text_message(event_types)


@pytest.mark.asyncio
async def test_reasoning_step_closes_open_text_message():
    async def mock_stream():
        text1 = RunContentEvent()
        text1.content = "Analyzing..."
        yield text1

        step = ReasoningStepEvent()
        step.content = ReasoningStep(title="Step 1", reasoning="First step...")
        step.reasoning_content = "## Step 1\nFirst step..."
        yield step

        yield ReasoningCompletedEvent()
        yield RunCompletedEvent()

    events = []
    async for event in async_stream_agno_response_as_agui_events(mock_stream(), "thread_1", "run_1"):
        events.append(event)

    event_types = [e.type for e in events]

    assert EventType.REASONING_START in event_types
    _check_no_reasoning_inside_text_message(event_types)
