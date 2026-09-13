"""Regression tests for get_last_run_output / aget_last_run_output on Agent
and Team subclasses.

Bug: the retrieval loop in ``agno.utils.agent`` checked
``entity.__class__.__name__ == "Agent" / "Team"`` which fails for user
subclasses like ``class CustomAgent(Agent): pass``. The fix uses
``isinstance()`` instead. These tests exercise the utility directly (no
LLM calls) using InMemoryDb + direct session inserts.
"""

import pytest

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.team.team import Team


class CustomAgent(Agent):
    pass


class CustomTeam(Team):
    pass


def _seed_agent_session(db: InMemoryDb, agent_id: str, session_id: str, run_id: str) -> None:
    db.upsert_session(
        AgentSession(
            session_id=session_id,
            agent_id=agent_id,
            runs=[
                RunOutput(
                    run_id=run_id,
                    agent_id=agent_id,
                    content="ok",
                    status=RunStatus.completed,
                )
            ],
            created_at=1,
            updated_at=1,
        )
    )


def _seed_team_session(db: InMemoryDb, team_id: str, session_id: str, run_id: str) -> None:
    db.upsert_session(
        TeamSession(
            session_id=session_id,
            team_id=team_id,
            runs=[
                TeamRunOutput(
                    run_id=run_id,
                    team_id=team_id,
                    content="ok",
                    status=RunStatus.completed,
                )
            ],
            created_at=1,
            updated_at=1,
        )
    )


def test_get_last_run_output_supports_agent_subclasses():
    db = InMemoryDb()
    _seed_agent_session(db, agent_id="custom-agent", session_id="s1", run_id="r1")

    agent = CustomAgent(id="custom-agent", db=db)
    last_output = agent.get_last_run_output(session_id="s1")

    assert last_output is not None
    assert last_output.run_id == "r1"


@pytest.mark.asyncio
async def test_aget_last_run_output_supports_agent_subclasses():
    db = InMemoryDb()
    _seed_agent_session(db, agent_id="custom-agent", session_id="s1", run_id="r1")

    agent = CustomAgent(id="custom-agent", db=db)
    last_output = await agent.aget_last_run_output(session_id="s1")

    assert last_output is not None
    assert last_output.run_id == "r1"


def test_get_last_run_output_supports_team_subclasses():
    db = InMemoryDb()
    _seed_team_session(db, team_id="custom-team", session_id="ts1", run_id="tr1")

    team = CustomTeam(id="custom-team", db=db, members=[])
    last_output = team.get_last_run_output(session_id="ts1")

    assert last_output is not None
    assert last_output.run_id == "tr1"


@pytest.mark.asyncio
async def test_aget_last_run_output_supports_team_subclasses():
    db = InMemoryDb()
    _seed_team_session(db, team_id="custom-team", session_id="ts1", run_id="tr1")

    team = CustomTeam(id="custom-team", db=db, members=[])
    last_output = await team.aget_last_run_output(session_id="ts1")

    assert last_output is not None
    assert last_output.run_id == "tr1"


def test_get_last_run_output_base_agent_still_works():
    """Baseline: the fix must not regress the base Agent case."""
    db = InMemoryDb()
    _seed_agent_session(db, agent_id="base-agent", session_id="s1", run_id="r1")

    agent = Agent(id="base-agent", db=db)
    last_output = agent.get_last_run_output(session_id="s1")

    assert last_output is not None
    assert last_output.run_id == "r1"


def test_get_last_run_output_util_cached_session_branch_subclasses():
    """The ``cached_session`` branch of the util must also handle subclasses.

    The public ``get_last_run_output()`` requires a ``session_id`` and never
    falls into that branch, so exercise the util directly.
    """
    from agno.utils.agent import get_last_run_output_util

    db = InMemoryDb()
    _seed_agent_session(db, agent_id="custom-agent", session_id="s1", run_id="r1")

    agent = CustomAgent(id="custom-agent", db=db)
    agent._cached_session = agent.get_session(session_id="s1")

    # No session_id -> forces the cached_session branch inside the util.
    last_output = get_last_run_output_util(agent, session_id=None)

    assert last_output is not None
    assert last_output.run_id == "r1"
