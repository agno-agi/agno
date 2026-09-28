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

import pytest

from agno.models.message import Message
from agno.run.agent import RunInput, RunOutput
from agno.run.base import HISTORY_SKIP_STATUSES, RunStatus
from agno.run.team import TeamRunInput, TeamRunOutput
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


# --- unverified runs: kept in history, their re-entry report kept out of chat history ---

REPORT = (
    '<verification attempt="1/3" nonce="0123456789abcdef">\n[FAIL] report_exists: report.md is missing\n</verification>'
)


def _run(kind: str, run_id: str, status: RunStatus, prompt: str, answer: str, report: bool = False):
    messages = [Message(role="user", content=prompt), Message(role="assistant", content="draft")]
    if report:
        messages.append(Message(role="user", content=REPORT))
        messages.append(Message(role="assistant", content=answer))
    if kind == "team":
        return TeamRunOutput(
            run_id=run_id,
            team_id="team-1",
            status=status,
            input=TeamRunInput(input_content=prompt),
            content=answer,
            messages=messages,
        )
    return RunOutput(
        run_id=run_id,
        agent_id="agent-1",
        status=status,
        input=RunInput(input_content=prompt),
        content=answer,
        messages=messages,
    )


def test_team_history_keeps_unverified_runs():
    session = TeamSession(session_id="t1", team_id="team-1")
    session.upsert_run(_run("team", "r1", RunStatus.completed, "q1", "a1"))
    session.upsert_run(_run("team", "r2", RunStatus.unverified, "q2", "a2"))
    session.upsert_run(_run("team", "r3", RunStatus.error, "q3", "a3"))

    assert session.get_team_history() == [("q1", "a1"), ("q2", "a2")]
    assert session.get_team_history(num_runs=1) == [("q2", "a2")]
    assert session.get_team_history(team_id="team-1") == [("q1", "a1"), ("q2", "a2")]


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_chat_history_drops_the_verification_report(kind):
    session = (
        TeamSession(session_id="t1", team_id="team-1")
        if kind == "team"
        else AgentSession(session_id="s1", agent_id="agent-1")
    )
    session.upsert_run(_run(kind, "r1", RunStatus.unverified, "q1", "a1", report=True))

    assert [m.content for m in session.get_chat_history()] == ["q1", "draft", "a1"]
    # A person's message that only starts with the tag stays in chat history
    typed = '<verification attempt="1/3"> is this tag valid XML?'
    session.upsert_run(_run(kind, "r2", RunStatus.completed, typed, "yes"))
    assert typed in [m.content for m in session.get_chat_history()]
    # Model history keeps the report: it is real transcript the model re-reads.
    assert any(str(m.content).startswith("<verification ") for m in session.get_messages())
