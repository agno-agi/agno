"""Regression tests: Session.to_dict(include_runs=False) must not mutate self.

The runs-denormalization work made adapters call ``to_dict(include_runs=False)``
to skip the deep run serialization when writing the session row. The first
implementation excluded runs by temporarily nulling ``self.runs`` during
``asdict(self)`` -- a live, possibly shared/cached session object. A concurrent
reader on another thread could observe ``session.runs is None`` mid-serialize.
The fix serializes a shallow copy, so ``self`` is never mutated.
"""

from __future__ import annotations

from agno.session.agent import AgentSession
from agno.session.team import TeamSession


class _FakeRun:
    def __init__(self, run_id: str):
        self.run_id = run_id

    def to_dict(self) -> dict:
        return {"run_id": self.run_id}


class TestAgentSessionToDict:
    def test_include_runs_false_does_not_mutate_self(self):
        runs = [_FakeRun("r1"), _FakeRun("r2")]
        session = AgentSession(session_id="s1", runs=runs)

        result = session.to_dict(include_runs=False)

        # self.runs must be the exact same object, untouched.
        assert session.runs is runs
        assert "runs" not in result

    def test_include_runs_true_preserves_self_and_serializes(self):
        runs = [_FakeRun("r1")]
        session = AgentSession(session_id="s1", runs=runs)

        result = session.to_dict(include_runs=True)

        assert session.runs is runs
        assert result["runs"] == [{"run_id": "r1"}]

    def test_no_runs_is_fine(self):
        session = AgentSession(session_id="s1")
        assert session.to_dict(include_runs=False).get("runs") is None
        assert session.to_dict(include_runs=True)["runs"] is None


class TestTeamSessionToDict:
    def test_include_runs_false_does_not_mutate_self(self):
        runs = [_FakeRun("r1"), _FakeRun("r2")]
        session = TeamSession(session_id="s1", runs=runs)

        result = session.to_dict(include_runs=False)

        assert session.runs is runs
        assert "runs" not in result

    def test_include_runs_true_preserves_self_and_serializes(self):
        runs = [_FakeRun("r1")]
        session = TeamSession(session_id="s1", runs=runs)

        result = session.to_dict(include_runs=True)

        assert session.runs is runs
        assert result["runs"] == [{"run_id": "r1"}]
