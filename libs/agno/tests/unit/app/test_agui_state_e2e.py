"""End-to-end integration test for AG-UI state events (StateSnapshot + StateDelta).

Tests the full pipeline: router -> streaming -> event emission, using mock agent responses.
Also includes real API tests that run when AGNO_RUN_REAL_API_TESTS=1 and OPENAI_API_KEY are set.
"""

import os
import uuid
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import APIRouter, FastAPI

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os.interfaces.agui.router import attach_routes
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.tools import tool
from tests.helpers import parse_sse_events

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def make_agui_payload(messages, state=None):
    """Build a valid RunAgentInput payload with all required fields."""
    return {
        "threadId": str(uuid.uuid4()),
        "runId": str(uuid.uuid4()),
        "state": state,
        "messages": [{"id": str(uuid.uuid4()), "role": m["role"], "content": m["content"]} for m in messages],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }


@tool
def increment_counter(amount: int = 1) -> str:
    """Increment the counter in session state by the given amount."""
    return f"Counter incremented by {amount}"


@pytest.fixture
def agent():
    return Agent(
        name="StateTestAgent",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[increment_counter],
        instructions="You are a test agent.",
        markdown=False,
    )


@pytest.fixture
def app(agent):
    test_app = FastAPI()
    router = APIRouter()
    attach_routes(router, agent=agent)
    test_app.include_router(router)
    return test_app


def get_event_types(events):
    """Extract event types from parsed SSE events."""
    return [e.get("data", {}).get("type") if isinstance(e.get("data"), dict) else None for e in events]


# ---------------------------------------------------------------------------
# Integration tests (mocked agent, real router + streaming pipeline)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_router_emits_state_snapshot_with_state(app, agent):
    """Integration test: router emits initial StateSnapshot when state is provided."""
    from httpx import ASGITransport

    async def mock_arun_stream(*args, **kwargs):
        text = RunContentEvent()
        text.event = RunEvent.run_content
        text.content = "Hello"
        yield text

        completed = RunCompletedEvent()
        completed.event = RunEvent.run_completed
        completed.content = ""
        completed.session_state = {"counter": 0, "label": "test"}
        yield completed

    with patch.object(agent, "arun", side_effect=mock_arun_stream):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/agui",
                json=make_agui_payload(
                    messages=[{"role": "user", "content": "Hi"}],
                    state={"counter": 0, "label": "test"},
                ),
                timeout=30.0,
            )

    assert response.status_code == 200
    events = parse_sse_events(response.text)
    event_types = get_event_types(events)

    # Must have RUN_STARTED, STATE_SNAPSHOT (initial + final), RUN_FINISHED
    assert "RUN_STARTED" in event_types
    assert event_types.count("STATE_SNAPSHOT") >= 2, f"Expected >= 2 snapshots, got: {event_types}"
    assert "RUN_FINISHED" in event_types

    # Initial snapshot right after RUN_STARTED
    run_started_idx = event_types.index("RUN_STARTED")
    first_snapshot_idx = event_types.index("STATE_SNAPSHOT")
    assert first_snapshot_idx == run_started_idx + 1

    # Final snapshot right before RUN_FINISHED
    run_finished_idx = event_types.index("RUN_FINISHED")
    last_snapshot_idx = len(event_types) - 1 - event_types[::-1].index("STATE_SNAPSHOT")
    assert last_snapshot_idx == run_finished_idx - 1

    # Verify initial snapshot content
    first_snapshot_data = events[first_snapshot_idx]["data"]
    assert first_snapshot_data["snapshot"] == {"counter": 0, "label": "test"}


@pytest.mark.asyncio
async def test_router_no_state_events_without_state(app, agent):
    """Integration test: no state events when state is not provided."""
    from httpx import ASGITransport

    async def mock_arun_stream(*args, **kwargs):
        text = RunContentEvent()
        text.event = RunEvent.run_content
        text.content = "Hello"
        yield text

        completed = RunCompletedEvent()
        completed.event = RunEvent.run_completed
        completed.content = ""
        yield completed

    with patch.object(agent, "arun", side_effect=mock_arun_stream):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/agui",
                json=make_agui_payload(
                    messages=[{"role": "user", "content": "Hi"}],
                    state=None,
                ),
                timeout=30.0,
            )

    assert response.status_code == 200
    events = parse_sse_events(response.text)
    event_types = get_event_types(events)

    assert "STATE_SNAPSHOT" not in event_types
    assert "STATE_DELTA" not in event_types
    assert "RUN_FINISHED" in event_types


@pytest.mark.asyncio
async def test_router_state_delta_after_tool_mutation(app, agent):
    """Integration test: StateDelta emitted when tool mutates state."""
    from httpx import ASGITransport

    # The mutable state dict passed through the pipeline
    mutable_state = {"counter": 0}

    async def mock_arun_stream(*args, **kwargs):
        text = RunContentEvent()
        text.event = RunEvent.run_content
        text.content = "Let me increment"
        yield text

        tool_start = ToolCallStartedEvent()
        tool_start.event = RunEvent.tool_call_started
        tool_start.content = ""
        tool_mock = MagicMock()
        tool_mock.tool_call_id = "tc_1"
        tool_mock.tool_name = "increment_counter"
        tool_mock.tool_args = {"amount": 1}
        tool_start.tool = tool_mock
        yield tool_start

        # Simulate state mutation that happens during tool execution
        mutable_state["counter"] = 5

        tool_end = ToolCallCompletedEvent()
        tool_end.event = RunEvent.tool_call_completed
        tool_end.content = ""
        tool_mock.result = "Counter incremented"
        tool_end.tool = tool_mock
        yield tool_end

        completed = RunCompletedEvent()
        completed.event = RunEvent.run_completed
        completed.content = ""
        completed.session_state = {"counter": 5}
        yield completed

    # Intercept validate_agui_state to return our mutable_state
    def mock_validate(state, thread_id):
        if state is not None:
            mutable_state["counter"] = 0  # Reset to initial
            return mutable_state
        return None

    with (
        patch.object(agent, "arun", side_effect=mock_arun_stream),
        patch("agno.os.interfaces.agui.router.validate_agui_state", side_effect=mock_validate),
    ):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/agui",
                json=make_agui_payload(
                    messages=[{"role": "user", "content": "Increment counter"}],
                    state={"counter": 0},
                ),
                timeout=30.0,
            )

    assert response.status_code == 200
    events = parse_sse_events(response.text)
    event_types = get_event_types(events)

    # Should have STATE_DELTA after tool call
    assert "STATE_DELTA" in event_types, f"Missing STATE_DELTA. Events: {event_types}"

    # STATE_DELTA should come after TOOL_CALL_RESULT
    delta_idx = event_types.index("STATE_DELTA")
    result_idx = event_types.index("TOOL_CALL_RESULT")
    assert delta_idx > result_idx

    # Verify delta content
    delta_event = events[delta_idx]["data"]
    delta_ops = delta_event["delta"]
    paths = [op["path"] for op in delta_ops]
    assert "/counter" in paths

    # Should also have final STATE_SNAPSHOT
    assert "STATE_SNAPSHOT" in event_types


# ---------------------------------------------------------------------------
# Real API tests (require explicit opt-in and OPENAI_API_KEY)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (os.environ.get("AGNO_RUN_REAL_API_TESTS") == "1" and os.environ.get("OPENAI_API_KEY")),
    reason="Real API tests require AGNO_RUN_REAL_API_TESTS=1 and OPENAI_API_KEY set",
)
@pytest.mark.asyncio
async def test_agui_state_events_real_api(app):
    """Real API test: AG-UI agent emits StateSnapshot events when state is provided."""
    from httpx import ASGITransport

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/agui",
            json=make_agui_payload(
                messages=[{"role": "user", "content": "Say hello in one sentence."}],
                state={"counter": 0, "label": "test"},
            ),
            timeout=60.0,
        )

    assert response.status_code == 200
    events = parse_sse_events(response.text)
    event_types = get_event_types(events)

    assert "RUN_STARTED" in event_types
    assert event_types.count("STATE_SNAPSHOT") >= 2
    assert "RUN_FINISHED" in event_types
