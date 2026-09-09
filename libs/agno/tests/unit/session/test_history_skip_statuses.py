"""The set of run statuses excluded when rebuilding message history/context must
have a single source of truth.

``session.get_messages`` (agent + team) filters these out *before* slicing the
last N runs, and the DB-level bounded read (``agno.db.utils.HISTORY_SKIP_STATUSES``)
must reproduce exactly the same filter — otherwise a ``runs_limit=N`` read and a
full-load read return different history windows for the same session. Both now
derive from ``agno.run.base.HISTORY_SKIP_STATUSES``; these tests guard the wiring
so the two representations can never drift.
"""

from __future__ import annotations

from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import HISTORY_SKIP_STATUSES, RunStatus
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession


def test_db_string_set_matches_canonical_enum():
    """The DB-facing string list must equal the canonical enum values."""
    from agno.db.utils import HISTORY_SKIP_STATUSES as db_strings

    assert db_strings == [status.value for status in HISTORY_SKIP_STATUSES]
    assert set(db_strings) == {"PAUSED", "CANCELLED", "ERROR", "REGENERATED"}


def test_canonical_contains_expected_statuses():
    assert set(HISTORY_SKIP_STATUSES) == {
        RunStatus.paused,
        RunStatus.cancelled,
        RunStatus.error,
        RunStatus.regenerated,
    }


def _contents(messages) -> list:
    return [m.content for m in messages]


def test_agent_get_messages_skips_every_canonical_status():
    session = AgentSession(session_id="s1", agent_id="agent-1")
    session.upsert_run(
        RunOutput(
            run_id="ok", agent_id="agent-1", status=RunStatus.completed, messages=[Message(role="user", content="keep")]
        )
    )
    for i, status in enumerate(HISTORY_SKIP_STATUSES):
        session.upsert_run(
            RunOutput(
                run_id=f"drop{i}",
                agent_id="agent-1",
                status=status,
                messages=[Message(role="user", content=f"drop{i}")],
            )
        )

    contents = _contents(session.get_messages())
    assert "keep" in contents
    assert not any(c.startswith("drop") for c in contents)


def test_team_get_messages_skips_regenerated():
    """Regression for the team alignment: TeamSession.get_messages previously did
    NOT skip REGENERATED runs (only agent did). Now both use the shared set."""
    session = TeamSession(session_id="t1", team_id="team-1")
    session.upsert_run(
        TeamRunOutput(
            run_id="ok", team_id="team-1", status=RunStatus.completed, messages=[Message(role="user", content="keep")]
        )
    )
    session.upsert_run(
        TeamRunOutput(
            run_id="regen",
            team_id="team-1",
            status=RunStatus.regenerated,
            messages=[Message(role="user", content="drop")],
        )
    )

    contents = _contents(session.get_messages())
    assert "keep" in contents
    assert "drop" not in contents
