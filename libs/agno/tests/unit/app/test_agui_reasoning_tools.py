import re

import pytest
from ag_ui.core import EventType

from agno.models.message import Citations
from agno.models.response import ToolExecution
from agno.os.interfaces.agui.stream import async_stream_agno_response_as_agui_events
from agno.reasoning.step import ReasoningStep
from agno.run.agent import (
    ReasoningCompletedEvent,
    ReasoningContentDeltaEvent,
    ReasoningStartedEvent,
    ReasoningStepEvent,
    RunCompletedEvent,
    RunContentEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent


async def _collect(stream) -> list:
    return [event async for event in async_stream_agno_response_as_agui_events(stream, "thread_1", "run_1")]


class _ReasoningSteps:
    """Builds ReasoningStepEvents carrying a title and a thought, with reasoning_content
    accumulated across the events one builder instance produced.

    Parity with the producer stops there. The reasoning-tools path accumulates reasoning_content
    the same way for a step of that shape, but it also fills action, confidence and next_action on
    the step, and the reasoning manager path derives reasoning_content differently again.
    """

    def __init__(self) -> None:
        self._reasoning_content = ""

    def event(self, title: str, reasoning: str) -> ReasoningStepEvent:
        self._reasoning_content += f"## {title}\n{reasoning}\n\n"
        step = ReasoningStepEvent()
        step.content = ReasoningStep(title=title, reasoning=reasoning)
        step.reasoning_content = self._reasoning_content
        return step


def _deltas(events: list, event_type: EventType) -> str:
    return "".join(e.delta for e in events if e.type == event_type)


def _span_events(events: list) -> list:
    span_types = {
        EventType.REASONING_START,
        EventType.REASONING_MESSAGE_START,
        EventType.REASONING_MESSAGE_CONTENT,
        EventType.REASONING_MESSAGE_END,
        EventType.REASONING_END,
        EventType.TEXT_MESSAGE_START,
        EventType.TEXT_MESSAGE_CONTENT,
        EventType.TEXT_MESSAGE_END,
    }
    return [(e.type, e.message_id) for e in events if e.type in span_types]


def _message_deltas(events: list, event_type: EventType) -> list:
    """Ordered (message_id, delta) pairs, so a span fragmented across ids cannot pass as one."""
    return [(e.message_id, e.delta) for e in events if e.type == event_type]


def _span_id_at(span_events: list, position: int) -> str:
    """Message id of the span event at this position, reported as an assertion when it is missing."""
    assert len(span_events) > position, f"expected a span event at position {position}, got {span_events}"
    return span_events[position][1]


def _span_id_of(span_events: list, event_type: EventType, occurrence: int = 0, other_than: str = "") -> str:
    """Message id of the nth span event of this type, reported as an assertion when it is missing."""
    message_ids = [mid for kind, mid in span_events if kind == event_type and mid != other_than]
    assert len(message_ids) > occurrence, f"expected {occurrence + 1} or more {event_type}, got {span_events}"
    return message_ids[occurrence]


def _first_event(events: list, event_type: EventType):
    """First event of this type, reported as an assertion when it is missing."""
    matching = [e for e in events if e.type == event_type]
    assert matching, f"expected a {event_type}, got {[e.type for e in events]}"
    return matching[0]


def _span_end_position(events: list, start_position: int, end_type: EventType) -> int:
    """Position of the end event closing the span opened at start_position, paired by message id."""
    start = events[start_position]
    end_positions = [
        i
        for i, e in enumerate(events)
        if i > start_position and e.type == end_type and e.message_id == start.message_id
    ]
    assert end_positions, f"{start.type} for {start.message_id} at {start_position} never ends"
    return min(end_positions)


def _check_no_reasoning_inside_text_message(events: list) -> None:
    """Verify REASONING_START never occurs inside a text message span, paired by message id."""
    reasoning_start_positions = [i for i, e in enumerate(events) if e.type == EventType.REASONING_START]

    for text_start_position, event in enumerate(events):
        if event.type != EventType.TEXT_MESSAGE_START:
            continue
        text_end_position = _span_end_position(events, text_start_position, EventType.TEXT_MESSAGE_END)
        violating = [i for i in reasoning_start_positions if text_start_position < i < text_end_position]
        assert not violating, f"REASONING_START at {violating} inside text message {event.message_id}"


def _check_no_text_inside_reasoning(events: list) -> None:
    """Verify TEXT_MESSAGE_START never occurs inside a reasoning message span, paired by message id."""
    text_start_positions = [i for i, e in enumerate(events) if e.type == EventType.TEXT_MESSAGE_START]

    for reasoning_start_position, event in enumerate(events):
        if event.type != EventType.REASONING_MESSAGE_START:
            continue
        reasoning_end_position = _span_end_position(events, reasoning_start_position, EventType.REASONING_MESSAGE_END)
        violating = [i for i in text_start_positions if reasoning_start_position < i < reasoning_end_position]
        assert not violating, f"TEXT_MESSAGE_START at {violating} inside reasoning message {event.message_id}"


@pytest.mark.asyncio
async def test_reasoning_started_closes_open_text_message():
    async def mock_stream():
        text1 = RunContentEvent()
        text1.content = "Let me think..."
        yield text1

        yield ReasoningStartedEvent()

        yield _ReasoningSteps().event(title="Analyze", reasoning="Thinking...")

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

    _check_no_reasoning_inside_text_message(events)


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
    _check_no_reasoning_inside_text_message(events)


@pytest.mark.asyncio
async def test_reasoning_step_closes_open_text_message():
    async def mock_stream():
        text1 = RunContentEvent()
        text1.content = "Analyzing..."
        yield text1

        yield _ReasoningSteps().event(title="Analyze", reasoning="First step...")

        yield ReasoningCompletedEvent()
        yield RunCompletedEvent()

    events = []
    async for event in async_stream_agno_response_as_agui_events(mock_stream(), "thread_1", "run_1"):
        events.append(event)

    event_types = [e.type for e in events]

    assert EventType.REASONING_START in event_types
    _check_no_reasoning_inside_text_message(events)


@pytest.mark.asyncio
async def test_native_reasoning_on_run_content_reaches_agui():
    """Providers that stream reasoning summaries deliver them on RunContent, not as reasoning events."""

    async def mock_stream():
        for delta in ("Weighing ", "the ", "options."):
            reasoning_chunk = RunContentEvent()
            reasoning_chunk.reasoning_content = delta
            yield reasoning_chunk

        answer = RunContentEvent()
        answer.content = "The answer is 42."
        yield answer

        yield RunCompletedEvent()

    events = await _collect(mock_stream())
    span_events = _span_events(events)

    reasoning_id = _span_id_at(span_events, 0)
    text_id = _span_id_of(span_events, EventType.TEXT_MESSAGE_START)

    assert span_events == [
        (EventType.REASONING_START, reasoning_id),
        (EventType.REASONING_MESSAGE_START, reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_id),
        (EventType.REASONING_MESSAGE_END, reasoning_id),
        (EventType.REASONING_END, reasoning_id),
        (EventType.TEXT_MESSAGE_START, text_id),
        (EventType.TEXT_MESSAGE_CONTENT, text_id),
        (EventType.TEXT_MESSAGE_END, text_id),
    ]
    assert reasoning_id != text_id

    # RUN_FINISHED is the only event outside the spans asserted above
    assert len(events) == len(span_events) + 1
    assert events[-1].type == EventType.RUN_FINISHED

    assert _message_deltas(events, EventType.REASONING_MESSAGE_CONTENT) == [
        (reasoning_id, "Weighing "),
        (reasoning_id, "the "),
        (reasoning_id, "options."),
    ]
    assert _message_deltas(events, EventType.TEXT_MESSAGE_CONTENT) == [(text_id, "The answer is 42.")]


@pytest.mark.asyncio
async def test_native_reasoning_survives_several_tool_calls_in_one_turn():
    async def mock_stream():
        first_reasoning = RunContentEvent()
        first_reasoning.reasoning_content = "I need two lookups."
        yield first_reasoning

        weather = ToolExecution(tool_call_id="tc_1", tool_name="get_weather", tool_args={"city": "London"})
        population = ToolExecution(tool_call_id="tc_2", tool_name="get_population", tool_args={"city": "London"})

        yield ToolCallStartedEvent(tool=weather)
        yield ToolCallStartedEvent(tool=population)

        weather.result = "15C"
        yield ToolCallCompletedEvent(tool=weather)
        population.result = "8900000"
        yield ToolCallCompletedEvent(tool=population)

        second_reasoning = RunContentEvent()
        second_reasoning.reasoning_content = "Both results are in."
        yield second_reasoning

        answer = RunContentEvent()
        answer.content = "Cold and crowded."
        yield answer

        yield RunCompletedEvent()

    events = await _collect(mock_stream())
    event_types = [e.type for e in events]
    span_events = _span_events(events)

    first_reasoning_id = _span_id_at(span_events, 0)
    second_reasoning_id = _span_id_of(span_events, EventType.REASONING_START, other_than=first_reasoning_id)
    parent_id = _span_id_of(span_events, EventType.TEXT_MESSAGE_START)
    answer_id = _span_id_of(span_events, EventType.TEXT_MESSAGE_START, other_than=parent_id)

    assert event_types == [
        EventType.REASONING_START,
        EventType.REASONING_MESSAGE_START,
        EventType.REASONING_MESSAGE_CONTENT,
        EventType.REASONING_MESSAGE_END,
        EventType.REASONING_END,
        EventType.TEXT_MESSAGE_START,
        EventType.TEXT_MESSAGE_END,
        EventType.TOOL_CALL_START,
        EventType.TOOL_CALL_ARGS,
        EventType.TOOL_CALL_START,
        EventType.TOOL_CALL_ARGS,
        EventType.TOOL_CALL_END,
        EventType.TOOL_CALL_RESULT,
        EventType.TOOL_CALL_END,
        EventType.TOOL_CALL_RESULT,
        EventType.REASONING_START,
        EventType.REASONING_MESSAGE_START,
        EventType.REASONING_MESSAGE_CONTENT,
        EventType.REASONING_MESSAGE_END,
        EventType.REASONING_END,
        EventType.TEXT_MESSAGE_START,
        EventType.TEXT_MESSAGE_CONTENT,
        EventType.TEXT_MESSAGE_END,
        EventType.RUN_FINISHED,
    ]

    assert span_events == [
        (EventType.REASONING_START, first_reasoning_id),
        (EventType.REASONING_MESSAGE_START, first_reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, first_reasoning_id),
        (EventType.REASONING_MESSAGE_END, first_reasoning_id),
        (EventType.REASONING_END, first_reasoning_id),
        (EventType.TEXT_MESSAGE_START, parent_id),
        (EventType.TEXT_MESSAGE_END, parent_id),
        (EventType.REASONING_START, second_reasoning_id),
        (EventType.REASONING_MESSAGE_START, second_reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, second_reasoning_id),
        (EventType.REASONING_MESSAGE_END, second_reasoning_id),
        (EventType.REASONING_END, second_reasoning_id),
        (EventType.TEXT_MESSAGE_START, answer_id),
        (EventType.TEXT_MESSAGE_CONTENT, answer_id),
        (EventType.TEXT_MESSAGE_END, answer_id),
    ]

    assert len({first_reasoning_id, second_reasoning_id, parent_id, answer_id}) == 4

    assert [(e.type, e.tool_call_id) for e in events if getattr(e, "tool_call_id", None) is not None] == [
        (EventType.TOOL_CALL_START, "tc_1"),
        (EventType.TOOL_CALL_ARGS, "tc_1"),
        (EventType.TOOL_CALL_START, "tc_2"),
        (EventType.TOOL_CALL_ARGS, "tc_2"),
        (EventType.TOOL_CALL_END, "tc_1"),
        (EventType.TOOL_CALL_RESULT, "tc_1"),
        (EventType.TOOL_CALL_END, "tc_2"),
        (EventType.TOOL_CALL_RESULT, "tc_2"),
    ]

    # Both tool calls hang off the empty message minted once the first reasoning span closed
    assert [e.parent_message_id for e in events if e.type == EventType.TOOL_CALL_START] == [parent_id, parent_id]

    assert _message_deltas(events, EventType.REASONING_MESSAGE_CONTENT) == [
        (first_reasoning_id, "I need two lookups."),
        (second_reasoning_id, "Both results are in."),
    ]
    assert _message_deltas(events, EventType.TEXT_MESSAGE_CONTENT) == [(answer_id, "Cold and crowded.")]


@pytest.mark.asyncio
async def test_native_reasoning_on_team_run_content_reaches_agui():
    async def mock_stream():
        reasoning_chunk = TeamRunContentEvent()
        reasoning_chunk.reasoning_content = "Delegating."
        yield reasoning_chunk

        answer = TeamRunContentEvent()
        answer.content = "Done."
        yield answer

        yield TeamRunCompletedEvent()

    events = await _collect(mock_stream())
    span_events = _span_events(events)

    reasoning_id = _span_id_at(span_events, 0)
    text_id = _span_id_of(span_events, EventType.TEXT_MESSAGE_START)

    assert span_events == [
        (EventType.REASONING_START, reasoning_id),
        (EventType.REASONING_MESSAGE_START, reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_id),
        (EventType.REASONING_MESSAGE_END, reasoning_id),
        (EventType.REASONING_END, reasoning_id),
        (EventType.TEXT_MESSAGE_START, text_id),
        (EventType.TEXT_MESSAGE_CONTENT, text_id),
        (EventType.TEXT_MESSAGE_END, text_id),
    ]
    assert reasoning_id != text_id

    assert len(events) == len(span_events) + 1
    assert events[-1].type == EventType.RUN_FINISHED

    assert _message_deltas(events, EventType.REASONING_MESSAGE_CONTENT) == [(reasoning_id, "Delegating.")]
    assert _message_deltas(events, EventType.TEXT_MESSAGE_CONTENT) == [(text_id, "Done.")]


@pytest.mark.asyncio
async def test_run_completed_while_reasoning_is_open_closes_the_span():
    """A run that ends before any assistant text must still close the reasoning span it left open."""

    async def mock_stream():
        for delta in ("Still ", "thinking."):
            reasoning_chunk = RunContentEvent()
            reasoning_chunk.reasoning_content = delta
            yield reasoning_chunk

        yield RunCompletedEvent()

    events = await _collect(mock_stream())
    span_events = _span_events(events)

    reasoning_id = _span_id_at(span_events, 0)

    assert span_events == [
        (EventType.REASONING_START, reasoning_id),
        (EventType.REASONING_MESSAGE_START, reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_id),
        (EventType.REASONING_MESSAGE_END, reasoning_id),
        (EventType.REASONING_END, reasoning_id),
    ]

    assert [e.type for e in events[-3:]] == [
        EventType.REASONING_MESSAGE_END,
        EventType.REASONING_END,
        EventType.RUN_FINISHED,
    ]
    assert len(events) == len(span_events) + 1

    assert _message_deltas(events, EventType.REASONING_MESSAGE_CONTENT) == [
        (reasoning_id, "Still "),
        (reasoning_id, "thinking."),
    ]


@pytest.mark.asyncio
async def test_reasoning_mirroring_the_answer_is_not_emitted_as_reasoning():
    """Providers that mirror the assistant text into reasoning_content must not produce a reasoning span."""

    async def mock_stream():
        for delta in ("The ", "answer ", "is 42."):
            chunk = RunContentEvent()
            chunk.content = delta
            chunk.reasoning_content = delta
            yield chunk

        yield RunCompletedEvent()

    events = await _collect(mock_stream())
    event_types = [e.type for e in events]

    assert event_types == [
        EventType.TEXT_MESSAGE_START,
        EventType.TEXT_MESSAGE_CONTENT,
        EventType.TEXT_MESSAGE_CONTENT,
        EventType.TEXT_MESSAGE_CONTENT,
        EventType.TEXT_MESSAGE_END,
        EventType.RUN_FINISHED,
    ]

    message_ids = {e.message_id for e in events if e.type == EventType.TEXT_MESSAGE_CONTENT}
    assert len(message_ids) == 1
    assert _deltas(events, EventType.TEXT_MESSAGE_CONTENT) == "The answer is 42."


@pytest.mark.asyncio
async def test_reasoning_started_ends_a_span_already_open():
    """A reasoning-started event arriving mid-span must close that span instead of orphaning it."""

    async def mock_stream():
        native_reasoning = RunContentEvent()
        native_reasoning.reasoning_content = "Native thinking."
        yield native_reasoning

        yield ReasoningStartedEvent()

        delta = ReasoningContentDeltaEvent()
        delta.reasoning_content = "Structured thinking."
        yield delta

        yield ReasoningCompletedEvent()

        answer = RunContentEvent()
        answer.content = "The answer is 42."
        yield answer

        yield RunCompletedEvent()

    events = await _collect(mock_stream())
    span_events = _span_events(events)

    first_id = _span_id_at(span_events, 0)
    second_id = _span_id_of(span_events, EventType.REASONING_START, other_than=first_id)
    text_id = _span_id_of(span_events, EventType.TEXT_MESSAGE_START)

    assert span_events == [
        (EventType.REASONING_START, first_id),
        (EventType.REASONING_MESSAGE_START, first_id),
        (EventType.REASONING_MESSAGE_CONTENT, first_id),
        (EventType.REASONING_MESSAGE_END, first_id),
        (EventType.REASONING_END, first_id),
        (EventType.REASONING_START, second_id),
        (EventType.REASONING_MESSAGE_START, second_id),
        (EventType.REASONING_MESSAGE_CONTENT, second_id),
        (EventType.REASONING_MESSAGE_END, second_id),
        (EventType.REASONING_END, second_id),
        (EventType.TEXT_MESSAGE_START, text_id),
        (EventType.TEXT_MESSAGE_CONTENT, text_id),
        (EventType.TEXT_MESSAGE_END, text_id),
    ]

    assert len({first_id, second_id, text_id}) == 3

    assert len(events) == len(span_events) + 1
    assert events[-1].type == EventType.RUN_FINISHED

    started = [mid for kind, mid in span_events if kind == EventType.REASONING_START]
    ended = [mid for kind, mid in span_events if kind == EventType.REASONING_END]
    message_started = [mid for kind, mid in span_events if kind == EventType.REASONING_MESSAGE_START]
    message_ended = [mid for kind, mid in span_events if kind == EventType.REASONING_MESSAGE_END]

    assert started == ended
    assert message_started == message_ended
    assert len(set(started)) == 2


@pytest.mark.asyncio
async def test_tool_call_with_existing_parent_message_keeps_the_reasoning_span_open():
    """A tool call parents to the existing assistant message and leaves the reasoning span open."""

    async def mock_stream():
        answer = RunContentEvent()
        answer.content = "Let me check the forecast."
        yield answer

        reasoning_chunk = RunContentEvent()
        reasoning_chunk.reasoning_content = "I should look up the weather."
        yield reasoning_chunk

        weather = ToolExecution(tool_call_id="tc_1", tool_name="get_weather", tool_args={"city": "London"})
        yield ToolCallStartedEvent(tool=weather)

        weather.result = "15C"
        yield ToolCallCompletedEvent(tool=weather)

        yield RunCompletedEvent()

    events = await _collect(mock_stream())
    event_types = [e.type for e in events]

    assert event_types == [
        EventType.TEXT_MESSAGE_START,
        EventType.TEXT_MESSAGE_CONTENT,
        EventType.TEXT_MESSAGE_END,
        EventType.REASONING_START,
        EventType.REASONING_MESSAGE_START,
        EventType.REASONING_MESSAGE_CONTENT,
        EventType.TOOL_CALL_START,
        EventType.TOOL_CALL_ARGS,
        EventType.TOOL_CALL_END,
        EventType.TOOL_CALL_RESULT,
        EventType.REASONING_MESSAGE_END,
        EventType.REASONING_END,
        EventType.RUN_FINISHED,
    ]

    # The existing assistant message parents the tool call, so no synthetic message is minted
    text_start = _first_event(events, EventType.TEXT_MESSAGE_START)
    tool_start = _first_event(events, EventType.TOOL_CALL_START)
    assert tool_start.parent_message_id == text_start.message_id

    _check_no_text_inside_reasoning(events)


@pytest.mark.asyncio
async def test_reasoning_tools_tool_calls_do_not_split_the_reasoning_span():
    """ReasoningTools interleaves think calls with steps. The think calls must not end the reasoning span, so
    all three steps land in one reasoning message, and the step headings run 1, 2, 3."""

    async def mock_stream():
        steps = _ReasoningSteps()
        for index in (1, 2, 3):
            think = ToolExecution(
                tool_call_id=f"tc_{index}",
                tool_name="think",
                tool_args={"thought": f"thought {index}"},
            )
            yield ToolCallStartedEvent(tool=think)

            think.result = "ok"
            yield ToolCallCompletedEvent(tool=think)

            yield steps.event(title=f"Consider {index}", reasoning=f"Reasoning {index}")

        answer = RunContentEvent()
        answer.content = "The answer is 42."
        yield answer

        yield RunCompletedEvent()

    events = await _collect(mock_stream())
    span_events = _span_events(events)

    parent_id = _span_id_at(span_events, 0)
    reasoning_id = _span_id_of(span_events, EventType.REASONING_START)
    answer_id = _span_id_of(span_events, EventType.TEXT_MESSAGE_START, other_than=parent_id)

    assert [e.type for e in events] == [
        EventType.TEXT_MESSAGE_START,
        EventType.TEXT_MESSAGE_END,
        EventType.TOOL_CALL_START,
        EventType.TOOL_CALL_ARGS,
        EventType.TOOL_CALL_END,
        EventType.TOOL_CALL_RESULT,
        EventType.REASONING_START,
        EventType.REASONING_MESSAGE_START,
        EventType.REASONING_MESSAGE_CONTENT,
        EventType.TOOL_CALL_START,
        EventType.TOOL_CALL_ARGS,
        EventType.TOOL_CALL_END,
        EventType.TOOL_CALL_RESULT,
        EventType.REASONING_MESSAGE_CONTENT,
        EventType.TOOL_CALL_START,
        EventType.TOOL_CALL_ARGS,
        EventType.TOOL_CALL_END,
        EventType.TOOL_CALL_RESULT,
        EventType.REASONING_MESSAGE_CONTENT,
        EventType.REASONING_MESSAGE_END,
        EventType.REASONING_END,
        EventType.TEXT_MESSAGE_START,
        EventType.TEXT_MESSAGE_CONTENT,
        EventType.TEXT_MESSAGE_END,
        EventType.RUN_FINISHED,
    ]

    assert span_events == [
        (EventType.TEXT_MESSAGE_START, parent_id),
        (EventType.TEXT_MESSAGE_END, parent_id),
        (EventType.REASONING_START, reasoning_id),
        (EventType.REASONING_MESSAGE_START, reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_id),
        (EventType.REASONING_MESSAGE_END, reasoning_id),
        (EventType.REASONING_END, reasoning_id),
        (EventType.TEXT_MESSAGE_START, answer_id),
        (EventType.TEXT_MESSAGE_CONTENT, answer_id),
        (EventType.TEXT_MESSAGE_END, answer_id),
    ]

    assert len({parent_id, reasoning_id, answer_id}) == 3

    # Every think call hangs off the one synthetic parent minted before the span opened
    assert [e.parent_message_id for e in events if e.type == EventType.TOOL_CALL_START] == [parent_id] * 3

    reasoning_text = _deltas(events, EventType.REASONING_MESSAGE_CONTENT)
    assert reasoning_text.count("## Step 1: Consider 1") == 1
    assert reasoning_text.count("## Step 2: Consider 2") == 1
    assert reasoning_text.count("## Step 3: Consider 3") == 1
    assert _deltas(events, EventType.TEXT_MESSAGE_CONTENT) == "The answer is 42."


@pytest.mark.asyncio
async def test_reasoning_step_numbering_is_per_run_not_per_span():
    """Numbering counts steps in the turn, not in the span. Assistant text between steps closes the
    span, so each step lands in a span of its own, and the count must keep going up all the same."""

    async def mock_stream():
        steps = _ReasoningSteps()
        for index in (1, 2, 3):
            yield steps.event(title=f"Consider {index}", reasoning=f"Reasoning {index}")

            partial = RunContentEvent()
            partial.content = f"Partial {index}. "
            yield partial

        yield RunCompletedEvent()

    events = await _collect(mock_stream())
    span_events = _span_events(events)

    # Each step opens its own span, so the alternation really did reset-test the counter
    reasoning_ids = [mid for kind, mid in span_events if kind == EventType.REASONING_START]
    assert len(set(reasoning_ids)) == 3, f"expected three distinct reasoning spans, got {span_events}"

    reasoning_text = _deltas(events, EventType.REASONING_MESSAGE_CONTENT)
    headings = re.findall(r"## Step \d+: Consider \d+", reasoning_text)
    assert headings == [
        "## Step 1: Consider 1",
        "## Step 2: Consider 2",
        "## Step 3: Consider 3",
    ]

    assert _deltas(events, EventType.TEXT_MESSAGE_CONTENT) == "Partial 1. Partial 2. Partial 3. "

    _check_no_reasoning_inside_text_message(events)
    _check_no_text_inside_reasoning(events)


@pytest.mark.asyncio
async def test_content_less_chunk_does_not_split_the_reasoning_span():
    """A chunk carrying only citations must not end the reasoning span or open an empty message inside it."""

    async def mock_stream():
        first_reasoning = RunContentEvent()
        first_reasoning.reasoning_content = "Weighing "
        yield first_reasoning

        citations_only = RunContentEvent()
        citations_only.citations = Citations(raw=[{"url": "https://example.com"}])
        yield citations_only

        second_reasoning = RunContentEvent()
        second_reasoning.reasoning_content = "the options."
        yield second_reasoning

        answer = RunContentEvent()
        answer.content = "The answer is 42."
        yield answer

        yield RunCompletedEvent()

    events = await _collect(mock_stream())
    span_events = _span_events(events)

    reasoning_id = _span_id_at(span_events, 0)
    text_id = _span_id_of(span_events, EventType.TEXT_MESSAGE_START)

    assert span_events == [
        (EventType.REASONING_START, reasoning_id),
        (EventType.REASONING_MESSAGE_START, reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_id),
        (EventType.REASONING_MESSAGE_END, reasoning_id),
        (EventType.REASONING_END, reasoning_id),
        (EventType.TEXT_MESSAGE_START, text_id),
        (EventType.TEXT_MESSAGE_CONTENT, text_id),
        (EventType.TEXT_MESSAGE_END, text_id),
    ]

    assert reasoning_id != text_id

    assert len(events) == len(span_events) + 1
    assert events[-1].type == EventType.RUN_FINISHED

    assert _deltas(events, EventType.REASONING_MESSAGE_CONTENT) == "Weighing the options."
    assert _deltas(events, EventType.TEXT_MESSAGE_CONTENT) == "The answer is 42."

    _check_no_text_inside_reasoning(events)


@pytest.mark.asyncio
async def test_content_less_chunk_without_reasoning_still_opens_the_assistant_message():
    """With no reasoning span open, a content-less chunk keeps opening the message that parents tool calls."""

    async def mock_stream():
        citations_only = RunContentEvent()
        citations_only.citations = Citations(raw=[{"url": "https://example.com"}])
        yield citations_only

        yield RunCompletedEvent()

    events = await _collect(mock_stream())
    span_events = _span_events(events)

    text_id = _span_id_at(span_events, 0)
    assert span_events == [
        (EventType.TEXT_MESSAGE_START, text_id),
        (EventType.TEXT_MESSAGE_END, text_id),
    ]

    assert len(events) == len(span_events) + 1
    assert events[-1].type == EventType.RUN_FINISHED


@pytest.mark.asyncio
async def test_mixed_text_and_reasoning_chunks_produce_one_message_each():
    """Accepted cost of alternation: a chunk carrying both text and its own differing reasoning opens a
    reasoning span and then a fresh assistant message, so consecutive such chunks give one message each.

    No provider stream has been observed doing this. Every reasoning delta and every text delta still
    reaches the client, in order, and the spans never nest.
    """

    async def mock_stream():
        for text, reasoning in (("The ", "Weighing "), ("answer ", "the "), ("is 42.", "options.")):
            chunk = RunContentEvent()
            chunk.content = text
            chunk.reasoning_content = reasoning
            yield chunk

        yield RunCompletedEvent()

    events = await _collect(mock_stream())
    span_events = _span_events(events)

    reasoning_ids = [mid for kind, mid in span_events if kind == EventType.REASONING_START]
    text_ids = [mid for kind, mid in span_events if kind == EventType.TEXT_MESSAGE_START]
    assert len(reasoning_ids) == 3, f"expected three reasoning spans, got {span_events}"
    assert len(text_ids) == 3, f"expected three assistant messages, got {span_events}"

    assert span_events == [
        (EventType.REASONING_START, reasoning_ids[0]),
        (EventType.REASONING_MESSAGE_START, reasoning_ids[0]),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_ids[0]),
        (EventType.REASONING_MESSAGE_END, reasoning_ids[0]),
        (EventType.REASONING_END, reasoning_ids[0]),
        (EventType.TEXT_MESSAGE_START, text_ids[0]),
        (EventType.TEXT_MESSAGE_CONTENT, text_ids[0]),
        (EventType.TEXT_MESSAGE_END, text_ids[0]),
        (EventType.REASONING_START, reasoning_ids[1]),
        (EventType.REASONING_MESSAGE_START, reasoning_ids[1]),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_ids[1]),
        (EventType.REASONING_MESSAGE_END, reasoning_ids[1]),
        (EventType.REASONING_END, reasoning_ids[1]),
        (EventType.TEXT_MESSAGE_START, text_ids[1]),
        (EventType.TEXT_MESSAGE_CONTENT, text_ids[1]),
        (EventType.TEXT_MESSAGE_END, text_ids[1]),
        (EventType.REASONING_START, reasoning_ids[2]),
        (EventType.REASONING_MESSAGE_START, reasoning_ids[2]),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_ids[2]),
        (EventType.REASONING_MESSAGE_END, reasoning_ids[2]),
        (EventType.REASONING_END, reasoning_ids[2]),
        (EventType.TEXT_MESSAGE_START, text_ids[2]),
        (EventType.TEXT_MESSAGE_CONTENT, text_ids[2]),
        (EventType.TEXT_MESSAGE_END, text_ids[2]),
    ]
    assert len(set(reasoning_ids + text_ids)) == 6

    assert _message_deltas(events, EventType.REASONING_MESSAGE_CONTENT) == [
        (reasoning_ids[0], "Weighing "),
        (reasoning_ids[1], "the "),
        (reasoning_ids[2], "options."),
    ]
    assert _message_deltas(events, EventType.TEXT_MESSAGE_CONTENT) == [
        (text_ids[0], "The "),
        (text_ids[1], "answer "),
        (text_ids[2], "is 42."),
    ]

    assert len(events) == len(span_events) + 1
    assert events[-1].type == EventType.RUN_FINISHED

    _check_no_reasoning_inside_text_message(events)
    _check_no_text_inside_reasoning(events)


@pytest.mark.asyncio
async def test_reasoning_then_mixed_chunk_then_text_stays_one_span_and_one_message():
    """The provider shape: thought-only chunks, one chunk carrying both, then text-only chunks."""

    async def mock_stream():
        for delta in ("Weighing ", "the "):
            reasoning_chunk = RunContentEvent()
            reasoning_chunk.reasoning_content = delta
            yield reasoning_chunk

        mixed = RunContentEvent()
        mixed.content = "The "
        mixed.reasoning_content = "options."
        yield mixed

        for delta in ("answer ", "is 42."):
            text_chunk = RunContentEvent()
            text_chunk.content = delta
            yield text_chunk

        yield RunCompletedEvent()

    events = await _collect(mock_stream())
    span_events = _span_events(events)

    reasoning_id = _span_id_at(span_events, 0)
    text_id = _span_id_of(span_events, EventType.TEXT_MESSAGE_START)

    assert span_events == [
        (EventType.REASONING_START, reasoning_id),
        (EventType.REASONING_MESSAGE_START, reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_id),
        (EventType.REASONING_MESSAGE_END, reasoning_id),
        (EventType.REASONING_END, reasoning_id),
        (EventType.TEXT_MESSAGE_START, text_id),
        (EventType.TEXT_MESSAGE_CONTENT, text_id),
        (EventType.TEXT_MESSAGE_CONTENT, text_id),
        (EventType.TEXT_MESSAGE_CONTENT, text_id),
        (EventType.TEXT_MESSAGE_END, text_id),
    ]

    assert reasoning_id != text_id

    assert _message_deltas(events, EventType.REASONING_MESSAGE_CONTENT) == [
        (reasoning_id, "Weighing "),
        (reasoning_id, "the "),
        (reasoning_id, "options."),
    ]
    assert _message_deltas(events, EventType.TEXT_MESSAGE_CONTENT) == [
        (text_id, "The "),
        (text_id, "answer "),
        (text_id, "is 42."),
    ]

    assert len(events) == len(span_events) + 1
    assert events[-1].type == EventType.RUN_FINISHED


@pytest.mark.asyncio
async def test_mixed_chunk_mid_answer_parents_a_later_tool_call_to_the_new_message():
    """Reasoning sharing a chunk with text ends the message open at the time, so the text that came with
    it starts a new one, and that new message is what a following tool call parents to."""

    async def mock_stream():
        opener = RunContentEvent()
        opener.content = "Let me check. "
        yield opener

        mixed = RunContentEvent()
        mixed.content = "One moment."
        mixed.reasoning_content = "I should look up the weather."
        yield mixed

        weather = ToolExecution(tool_call_id="tc_1", tool_name="get_weather", tool_args={"city": "London"})
        yield ToolCallStartedEvent(tool=weather)

        weather.result = "15C"
        yield ToolCallCompletedEvent(tool=weather)

        later_reasoning = RunContentEvent()
        later_reasoning.reasoning_content = "The result is in."
        yield later_reasoning

        yield RunCompletedEvent()

    events = await _collect(mock_stream())
    span_events = _span_events(events)

    opener_id = _span_id_at(span_events, 0)
    first_reasoning_id = _span_id_of(span_events, EventType.REASONING_START)
    answer_id = _span_id_of(span_events, EventType.TEXT_MESSAGE_START, other_than=opener_id)
    second_reasoning_id = _span_id_of(span_events, EventType.REASONING_START, other_than=first_reasoning_id)

    assert span_events == [
        (EventType.TEXT_MESSAGE_START, opener_id),
        (EventType.TEXT_MESSAGE_CONTENT, opener_id),
        (EventType.TEXT_MESSAGE_END, opener_id),
        (EventType.REASONING_START, first_reasoning_id),
        (EventType.REASONING_MESSAGE_START, first_reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, first_reasoning_id),
        (EventType.REASONING_MESSAGE_END, first_reasoning_id),
        (EventType.REASONING_END, first_reasoning_id),
        (EventType.TEXT_MESSAGE_START, answer_id),
        (EventType.TEXT_MESSAGE_CONTENT, answer_id),
        (EventType.TEXT_MESSAGE_END, answer_id),
        (EventType.REASONING_START, second_reasoning_id),
        (EventType.REASONING_MESSAGE_START, second_reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, second_reasoning_id),
        (EventType.REASONING_MESSAGE_END, second_reasoning_id),
        (EventType.REASONING_END, second_reasoning_id),
    ]

    assert len({opener_id, first_reasoning_id, answer_id, second_reasoning_id}) == 4

    # Each delta is emitted where it arrived, never carried over into a later span
    assert _message_deltas(events, EventType.REASONING_MESSAGE_CONTENT) == [
        (first_reasoning_id, "I should look up the weather."),
        (second_reasoning_id, "The result is in."),
    ]
    assert _message_deltas(events, EventType.TEXT_MESSAGE_CONTENT) == [
        (opener_id, "Let me check. "),
        (answer_id, "One moment."),
    ]

    # No synthetic parent is minted: the message the mixed chunk's text opened is the live one
    tool_start = _first_event(events, EventType.TOOL_CALL_START)
    assert tool_start.parent_message_id == answer_id

    _check_no_reasoning_inside_text_message(events)
    _check_no_text_inside_reasoning(events)


@pytest.mark.asyncio
async def test_reasoning_only_chunk_mid_answer_ends_that_assistant_message():
    """Accepted cost of alternation: a reasoning-only chunk arriving mid-answer ends the open assistant
    message, and the rest of the answer streams under a new message id.

    This is the same thing the dedicated reasoning-event path has always done, so a client that renders
    the reasoning-event shape correctly already renders this one.
    """

    async def mock_stream():
        opener = RunContentEvent()
        opener.content = "The answer"
        yield opener

        interruption = RunContentEvent()
        interruption.reasoning_content = "Still thinking."
        yield interruption

        rest = RunContentEvent()
        rest.content = " is 42."
        yield rest

        yield RunCompletedEvent()

    events = await _collect(mock_stream())
    span_events = _span_events(events)

    first_text_id = _span_id_at(span_events, 0)
    reasoning_id = _span_id_of(span_events, EventType.REASONING_START)
    second_text_id = _span_id_of(span_events, EventType.TEXT_MESSAGE_START, other_than=first_text_id)

    assert span_events == [
        (EventType.TEXT_MESSAGE_START, first_text_id),
        (EventType.TEXT_MESSAGE_CONTENT, first_text_id),
        (EventType.TEXT_MESSAGE_END, first_text_id),
        (EventType.REASONING_START, reasoning_id),
        (EventType.REASONING_MESSAGE_START, reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_id),
        (EventType.REASONING_MESSAGE_END, reasoning_id),
        (EventType.REASONING_END, reasoning_id),
        (EventType.TEXT_MESSAGE_START, second_text_id),
        (EventType.TEXT_MESSAGE_CONTENT, second_text_id),
        (EventType.TEXT_MESSAGE_END, second_text_id),
    ]

    assert len({first_text_id, reasoning_id, second_text_id}) == 3

    # The reasoning reaches the client as it arrives, not after the answer has finished
    assert _message_deltas(events, EventType.TEXT_MESSAGE_CONTENT) == [
        (first_text_id, "The answer"),
        (second_text_id, " is 42."),
    ]
    assert _deltas(events, EventType.REASONING_MESSAGE_CONTENT) == "Still thinking."

    assert len(events) == len(span_events) + 1
    assert events[-1].type == EventType.RUN_FINISHED

    _check_no_reasoning_inside_text_message(events)
    _check_no_text_inside_reasoning(events)


@pytest.mark.asyncio
async def test_reasoning_after_a_content_less_opener_streams_before_the_answer():
    """The reasoning-capable model shape: an empty opening chunk, native reasoning, then the answer.

    A run's first chunk carries no text yet still opens an assistant message, and every native
    reasoning delta arrives while that message is open. Reasoning must not wait for the answer to
    finish: the span opens as soon as the first delta lands, so the client sees thinking live.
    """

    async def mock_stream():
        opener = RunContentEvent()
        opener.content = ""
        yield opener

        for delta in ("Weighing ", "the ", "options."):
            reasoning_chunk = RunContentEvent()
            reasoning_chunk.reasoning_content = delta
            yield reasoning_chunk

        answer = RunContentEvent()
        answer.content = "The answer is 42."
        yield answer

        yield RunCompletedEvent()

    events = await _collect(mock_stream())
    span_events = _span_events(events)

    opener_id = _span_id_at(span_events, 0)
    reasoning_id = _span_id_of(span_events, EventType.REASONING_START)
    answer_id = _span_id_of(span_events, EventType.TEXT_MESSAGE_START, occurrence=1)

    assert span_events == [
        (EventType.TEXT_MESSAGE_START, opener_id),
        (EventType.TEXT_MESSAGE_END, opener_id),
        (EventType.REASONING_START, reasoning_id),
        (EventType.REASONING_MESSAGE_START, reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_id),
        (EventType.REASONING_MESSAGE_CONTENT, reasoning_id),
        (EventType.REASONING_MESSAGE_END, reasoning_id),
        (EventType.REASONING_END, reasoning_id),
        (EventType.TEXT_MESSAGE_START, answer_id),
        (EventType.TEXT_MESSAGE_CONTENT, answer_id),
        (EventType.TEXT_MESSAGE_END, answer_id),
    ]

    assert len({opener_id, reasoning_id, answer_id}) == 3

    # Each delta reaches the client as its own event, in order, rather than as one lump at the end
    assert _message_deltas(events, EventType.REASONING_MESSAGE_CONTENT) == [
        (reasoning_id, "Weighing "),
        (reasoning_id, "the "),
        (reasoning_id, "options."),
    ]

    # The whole reasoning span is over before the answer starts, never emitted after it
    event_types = [e.type for e in events]
    assert event_types.index(EventType.REASONING_END) < event_types.index(EventType.TEXT_MESSAGE_CONTENT)
    assert max(i for i, t in enumerate(event_types) if t == EventType.REASONING_MESSAGE_CONTENT) < event_types.index(
        EventType.TEXT_MESSAGE_CONTENT
    )

    assert len(events) == len(span_events) + 1
    assert events[-1].type == EventType.RUN_FINISHED

    _check_no_reasoning_inside_text_message(events)
    _check_no_text_inside_reasoning(events)
