import os

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.run import RunContext
from agno.team import Team

from ._agui_sse import assert_event_absent, get_event_types, make_request_body, parse_sse_events

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from agno.os.interfaces.agui import AGUI  # noqa: E402

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set"),
]

# =============================================================================
# Tools that mutate session state
# =============================================================================


def add_item_to_list(run_context: RunContext, item: str) -> str:
    """Add an item to the shopping list in session state."""
    if run_context.session_state is None:
        run_context.session_state = {}
    if "items" not in run_context.session_state:
        run_context.session_state["items"] = []
    run_context.session_state["items"].append(item)
    return f"Added {item}. List now has {len(run_context.session_state['items'])} items."


def increment_counter(run_context: RunContext, amount: int = 1) -> str:
    """Increment a counter in session state."""
    if run_context.session_state is None:
        run_context.session_state = {}
    current = run_context.session_state.get("counter", 0)
    run_context.session_state["counter"] = current + amount
    return f"Counter is now {run_context.session_state['counter']}"


# =============================================================================
# Integration Tests - Real Agent, Real LLM, Real State
# =============================================================================


class TestAgentStateEventsIntegration:
    """Integration tests for AG-UI state events with real agent and LLM calls."""

    @pytest.fixture
    def state_agent(self):
        return Agent(
            name="state-test-agent",
            model=OpenAIChat(id="gpt-4o-mini"),
            tools=[add_item_to_list, increment_counter],
            instructions="""You help manage a shopping list and counter.
When asked to add items, use the add_item_to_list tool.
When asked to increment, use the increment_counter tool.
Be brief in your responses.""",
            telemetry=False,
        )

    @pytest.fixture
    def client(self, state_agent: Agent):
        agent_os = AgentOS(agents=[state_agent], interfaces=[AGUI(agent=state_agent)], telemetry=False)
        # As a context manager so the app lifespan runs, which is what a served AgentOS does.
        with TestClient(agent_os.get_app()) as client:
            yield client

    def test_initial_and_final_snapshot_with_real_agent(self, client):
        """Real agent emits initial and final STATE_SNAPSHOT when state is provided."""
        response = client.post(
            "/agui",
            json=make_request_body("Say hello briefly", state={"counter": 0}),
        )

        assert response.status_code == 200
        events = parse_sse_events(response.text)
        types = get_event_types(events)

        # Must have initial and final snapshots
        assert "RUN_STARTED" in types
        assert types.count("STATE_SNAPSHOT") >= 2

        # Initial snapshot right after RUN_STARTED
        run_started_idx = types.index("RUN_STARTED")
        first_snapshot_idx = types.index("STATE_SNAPSHOT")
        assert first_snapshot_idx == run_started_idx + 1

        # Final snapshot right before RUN_FINISHED
        assert "RUN_FINISHED" in types
        run_finished_idx = types.index("RUN_FINISHED")
        last_snapshot_idx = len(types) - 1 - types[::-1].index("STATE_SNAPSHOT")
        assert last_snapshot_idx == run_finished_idx - 1

    def test_no_state_events_without_state(self, client):
        """Real agent emits no state events when state is not provided."""
        response = client.post(
            "/agui",
            json=make_request_body("Say hello briefly", state=None),
        )

        assert response.status_code == 200
        events = parse_sse_events(response.text)
        types = get_event_types(events)

        assert_event_absent(types, "STATE_SNAPSHOT")
        assert_event_absent(types, "STATE_DELTA")
        assert "RUN_FINISHED" in types

    def test_state_delta_emitted_when_tool_mutates_state(self, client):
        """Real tool mutation emits STATE_DELTA event."""
        response = client.post(
            "/agui",
            json=make_request_body(
                "Add 'milk' to my list using the tool",
                state={"items": []},
            ),
        )

        assert response.status_code == 200
        events = parse_sse_events(response.text)
        types = get_event_types(events)

        # Should have tool call events
        assert "TOOL_CALL_START" in types
        assert "TOOL_CALL_RESULT" in types

        # Should have STATE_DELTA after tool completes
        assert "STATE_DELTA" in types, f"Missing STATE_DELTA. Events: {types}"

        # Delta should be after tool result
        delta_idx = types.index("STATE_DELTA")
        result_idx = types.index("TOOL_CALL_RESULT")
        assert delta_idx > result_idx

        # Verify delta contains the items change
        delta_event = next(e for e in events if e.get("type") == "STATE_DELTA")
        paths = [op["path"] for op in delta_event["delta"]]
        assert any("items" in p for p in paths), f"Expected items path in delta, got: {paths}"

        # Final snapshot should show the updated state
        final_snapshot = [e for e in events if e.get("type") == "STATE_SNAPSHOT"][-1]
        assert "milk" in str(final_snapshot["snapshot"].get("items", []))

    def test_increment_counter_emits_delta(self, client):
        """Increment tool mutation emits STATE_DELTA with counter change."""
        response = client.post(
            "/agui",
            json=make_request_body(
                "Increment the counter by 5 using the tool",
                state={"counter": 0},
            ),
        )

        assert response.status_code == 200
        events = parse_sse_events(response.text)
        types = get_event_types(events)

        assert "STATE_DELTA" in types

        # Verify delta has counter path
        delta_event = next(e for e in events if e.get("type") == "STATE_DELTA")
        paths = [op["path"] for op in delta_event["delta"]]
        assert "/counter" in paths

        # Final snapshot should have updated counter
        final_snapshot = [e for e in events if e.get("type") == "STATE_SNAPSHOT"][-1]
        assert final_snapshot["snapshot"]["counter"] == 5

    def test_nested_state_mutation(self, client):
        """Nested state changes are tracked in delta."""
        response = client.post(
            "/agui",
            json=make_request_body(
                "Add 'eggs' to my list",
                state={"metadata": {"created": "today"}, "items": []},
            ),
        )

        assert response.status_code == 200
        events = parse_sse_events(response.text)

        # Final snapshot should preserve nested metadata
        final_snapshot = [e for e in events if e.get("type") == "STATE_SNAPSHOT"][-1]
        assert final_snapshot["snapshot"]["metadata"]["created"] == "today"
        assert "eggs" in str(final_snapshot["snapshot"].get("items", []))


# =============================================================================
# Team Integration Tests
# =============================================================================


class TestTeamStateEventsIntegration:
    """Integration tests for AG-UI state events with real team."""

    @pytest.fixture
    def state_team(self):
        member = Agent(
            name="list-manager",
            model=OpenAIChat(id="gpt-4o-mini"),
            tools=[add_item_to_list],
            instructions="You manage a shopping list. Use add_item_to_list when asked to add items.",
            telemetry=False,
        )
        return Team(
            name="state-test-team",
            members=[member],
            instructions="Delegate list management to the list-manager agent.",
            telemetry=False,
        )

    @pytest.fixture
    def team_client(self, state_team: Team):
        agent_os = AgentOS(teams=[state_team], interfaces=[AGUI(team=state_team)], telemetry=False)
        # As a context manager so the app lifespan runs, which is what a served AgentOS does.
        with TestClient(agent_os.get_app()) as client:
            yield client

    def test_team_emits_state_snapshots(self, team_client):
        """Team emits initial and final STATE_SNAPSHOT."""
        response = team_client.post(
            "/agui",
            json=make_request_body("Say hello", state={"task": "pending"}),
        )

        assert response.status_code == 200
        events = parse_sse_events(response.text)
        types = get_event_types(events)

        assert "RUN_STARTED" in types
        assert "STATE_SNAPSHOT" in types
        assert "RUN_FINISHED" in types

    def test_team_no_state_events_without_state(self, team_client):
        """Team emits no state events when state is None."""
        response = team_client.post(
            "/agui",
            json=make_request_body("Say hello", state=None),
        )

        assert response.status_code == 200
        events = parse_sse_events(response.text)
        types = get_event_types(events)

        assert_event_absent(types, "STATE_SNAPSHOT")
        assert_event_absent(types, "STATE_DELTA")
