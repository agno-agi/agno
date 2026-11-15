"""Tests for the owner fallback used when a paused run is resumed.

A resume rarely carries the owner, and losing it falls back to ``user_id=None`` — the
unscoped admin view over every tenant.
"""

from agno.agent._run import _resolve_continue_owner
from agno.run.agent import RunOutput
from agno.session import AgentSession


def _session(*runs: RunOutput) -> AgentSession:
    return AgentSession(session_id="s", runs=list(runs))


class TestResolveContinueOwner:
    def test_run_response_carries_the_owner(self):
        run = RunOutput(run_id="r1", session_id="s", user_id="alice")

        assert _resolve_continue_owner(run, run_id="r1", session=None) == "alice"

    def test_persisted_run_carries_the_owner_when_only_a_run_id_is_given(self):
        session = _session(
            RunOutput(run_id="other", session_id="s", user_id="bob"),
            RunOutput(run_id="r1", session_id="s", user_id="alice"),
        )

        assert _resolve_continue_owner(None, run_id="r1", session=session) == "alice"

    def test_unknown_run_id_resolves_to_no_owner(self):
        session = _session(RunOutput(run_id="r1", session_id="s", user_id="alice"))

        assert _resolve_continue_owner(None, run_id="missing", session=session) is None

    def test_run_without_an_owner_stays_unscoped(self):
        # No owner anywhere is the admin view — an owner must never be invented.
        run = RunOutput(run_id="r1", session_id="s")

        assert _resolve_continue_owner(run, run_id="r1", session=None) is None

    def test_run_response_wins_over_the_persisted_run(self):
        session = _session(RunOutput(run_id="r1", session_id="s", user_id="bob"))
        run = RunOutput(run_id="r1", session_id="s", user_id="alice")

        assert _resolve_continue_owner(run, run_id="r1", session=session) == "alice"
