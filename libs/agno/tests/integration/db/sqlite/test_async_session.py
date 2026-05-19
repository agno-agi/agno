"""Integration tests for AsyncSqliteDb session methods."""

import time
from typing import List

import pytest

from agno.db.base import SessionType
from agno.db.sqlite import AsyncSqliteDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession


def _make_agent_session_for_user(user_id: str, run_ids: List[str]) -> AgentSession:
    now = int(time.time())
    return AgentSession(
        session_id="async_upsert_user_change_agent",
        agent_id="async_upsert_user_change_agent_id",
        user_id=user_id,
        runs=[
            RunOutput(
                run_id=run_id,
                agent_id="async_upsert_user_change_agent_id",
                user_id=user_id,
                status=RunStatus.completed,
                messages=[],
            )
            for run_id in run_ids
        ],
        created_at=now,
        updated_at=now,
    )


def _make_team_session_for_user(user_id: str, run_ids: List[str]) -> TeamSession:
    now = int(time.time())
    return TeamSession(
        session_id="async_upsert_user_change_team",
        team_id="async_upsert_user_change_team_id",
        user_id=user_id,
        runs=[
            TeamRunOutput(
                run_id=run_id,
                team_id="async_upsert_user_change_team_id",
                user_id=user_id,
                status=RunStatus.completed,
                messages=[],
                created_at=now,
            )
            for run_id in run_ids
        ],
        created_at=now,
        updated_at=now,
    )


def _make_workflow_session_for_user(user_id: str, run_ids: List[str]) -> WorkflowSession:
    now = int(time.time())
    return WorkflowSession(
        session_id="async_upsert_user_change_workflow",
        workflow_id="async_upsert_user_change_workflow_id",
        user_id=user_id,
        runs=[
            WorkflowRunOutput(
                run_id=run_id,
                workflow_id="async_upsert_user_change_workflow_id",
                status=RunStatus.completed,
                created_at=now,
            )
            for run_id in run_ids
        ],
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("session_type", "session_factory"),
    [
        (SessionType.AGENT, _make_agent_session_for_user),
        (SessionType.TEAM, _make_team_session_for_user),
        (SessionType.WORKFLOW, _make_workflow_session_for_user),
    ],
)
async def test_upsert_session_updates_existing_session_when_user_id_changes(
    async_shared_db: AsyncSqliteDb,
    session_type: SessionType,
    session_factory,
):
    """Upserting an existing session with a new user_id updates instead of silently skipping."""
    await async_shared_db.upsert_session(session_factory("@alice:example.org", ["run_1"]))

    result = await async_shared_db.upsert_session(session_factory("@bob:example.org", ["run_1", "run_2"]))

    assert result is not None
    assert result.user_id == "@bob:example.org"
    assert result.runs is not None
    assert [run.run_id for run in result.runs] == ["run_1", "run_2"]

    stored = await async_shared_db.get_session(result.session_id, session_type)
    assert stored is not None
    assert stored.user_id == "@bob:example.org"
    assert stored.runs is not None
    assert [run.run_id for run in stored.runs] == ["run_1", "run_2"]
