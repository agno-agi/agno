"""Unit tests for ``resolve_run_index``.

Regression tests for reviewer comment #3 on PR #8350. The helper previously
fell back to ``len(runs) - 1`` when it couldn't locate the run — masking
caller bugs by silently returning the index of an *unrelated* run. Two
concrete failure modes:

1. ``run.run_id is None`` — the loop was skipped and the tail index of some
   other run was returned. ``save_run(anon_run, run_index=<tail>)`` would
   then overwrite the neighbour's ``run_index`` in the runs table.
2. ``run.run_id`` set but not present in ``session.runs`` (caller forgot
   ``upsert_run``, or ID mismatch) — same silent collision at the tail.

The helper now returns ``None`` for both cases, which the DB stores as NULL
— an unambiguous "unknown" signal that never collides.
"""

from __future__ import annotations

import pytest

from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session._utils import resolve_run_index
from agno.session.agent import AgentSession


def _run(run_id: str | None) -> RunOutput:
    r = RunOutput(session_id="s1", status=RunStatus.completed)
    r.run_id = run_id  # type: ignore[assignment]
    return r


@pytest.fixture
def session_with_two_runs() -> AgentSession:
    s = AgentSession(session_id="s1")
    s.upsert_run(_run("r0"))
    s.upsert_run(_run("r1"))
    return s


class TestHappyPath:
    def test_returns_index_of_matching_run(self, session_with_two_runs: AgentSession):
        assert resolve_run_index(session_with_two_runs, _run("r0")) == 0
        assert resolve_run_index(session_with_two_runs, _run("r1")) == 1

    def test_returns_index_after_upsert_updates_in_place(self, session_with_two_runs: AgentSession):
        """``upsert_run`` on an existing run_id keeps the same slot — the
        resolved index must still match."""
        updated_r0 = _run("r0")
        session_with_two_runs.upsert_run(updated_r0)
        assert resolve_run_index(session_with_two_runs, updated_r0) == 0

    def test_dict_run_supported(self, session_with_two_runs: AgentSession):
        """Some callers pass a plain dict rather than a RunOutput."""
        assert resolve_run_index(session_with_two_runs, {"run_id": "r1"}) == 1


class TestReviewerComment3Regressions:
    """The two scenarios that produced silent data corruption under the old
    ``len(runs) - 1`` fallback."""

    def test_none_run_id_returns_none_not_tail_index(self, session_with_two_runs: AgentSession):
        """OLD behavior: ``run_id=None`` skipped the search and returned
        ``len(runs) - 1`` (== 1), the index of a real neighbouring run.
        NEW behavior: returns ``None`` so ``save_run`` writes NULL rather
        than clobbering the neighbour's ``run_index``."""
        anon = _run(None)
        assert resolve_run_index(session_with_two_runs, anon) is None, (
            "run_id=None must resolve to None — never to the tail index, "
            "which under the old code returned the position of an UNRELATED run."
        )

    def test_orphan_run_id_returns_none_not_tail_index(self, session_with_two_runs: AgentSession):
        """OLD behavior: an unknown run_id fell through the loop and
        returned ``len(runs) - 1`` — the position of the last real run.
        NEW behavior: returns ``None`` so the caller bug surfaces cleanly."""
        orphan = _run("ghost-never-upserted")
        assert resolve_run_index(session_with_two_runs, orphan) is None

    def test_none_run_id_on_single_run_session_would_have_masked_bug(self):
        """Extra-nasty variant: single-run session + anonymous new run.
        Old code returned 0, and ``save_run(anon, run_index=0)`` would step
        directly on the sole real run. New code returns None."""
        s = AgentSession(session_id="s1")
        real = _run("only-real-run")
        s.upsert_run(real)
        assert resolve_run_index(s, _run(None)) is None


class TestEmptyAndNoneInputs:
    def test_empty_runs_returns_none(self):
        s = AgentSession(session_id="s1")
        assert resolve_run_index(s, _run("anything")) is None

    def test_runs_is_none_returns_none(self):
        s = AgentSession(session_id="s1")
        s.runs = None  # type: ignore[assignment]
        assert resolve_run_index(s, _run("anything")) is None


class TestOrderingInvariant:
    """When the run IS present, its index must equal its actual position —
    the fallback used to lie about this for orphans, so we assert the
    invariant explicitly."""

    @pytest.mark.parametrize("target,expected_idx", [("r0", 0), ("r1", 1), ("r2", 2)])
    def test_index_matches_actual_position(self, target: str, expected_idx: int):
        s = AgentSession(session_id="s1")
        s.upsert_run(_run("r0"))
        s.upsert_run(_run("r1"))
        s.upsert_run(_run("r2"))
        assert resolve_run_index(s, _run(target)) == expected_idx
