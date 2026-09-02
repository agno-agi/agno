from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator

import pytest
from ag_ui.core import EventType
from ag_ui.encoder import EventEncoder

from agno.models.response import ToolExecution
from agno.os.interfaces.agui.stream import (
    async_stream_agno_response_as_agui_events,
    stream_agno_response_as_agui_events,
)
from agno.run.agent import RunCompletedEvent, RunContentEvent, RunOutputEvent, ToolCallStartedEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import TeamRunOutputEvent


def _assert_lineage(event, *, agent_id=None, team_id=None, run_id=None, parent_run_id=None):
    assert getattr(event, "agent_id", None) == agent_id
    assert getattr(event, "team_id", None) == team_id
    assert getattr(event, "run_id", None) == run_id
    assert getattr(event, "parent_run_id", None) == parent_run_id


def _agent_stream() -> Iterator[RunOutputEvent | TeamRunOutputEvent]:
    yield RunContentEvent(
        content="member response",
        agent_id="member-agent",
        run_id="member-run",
        parent_run_id="team-run",
    )
    yield RunCompletedEvent(
        agent_id="member-agent",
        run_id="member-run",
        parent_run_id="team-run",
    )


async def _team_stream() -> AsyncIterator[RunOutputEvent | TeamRunOutputEvent]:
    yield TeamRunContentEvent(
        content="leader response",
        team_id="research-team",
        run_id="team-run",
    )
    yield RunCompletedEvent(run_id="team-run")


def test_sync_stream_preserves_agent_run_lineage():
    events = list(
        stream_agno_response_as_agui_events(
            _agent_stream(),
            "thread-1",
            "request-run",
            team_id="research-team",
            team_mode="coordinate",
        )
    )

    start = next(event for event in events if event.type == EventType.TEXT_MESSAGE_START)
    content = next(event for event in events if event.type == EventType.TEXT_MESSAGE_CONTENT)
    finished = next(event for event in events if event.type == EventType.RUN_FINISHED)

    _assert_lineage(
        start,
        agent_id="member-agent",
        team_id="research-team",
        run_id="member-run",
        parent_run_id="team-run",
    )
    _assert_lineage(
        content,
        agent_id="member-agent",
        team_id="research-team",
        run_id="member-run",
        parent_run_id="team-run",
    )
    encoded = EventEncoder().encode(content)
    serialized = json.loads(encoded.removeprefix("data: ").strip())
    assert {field: serialized[field] for field in ("agent_id", "team_id", "run_id", "parent_run_id")} == {
        "agent_id": "member-agent",
        "team_id": "research-team",
        "run_id": "member-run",
        "parent_run_id": "team-run",
    }
    assert serialized["surface"] == "trace"
    _assert_lineage(
        finished,
        agent_id="member-agent",
        team_id="research-team",
        run_id="request-run",
        parent_run_id="team-run",
    )


@pytest.mark.asyncio
async def test_async_stream_preserves_team_run_lineage():
    events = [
        event
        async for event in async_stream_agno_response_as_agui_events(
            _team_stream(),
            "thread-1",
            "request-run",
        )
    ]

    start = next(event for event in events if event.type == EventType.TEXT_MESSAGE_START)
    content = next(event for event in events if event.type == EventType.TEXT_MESSAGE_CONTENT)

    _assert_lineage(start, team_id="research-team", run_id="team-run")
    _assert_lineage(content, team_id="research-team", run_id="team-run")
    assert getattr(start, "surface", None) == "user"
    assert getattr(content, "surface", None) == "user"


def test_coordinate_and_route_member_text_have_different_surfaces():
    coordinate_events = list(
        stream_agno_response_as_agui_events(
            iter(
                [
                    RunContentEvent(
                        content="member trace",
                        agent_id="member-agent",
                        run_id="member-run",
                        parent_run_id="team-run",
                    ),
                    TeamRunContentEvent(
                        content="leader answer",
                        team_id="research-team",
                        run_id="team-run",
                    ),
                    RunCompletedEvent(run_id="team-run"),
                ]
            ),
            "thread-1",
            "request-run",
            team_id="research-team",
            team_mode="coordinate",
        )
    )
    coordinate_content = [event for event in coordinate_events if event.type == EventType.TEXT_MESSAGE_CONTENT]

    assert [event.delta for event in coordinate_content] == ["member trace", "leader answer"]
    assert [getattr(event, "surface", None) for event in coordinate_content] == ["trace", "user"]

    route_events = list(
        stream_agno_response_as_agui_events(
            iter(
                [
                    RunContentEvent(
                        content="member final answer",
                        agent_id="member-agent",
                        run_id="member-run",
                        parent_run_id="team-run",
                    ),
                    RunCompletedEvent(run_id="team-run"),
                ]
            ),
            "thread-1",
            "request-run",
            team_id="research-team",
            team_mode="route",
        )
    )
    route_content = next(event for event in route_events if event.type == EventType.TEXT_MESSAGE_CONTENT)

    assert route_content.delta == "member final answer"
    assert getattr(route_content, "surface", None) == "user"


def test_missing_lineage_fields_remain_absent():
    events = list(
        stream_agno_response_as_agui_events(
            iter([RunContentEvent(content="hello"), RunCompletedEvent()]),
            "thread-1",
            "request-run",
        )
    )

    content = next(event for event in events if event.type == EventType.TEXT_MESSAGE_CONTENT)
    serialized = content.model_dump(exclude_none=True)

    for field in ("agent_id", "team_id", "run_id", "parent_run_id"):
        assert field not in serialized


def test_tool_events_preserve_member_lineage():
    tool_event = ToolCallStartedEvent(
        agent_id="member-agent",
        run_id="member-run",
        parent_run_id="team-run",
        tool=ToolExecution(
            tool_call_id="tool-1",
            tool_name="search",
            tool_args={"query": "agno"},
        ),
    )

    events = list(
        stream_agno_response_as_agui_events(
            iter([tool_event, RunCompletedEvent(run_id="team-run")]),
            "thread-1",
            "request-run",
            team_id="research-team",
        )
    )

    tool_events = [event for event in events if event.type in (EventType.TOOL_CALL_START, EventType.TOOL_CALL_ARGS)]
    assert len(tool_events) == 2
    for event in tool_events:
        _assert_lineage(
            event,
            agent_id="member-agent",
            team_id="research-team",
            run_id="member-run",
            parent_run_id="team-run",
        )
