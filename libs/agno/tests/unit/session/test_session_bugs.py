"""BUG-020: Session deserialization IndexError on empty runs list.

Both AgentSession.from_dict() and TeamSession.from_dict() check:
    if runs is not None and isinstance(runs[0], dict)
When runs=[] (empty list), runs[0] raises IndexError.
"""

import pytest


class TestBUG020SessionEmptyRuns:
    def test_agent_session_empty_runs_crashes(self):
        """AgentSession.from_dict with runs=[] raises IndexError."""
        from agno.session.agent import AgentSession

        with pytest.raises(IndexError):
            AgentSession.from_dict({"session_id": "test-1", "runs": []})

    def test_team_session_empty_runs_crashes(self):
        """TeamSession.from_dict with runs=[] raises IndexError."""
        from agno.session.team import TeamSession

        with pytest.raises(IndexError):
            TeamSession.from_dict({"session_id": "test-1", "runs": []})

    def test_agent_session_none_runs_works(self):
        """Control: runs=None doesn't crash."""
        from agno.session.agent import AgentSession

        result = AgentSession.from_dict({"session_id": "test-1", "runs": None})
        assert result is not None
        assert result.session_id == "test-1"

    def test_team_session_none_runs_works(self):
        """Control: runs=None doesn't crash."""
        from agno.session.team import TeamSession

        result = TeamSession.from_dict({"session_id": "test-1", "runs": None})
        assert result is not None
        assert result.session_id == "test-1"

    def test_agent_session_missing_runs_key_works(self):
        """Control: missing runs key doesn't crash."""
        from agno.session.agent import AgentSession

        result = AgentSession.from_dict({"session_id": "test-1"})
        assert result is not None
