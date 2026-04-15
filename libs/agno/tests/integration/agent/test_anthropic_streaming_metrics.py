"""
Integration test for GitHub issue #5444:
"AG-UI streaming reports doubled input_tokens (Anthropic usage added twice)"

Tests that streaming and non-streaming Claude metrics match, that session DB
stores correct values, and that async streaming (the AG-UI code path) is not
doubled.
"""

import pytest

from agno.agent import Agent, RunOutput
from agno.db.base import SessionType
from agno.metrics import RunMetrics
from agno.models.anthropic import Claude

MODEL_ID = "claude-haiku-4-5"
PROMPT = "What is 2+2? Answer in one sentence."


# -- Helpers ------------------------------------------------------------------


def _get_streaming_run_output(agent: Agent, prompt: str) -> RunOutput:
    final = None
    for event in agent.run(prompt, stream=True, yield_run_output=True):
        if isinstance(event, RunOutput):
            final = event
    assert final is not None, "Streaming did not yield a RunOutput"
    return final


async def _get_async_streaming_run_output(agent: Agent, prompt: str) -> RunOutput:
    final = None
    async for event in agent.arun(prompt, stream=True, yield_run_output=True):
        if isinstance(event, RunOutput):
            final = event
    assert final is not None, "Async streaming did not yield a RunOutput"
    return final


# -- Tests --------------------------------------------------------------------


def test_streaming_input_tokens_not_doubled():
    """Core #5444 regression: streaming input_tokens must not be 2x non-streaming."""
    non_stream = Agent(model=Claude(id=MODEL_ID), telemetry=False)
    response_sync = non_stream.run(PROMPT, stream=False)

    stream_agent = Agent(model=Claude(id=MODEL_ID), telemetry=False)
    response_stream = _get_streaming_run_output(stream_agent, PROMPT)

    sync_in = response_sync.metrics.input_tokens
    stream_in = response_stream.metrics.input_tokens

    assert sync_in > 0, "Non-streaming should report input_tokens"
    assert stream_in > 0, "Streaming should report input_tokens"

    ratio = stream_in / sync_in
    assert ratio <= 1.3, (
        f"Streaming input_tokens ({stream_in}) is {ratio:.2f}x non-streaming ({sync_in}). "
        f"Bug #5444: tokens are doubled."
    )


@pytest.mark.asyncio
async def test_async_streaming_input_tokens_not_doubled():
    """AG-UI uses async streaming — same check as above but async path."""
    non_stream = Agent(model=Claude(id=MODEL_ID), telemetry=False)
    response_sync = await non_stream.arun(PROMPT, stream=False)

    stream_agent = Agent(model=Claude(id=MODEL_ID), telemetry=False)
    response_stream = await _get_async_streaming_run_output(stream_agent, PROMPT)

    sync_in = response_sync.metrics.input_tokens
    stream_in = response_stream.metrics.input_tokens

    assert sync_in > 0
    assert stream_in > 0

    ratio = stream_in / sync_in
    assert ratio <= 1.3, (
        f"Async streaming input_tokens ({stream_in}) is {ratio:.2f}x non-streaming ({sync_in}). "
        f"Bug #5444: tokens are doubled in AG-UI path."
    )


def test_streaming_total_tokens_consistent():
    """total_tokens should equal input_tokens + output_tokens for streaming."""
    agent = Agent(model=Claude(id=MODEL_ID), telemetry=False)
    result = _get_streaming_run_output(agent, PROMPT)

    m = result.metrics
    assert m.total_tokens == m.input_tokens + m.output_tokens, (
        f"total_tokens ({m.total_tokens}) != input ({m.input_tokens}) + output ({m.output_tokens})"
    )


def test_streaming_metrics_detail_matches_toplevel():
    """RunMetrics.details['model'] should sum to the same as top-level tokens."""
    agent = Agent(model=Claude(id=MODEL_ID), telemetry=False)
    result = _get_streaming_run_output(agent, PROMPT)

    assert result.metrics.details is not None
    assert "model" in result.metrics.details

    detail_input = sum(d.input_tokens for d in result.metrics.details["model"])
    detail_output = sum(d.output_tokens for d in result.metrics.details["model"])

    assert detail_input == result.metrics.input_tokens, (
        f"detail input ({detail_input}) != top-level input ({result.metrics.input_tokens})"
    )
    assert detail_output == result.metrics.output_tokens, (
        f"detail output ({detail_output}) != top-level output ({result.metrics.output_tokens})"
    )


def test_session_db_stores_correct_streaming_metrics(shared_db):
    """Session DB metrics must not be doubled — this is what /sessions/{id}/runs returns."""
    agent = Agent(
        model=Claude(id=MODEL_ID),
        db=shared_db,
        telemetry=False,
    )

    result = _get_streaming_run_output(agent, PROMPT)
    run_input = result.metrics.input_tokens
    assert run_input > 0

    session = shared_db.get_session(
        session_id=agent.session_id,
        session_type=SessionType.AGENT,
    )
    session_input = session.session_data["session_metrics"]["input_tokens"]

    assert session_input == run_input, (
        f"Session DB input_tokens ({session_input}) != run input_tokens ({run_input}). "
        f"DB is storing inflated metrics."
    )


def test_multi_turn_streaming_session_metrics(shared_db):
    """Two streaming turns — session metrics should be sum of individual runs, not inflated."""
    agent = Agent(
        model=Claude(id=MODEL_ID),
        db=shared_db,
        telemetry=False,
    )

    run1 = _get_streaming_run_output(agent, "Say hello.")
    run2 = _get_streaming_run_output(agent, "Say goodbye.")

    expected_input = run1.metrics.input_tokens + run2.metrics.input_tokens

    session = shared_db.get_session(
        session_id=agent.session_id,
        session_type=SessionType.AGENT,
    )
    session_input = session.session_data["session_metrics"]["input_tokens"]

    assert session_input == expected_input, (
        f"Session input ({session_input}) != sum of runs ({expected_input}). "
        f"Metrics are being inflated across turns."
    )
