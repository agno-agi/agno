import json
from typing import Any, AsyncIterator, Dict, List
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.agent._storage import load_session_state
from agno.os.app import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunOutputEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.session.agent import AgentSession
from agno.team import Team


def parse_sse_events(content: str) -> List[Dict[str, Any]]:
    events = []
    for line in content.split("\n"):
        line = line.strip()
        if not line or not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        try:
            events.append(json.loads(data_str))
        except json.JSONDecodeError:
            continue
    return events


def get_event_types(events: List[Dict[str, Any]]) -> List[str]:
    return [e.get("type") for e in events]


def make_request_body(message: str, state: Any = None, thread_id: str = "test-thread") -> Dict[str, Any]:
    return {
        "threadId": thread_id,
        "runId": "test-run",
        "state": state,
        "messages": [{"id": "msg-1", "role": "user", "content": message}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }


# =============================================================================
# Agent State Events
# =============================================================================


@pytest.fixture
def test_agent():
    return Agent(name="test-state-agent", instructions="You are a test agent.")


@pytest.fixture
def agent_client(test_agent: Agent):
    agent_os = AgentOS(agents=[test_agent], interfaces=[AGUI(agent=test_agent)])
    app = agent_os.get_app()
    return TestClient(app), test_agent


class TestAgentStateSnapshot:
    def test_initial_snapshot_emitted_when_state_provided(self, agent_client):
        client, agent = agent_client

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Hello")
            yield RunCompletedEvent(content="", session_state={"counter": 0})

        with patch.object(
            agent,
            "arun",
        ) as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("Hi", state={"counter": 0}))

        assert response.status_code == 200
        events = parse_sse_events(response.text)
        types = get_event_types(events)

        assert "RUN_STARTED" in types
        assert "STATE_SNAPSHOT" in types

        # Initial snapshot immediately after RUN_STARTED
        run_started_idx = types.index("RUN_STARTED")
        first_snapshot_idx = types.index("STATE_SNAPSHOT")
        assert first_snapshot_idx == run_started_idx + 1

        # Verify snapshot content
        snapshot_event = events[first_snapshot_idx]
        assert snapshot_event["snapshot"] == {"counter": 0}

    def test_final_snapshot_emitted_before_run_finished(self, agent_client):
        client, agent = agent_client

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Done")
            yield RunCompletedEvent(content="", session_state={"counter": 5})

        with patch.object(
            agent,
            "arun",
        ) as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("Test", state={"counter": 0}))

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        # Final snapshot right before RUN_FINISHED
        run_finished_idx = types.index("RUN_FINISHED")
        last_snapshot_idx = len(types) - 1 - types[::-1].index("STATE_SNAPSHOT")
        assert last_snapshot_idx == run_finished_idx - 1

        # Verify final snapshot has updated state
        final_snapshot = events[last_snapshot_idx]
        assert final_snapshot["snapshot"] == {"counter": 5}

    def test_emits_empty_snapshot_when_state_is_none(self, agent_client):
        # Emit empty STATE_SNAPSHOT on first run so the frontend's state atom initializes.
        client, agent = agent_client

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Hello")
            yield RunCompletedEvent(content="")

        with patch.object(
            agent,
            "arun",
        ) as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("Hi", state=None))

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        assert "STATE_SNAPSHOT" in types
        # No mutations happened so no deltas should fire.
        assert "STATE_DELTA" not in types
        assert "RUN_FINISHED" in types
        # First (initial) snapshot should be empty dict.
        first_snapshot = next(e for e in events if e.get("type") == "STATE_SNAPSHOT")
        assert first_snapshot["snapshot"] == {}

    def test_request_with_omitted_state_field_returns_422(self, agent_client):
        # `state` is required by Pydantic; omitting it (not null) is malformed.
        client, _agent = agent_client

        body = {
            "threadId": "test-thread",
            "runId": "test-run",
            "messages": [{"id": "msg-1", "role": "user", "content": "Hi"}],
            "tools": [],
            "context": [],
            "forwardedProps": {},
        }
        response = client.post("/agui", json=body)

        assert response.status_code == 422
        # Confirm the missing field is what Pydantic flagged.
        detail = response.json()["detail"]
        assert any(err.get("loc") == ["body", "state"] for err in detail)

    def test_session_state_passed_to_agent_arun(self, agent_client):
        client, agent = agent_client
        initial_state = {"counter": 10, "items": ["a", "b"]}

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Done")
            yield RunCompletedEvent(content="", session_state=initial_state)

        with patch.object(
            agent,
            "arun",
        ) as mock_arun:
            mock_arun.return_value = mock_stream()
            client.post("/agui", json=make_request_body("Test", state=initial_state))

        # Verify agent.arun received session_state
        mock_arun.assert_called_once()
        call_kwargs = mock_arun.call_args.kwargs
        assert call_kwargs["session_state"] == initial_state


class TestAgentStateDelta:
    def test_delta_emitted_after_tool_mutation(self, agent_client):
        client, agent = agent_client

        # Mutable state that will be modified during stream
        mutable_state = {"counter": 0}

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Calling tool")

            tool_mock = MagicMock()
            tool_mock.tool_call_id = "tc_1"
            tool_mock.tool_name = "increment"
            tool_mock.tool_args = {"amount": 5}

            yield ToolCallStartedEvent(content="", tool=tool_mock)

            # Simulate tool mutating state
            mutable_state["counter"] = 5

            tool_mock.result = "Incremented"
            yield ToolCallCompletedEvent(content="", tool=tool_mock)

            yield RunCompletedEvent(content="", session_state={"counter": 5})

        def mock_validate(state, thread_id):
            if state is not None:
                mutable_state["counter"] = 0
                return mutable_state
            return None

        with (
            patch.object(
                agent,
                "arun",
            ) as mock_arun,
            patch("agno.os.interfaces.agui.router.validate_agui_state", side_effect=mock_validate),
        ):
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("Increment", state={"counter": 0}))

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        assert "STATE_DELTA" in types

        # Delta after TOOL_CALL_RESULT
        delta_idx = types.index("STATE_DELTA")
        result_idx = types.index("TOOL_CALL_RESULT")
        assert delta_idx > result_idx

        # Verify delta content
        delta_event = events[delta_idx]
        paths = [op["path"] for op in delta_event["delta"]]
        assert "/counter" in paths

    def test_no_delta_when_state_unchanged(self, agent_client):
        client, agent = agent_client

        # State that won't change
        stable_state = {"counter": 0}

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Calling tool")

            tool_mock = MagicMock()
            tool_mock.tool_call_id = "tc_1"
            tool_mock.tool_name = "noop"
            tool_mock.tool_args = {}

            yield ToolCallStartedEvent(content="", tool=tool_mock)
            # No state mutation here
            tool_mock.result = "No change"
            yield ToolCallCompletedEvent(content="", tool=tool_mock)

            yield RunCompletedEvent(content="", session_state={"counter": 0})

        def mock_validate(state, thread_id):
            if state is not None:
                return stable_state
            return None

        with (
            patch.object(
                agent,
                "arun",
            ) as mock_arun,
            patch("agno.os.interfaces.agui.router.validate_agui_state", side_effect=mock_validate),
        ):
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("Noop", state={"counter": 0}))

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        # No delta because state didn't change
        assert "STATE_DELTA" not in types
        # But still have snapshots
        assert "STATE_SNAPSHOT" in types


class TestAgentStateEdgeCases:
    def test_empty_dict_state(self, agent_client):
        client, agent = agent_client

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Done")
            yield RunCompletedEvent(content="", session_state={})

        with patch.object(
            agent,
            "arun",
        ) as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("Test", state={}))

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        # Empty dict is still valid state
        assert "STATE_SNAPSHOT" in types
        snapshot = next(e for e in events if e.get("type") == "STATE_SNAPSHOT")
        assert snapshot["snapshot"] == {}

    def test_nested_state_changes(self, agent_client):
        client, agent = agent_client

        mutable_state = {"recipe": {"title": "", "ingredients": []}}

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Updating recipe")

            tool_mock = MagicMock()
            tool_mock.tool_call_id = "tc_1"
            tool_mock.tool_name = "update_recipe"
            tool_mock.tool_args = {}

            yield ToolCallStartedEvent(content="", tool=tool_mock)

            # Nested mutation
            mutable_state["recipe"]["title"] = "Pasta"
            mutable_state["recipe"]["ingredients"].append("noodles")

            tool_mock.result = "Updated"
            yield ToolCallCompletedEvent(content="", tool=tool_mock)

            yield RunCompletedEvent(content="", session_state=mutable_state)

        def mock_validate(state, thread_id):
            if state is not None:
                mutable_state["recipe"] = {"title": "", "ingredients": []}
                return mutable_state
            return None

        with (
            patch.object(
                agent,
                "arun",
            ) as mock_arun,
            patch("agno.os.interfaces.agui.router.validate_agui_state", side_effect=mock_validate),
        ):
            mock_arun.return_value = mock_stream()
            response = client.post(
                "/agui", json=make_request_body("Update", state={"recipe": {"title": "", "ingredients": []}})
            )

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        assert "STATE_DELTA" in types
        delta_event = next(e for e in events if e.get("type") == "STATE_DELTA")
        paths = [op["path"] for op in delta_event["delta"]]
        # Should have paths for nested changes
        assert any("/recipe" in p for p in paths)


# =============================================================================
# Team State Events
# =============================================================================


@pytest.fixture
def test_team():
    member = Agent(name="team-member", instructions="You help the team.")
    return Team(name="test-state-team", members=[member])


@pytest.fixture
def team_client(test_team: Team):
    agent_os = AgentOS(teams=[test_team], interfaces=[AGUI(team=test_team)])
    app = agent_os.get_app()
    return TestClient(app), test_team


class TestTeamStateSnapshot:
    def test_team_initial_snapshot(self, team_client):
        client, team = team_client

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Team response")
            yield RunCompletedEvent(content="", session_state={"task": "done"})

        with patch.object(
            team,
            "arun",
        ) as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("Test", state={"task": "pending"}))

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        assert "RUN_STARTED" in types
        assert "STATE_SNAPSHOT" in types

        # Initial snapshot after RUN_STARTED
        run_started_idx = types.index("RUN_STARTED")
        first_snapshot_idx = types.index("STATE_SNAPSHOT")
        assert first_snapshot_idx == run_started_idx + 1

    def test_team_final_snapshot(self, team_client):
        client, team = team_client

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Team done")
            yield RunCompletedEvent(content="", session_state={"task": "completed"})

        with patch.object(
            team,
            "arun",
        ) as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("Finish", state={"task": "pending"}))

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        # Final snapshot before RUN_FINISHED
        run_finished_idx = types.index("RUN_FINISHED")
        last_snapshot_idx = len(types) - 1 - types[::-1].index("STATE_SNAPSHOT")
        assert last_snapshot_idx == run_finished_idx - 1

        final_snapshot = events[last_snapshot_idx]
        assert final_snapshot["snapshot"] == {"task": "completed"}

    def test_team_emits_empty_snapshot_without_state(self, team_client):
        # Team variant: emit empty STATE_SNAPSHOT on first run so the frontend's state atom initializes.
        client, team = team_client

        async def mock_stream() -> AsyncIterator[RunOutputEvent]:
            yield RunContentEvent(content="Team response")
            yield RunCompletedEvent(content="")

        with patch.object(
            team,
            "arun",
        ) as mock_arun:
            mock_arun.return_value = mock_stream()
            response = client.post("/agui", json=make_request_body("Test", state=None))

        events = parse_sse_events(response.text)
        types = get_event_types(events)

        assert "STATE_SNAPSHOT" in types
        assert "STATE_DELTA" not in types
        first_snapshot = next(e for e in events if e.get("type") == "STATE_SNAPSHOT")
        assert first_snapshot["snapshot"] == {}


class TestSessionStateReferencePreservation:
    """Lock in `load_session_state`'s reference-passing contract that #6080's STATE_DELTA computation depends on."""

    def test_load_session_state_returns_same_reference(self):
        # Direct unit test on the load_session_state contract: returning the
        # same dict object the caller passed in is load-bearing for STATE_DELTA.
        agent = Agent(name="Ref")
        session = AgentSession(session_id="test-session", session_data={})

        passed_in = {"counter": 0}
        returned = load_session_state(agent, session, passed_in)

        # Returned dict must BE the same object — not a copy, not a merge into new dict.
        assert returned is passed_in
        # The session's stored state must also be the same object so future loads
        # don't lose the reference chain.
        assert session.session_data is not None
        assert session.session_data["session_state"] is passed_in

    def test_load_session_state_propagates_mutation_via_reference(self):
        # If we mutate the returned dict, the session_data view must reflect it.
        # This is the reverse direction of the contract: writes through any holder
        # of the alias must be visible to all other holders.
        agent = Agent(name="Ref")
        session = AgentSession(session_id="test-session", session_data={})

        state = {"counter": 0}
        load_session_state(agent, session, state)

        state["counter"] = 42

        assert session.session_data is not None
        assert session.session_data["session_state"]["counter"] == 42
