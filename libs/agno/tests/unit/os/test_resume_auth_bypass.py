"""
Test: /resume endpoint auth bypass — can User B access User A's run?

This test proves that the /resume endpoint checks agent-level access
but NOT run-level ownership. Two users who both have access to the
same agent can read each other's conversation history.

The bug exists at three layers:
1. require_resource_access only checks agent_id, not run_id
2. EventsBuffer has no user_id tracking
3. DB fallback (PATH 3) has no user_id filter
"""

import pytest

from agno.os.managers import EventsBuffer, SSESubscriberManager
from agno.run.agent import RunContentEvent, RunStartedEvent
from agno.run.base import RunStatus


class TestResumeAuthBypass:
    """Prove that EventsBuffer has no user ownership concept."""

    def test_any_caller_can_read_any_run_events(self):
        """EventsBuffer.get_events() has no user_id parameter.
        Anyone who knows the run_id gets all events."""
        buf = EventsBuffer(max_events_per_run=100)

        # User A creates a run with sensitive data
        user_a_run_id = "user-a-private-run-123"
        buf.add_event(user_a_run_id, RunContentEvent(content="My salary is $150,000"))
        buf.add_event(user_a_run_id, RunContentEvent(content="My SSN is 123-45-6789"))
        buf.add_event(user_a_run_id, RunContentEvent(content="Fire Bob from the team"))

        # User B calls get_events with User A's run_id
        # There is NO user_id check — just a dict lookup
        stolen_events = buf.get_events(user_a_run_id)

        # User B gets ALL of User A's private conversation
        assert len(stolen_events) == 3
        assert stolen_events[0].content == "My salary is $150,000"
        assert stolen_events[1].content == "My SSN is 123-45-6789"
        assert stolen_events[2].content == "Fire Bob from the team"

    def test_buffer_has_no_user_id_tracking(self):
        """EventsBuffer stores no information about WHO created the run."""
        buf = EventsBuffer(max_events_per_run=100)

        buf.add_event("run-123", RunContentEvent(content="secret"))

        # Check metadata — there is no user_id field
        metadata = buf.run_metadata.get("run-123", {})
        assert "user_id" not in metadata, (
            "EventsBuffer.run_metadata has no user_id field. "
            "There is no way to check ownership."
        )

    def test_get_events_has_no_user_parameter(self):
        """get_events() signature doesn't accept user_id at all."""
        buf = EventsBuffer(max_events_per_run=100)
        buf.add_event("run-123", RunContentEvent(content="data"))

        # The method signature is: get_events(run_id, last_event_index=None)
        # There is no user_id parameter to filter by
        import inspect
        sig = inspect.signature(buf.get_events)
        param_names = list(sig.parameters.keys())

        assert "user_id" not in param_names, (
            f"get_events parameters are {param_names} — no user_id. "
            f"Any caller who knows run_id can read all events."
        )

    def test_add_event_has_no_user_parameter(self):
        """add_event() doesn't record which user created the run."""
        buf = EventsBuffer(max_events_per_run=100)

        import inspect
        sig = inspect.signature(buf.add_event)
        param_names = list(sig.parameters.keys())

        assert "user_id" not in param_names, (
            f"add_event parameters are {param_names} — no user_id. "
            f"The buffer has no concept of run ownership."
        )

    def test_subscriber_manager_has_no_user_check(self):
        """SSESubscriberManager.subscribe() has no user_id parameter."""
        mgr = SSESubscriberManager()

        import inspect
        sig = inspect.signature(mgr.subscribe)
        param_names = list(sig.parameters.keys())

        assert "user_id" not in param_names, (
            f"subscribe parameters are {param_names} — no user_id. "
            f"Any caller who knows run_id can subscribe to live events."
        )

    def test_get_run_status_has_no_user_check(self):
        """get_run_status() returns status for any run_id, no ownership check."""
        buf = EventsBuffer(max_events_per_run=100)

        # User A's run
        buf.add_event("user-a-run", RunContentEvent(content="private"))
        buf.set_run_completed("user-a-run", RunStatus.completed)

        # User B can check the status of User A's run
        status = buf.get_run_status("user-a-run")
        assert status == RunStatus.completed, (
            "User B can see User A's run status without any auth check"
        )

    def test_cross_user_scenario_with_jwt(self):
        """
        Simulate the full attack scenario with JWT auth enabled.

        With JWT: require_resource_access checks "Can User B run this agent?"
        Answer: YES (both users have access to the same shared agent)

        It does NOT check: "Does this run_id belong to User B?"
        Answer: NO — but this question is never asked.
        """
        buf = EventsBuffer(max_events_per_run=100)

        # User A (Alice) starts a run on the shared "assistant" agent
        alice_run_id = "alice-run-uuid-456"
        buf.add_event(alice_run_id, RunContentEvent(content="Draft my resignation letter"))
        buf.add_event(alice_run_id, RunContentEvent(content="Dear Manager, I am writing to..."))
        buf.set_run_completed(alice_run_id, RunStatus.completed)

        # User B (Bob) also has access to the "assistant" agent
        # Bob obtains Alice's run_id (from logs, shared URL, browser history, etc.)
        # Bob calls /resume with Alice's run_id

        # The auth check (require_resource_access) passes because:
        #   check_resource_access(request, "assistant", "agents", "run") → True
        # (Bob has access to the "assistant" agent)

        # Then the code calls event_buffer.get_events(alice_run_id)
        # with NO user_id check:
        bobs_view = buf.get_events(alice_run_id)

        # Bob sees Alice's private resignation letter
        assert len(bobs_view) == 2
        assert "resignation" in bobs_view[0].content
        assert "Dear Manager" in bobs_view[1].content
        # This is the data privacy violation
