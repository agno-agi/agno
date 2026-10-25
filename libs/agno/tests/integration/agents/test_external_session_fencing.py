"""Worker session identity commits atomically with the fenced run on PostgreSQL."""

import inspect
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, event, text

from agno.agents.base import BaseExternalAgent
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.concurrency import worker_managed_execution


@pytest_asyncio.fixture(params=[False, True], ids=["postgres", "async-postgres"])
async def agent(request):
    url = os.getenv("AGNO_TEST_TRANSCRIPT_POSTGRES_URL")
    if not url:
        pytest.skip("Set AGNO_TEST_TRANSCRIPT_POSTGRES_URL")
    schema = "external_fence_" + uuid4().hex
    cls = AsyncPostgresDb if request.param else PostgresDb
    db = cls(db_url=url, db_schema=schema)
    component = BaseExternalAgent(id="external", db=db)
    session = component._create_session("s", "owner")
    session.session_data = {"claude_sdk_session_id": "original", "codex_thread_id": "original"}
    await component._apersist_run_in_session(
        session,
        RunOutput(
            run_id="r",
            session_id="s",
            agent_id="external",
            user_id="owner",
            status=RunStatus.running,
            queue_attempt=2,
        ),
        strict=True,
    )
    try:
        yield component
    finally:
        if request.param:
            await db.db_engine.dispose()
        else:
            db.db_engine.dispose()
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))
        engine.dispose()


async def save(agent, attempt, identity):
    session = agent._create_session("s", "owner")
    session.session_data = {"claude_sdk_session_id": identity, "codex_thread_id": identity}
    with worker_managed_execution("r", "worker", attempt):
        await agent._apersist_run_in_session(
            session,
            RunOutput(
                run_id="r",
                session_id="s",
                agent_id="external",
                user_id="owner",
                content=identity,
                status=RunStatus.completed,
            ),
        )


@pytest.mark.asyncio
async def test_session_identity_and_run_share_attempt_fence(agent):
    await save(agent, 2, "winner")
    await save(agent, 1, "stale")
    session = await agent.aget_session("s", "owner")
    assert session.session_data == {"claude_sdk_session_id": "winner", "codex_thread_id": "winner"}
    assert session.get_run("r").content == "winner"
    assert session.get_run("r").queue_attempt == 2


@pytest.mark.asyncio
async def test_session_write_failure_rolls_back_terminal_run(agent):
    engine = agent.db.db_engine
    if isinstance(agent.db, AsyncPostgresDb):
        engine = engine.sync_engine

    def reject_session_update(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE ") and ".agno_sessions " in statement:
            raise RuntimeError("injected session metadata failure")

    event.listen(engine, "before_cursor_execute", reject_session_update)
    try:
        with pytest.raises(RuntimeError, match="injected session metadata failure"):
            await save(agent, 2, "uncommitted")
    finally:
        event.remove(engine, "before_cursor_execute", reject_session_update)
    session = await agent.aget_session("s", "owner")
    assert session.session_data["claude_sdk_session_id"] == "original"
    assert session.get_run("r").status == RunStatus.running
    assert session.get_run("r").content is None
    await save(agent, 2, "committed")
    assert (await agent.aget_session("s", "owner")).session_data["claude_sdk_session_id"] == "committed"


@pytest.mark.asyncio
async def test_missing_worker_row_cannot_commit_session_or_terminal_run(agent):
    result = agent.db.delete_run("r")
    if inspect.isawaitable(result):
        await result
    with pytest.raises(RuntimeError, match="prepared worker run"):
        await save(agent, 2, "uncommitted")
    session = await agent.aget_session("s", "owner")
    assert session.session_data["claude_sdk_session_id"] == "original"
    assert session.get_run("r") is None


@pytest.mark.asyncio
async def test_missing_session_table_cannot_commit_terminal_run(agent, monkeypatch):
    original = agent.db._get_table
    if isinstance(agent.db, AsyncPostgresDb):

        async def get_table(table_type, **kwargs):
            return None if table_type == "sessions" else await original(table_type=table_type, **kwargs)
    else:

        def get_table(table_type, **kwargs):
            return None if table_type == "sessions" else original(table_type=table_type, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(agent.db, "_get_table", get_table)
        with pytest.raises(RuntimeError, match="session table"):
            await save(agent, 2, "uncommitted")
    assert (await agent.aget_run_output("r", "s", "owner")).status == RunStatus.running


@pytest.mark.asyncio
async def test_session_ownership_rejection_rolls_back_run(agent):
    # Model a legacy run row whose owner no longer matches the session owner.
    engine = create_engine(os.environ["AGNO_TEST_TRANSCRIPT_POSTGRES_URL"])
    try:
        with engine.begin() as conn:
            conn.execute(
                text('UPDATE "' + agent.db.db_schema + '".agno_sessions SET user_id = :user'), {"user": "other"}
            )
    finally:
        engine.dispose()
    with pytest.raises(RuntimeError, match="owned session"):
        await save(agent, 2, "uncommitted")
    session = await agent.aget_session("s", "other")
    assert session.session_data["claude_sdk_session_id"] == "original"
    result = agent.db.get_run("r")
    if inspect.isawaitable(result):
        result = await result
    assert result.status == RunStatus.running
