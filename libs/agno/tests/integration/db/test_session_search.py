"""Exercise both PostgreSQL search implementations against an isolated schema."""

import inspect
from uuid import uuid4

import pytest
from sqlalchemy import text

from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.session import AgentSession, TeamSession


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_postgres_session_search(use_async):
    schema = "session_search_" + uuid4().hex
    db = (
        AsyncPostgresDb(db_url="postgresql+psycopg_async://ai:ai@localhost:5532/ai", db_schema=schema)
        if use_async
        else PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", db_schema=schema)
    )

    async def resolve(value):
        return await value if inspect.isawaitable(value) else value

    try:
        for session in [
            AgentSession(
                session_id="a",
                agent_id="support",
                user_id="alice",
                created_at=100,
                session_data={"session_name": "Billing 100%"},
            ),
            TeamSession(
                session_id="t",
                team_id="support",
                user_id="alice",
                created_at=200,
                session_data={"session_name": "Billing review"},
            ),
            AgentSession(
                session_id="b",
                agent_id="sales",
                user_id="bob",
                created_at=300,
                session_data={"session_name": "Billing"},
            ),
        ]:
            await resolve(db.upsert_session(session))
        rows, count = await resolve(
            db.search_sessions(
                filter_expr={
                    "op": "AND",
                    "conditions": [
                        {"op": "CONTAINS", "key": "session_name", "value": "BILLING"},
                        {"op": "GTE", "key": "created_at", "value": "1970-01-01T01:01:40+01:00"},
                    ],
                },
                user_id="alice",
                limit=1,
                page=2,
                sort_order="asc",
            )
        )
        assert count == 2
        assert [row["session_id"] for row in rows] == ["t"]
        rows, count = await resolve(
            db.search_sessions(
                filter_expr={"op": "CONTAINS", "key": "session_name", "value": "%"},
            )
        )
        assert count == 1
        assert rows[0]["session_id"] == "a"
        # Team rows have no agent_id; negation must preserve SQL NULL semantics.
        rows, count = await resolve(
            db.search_sessions(
                filter_expr={"op": "NOT", "condition": {"op": "EQ", "key": "agent_id", "value": "support"}}
            )
        )
        assert count == 1
        assert rows[0]["session_id"] == "b"
    finally:
        if use_async:
            async with db.db_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await db.db_engine.dispose()
        else:
            with db.db_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            db.db_engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_postgres_searches_summary_and_run_content(use_async):
    from agno.session.summary import SessionSummary

    schema = "session_recall_" + uuid4().hex
    db = (
        AsyncPostgresDb(db_url="postgresql+psycopg_async://ai:ai@localhost:5532/ai", db_schema=schema)
        if use_async
        else PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", db_schema=schema)
    )

    async def resolve(value):
        return await value if inspect.isawaitable(value) else value

    try:
        from agno.run.agent import RunInput, RunOutput

        for session in [
            AgentSession(
                session_id="billing",
                agent_id="support",
                created_at=100,
                summary=SessionSummary(summary="Fixed the 100% billing export"),
            ),
            AgentSession(session_id="other", agent_id="support", created_at=200),
            AgentSession(session_id="bare", agent_id="support", created_at=300),
        ]:
            await resolve(db.upsert_session(session))
        run = RunOutput(
            run_id="r1",
            session_id="other",
            agent_id="support",
            input=RunInput(input_content="The S3 export failed with AccessDenied"),
            content={"status": "investigating"},
        )
        await resolve(db.upsert_run(run, session_id="other", run_index=0))

        async def ids(filter_expr):
            rows, _ = await resolve(db.search_sessions(filter_expr=filter_expr))
            return sorted(row["session_id"] for row in rows)

        assert await ids({"op": "CONTAINS", "key": "summary", "value": "BILLING"}) == ["billing"]
        assert await ids({"op": "CONTAINS", "key": "summary", "value": "%"}) == ["billing"]
        assert await ids({"op": "CONTAINS", "key": "run_content", "value": "accessdenied"}) == ["other"]
        # Structured output is searched as its JSON text.
        assert await ids({"op": "CONTAINS", "key": "run_content", "value": "investigating"}) == ["other"]
        assert await ids({"op": "CONTAINS", "key": "run_content", "value": "%"}) == []
        # NOT EXISTS: sessions without a matching run are plain non-matches, so the negation keeps them.
        assert await ids({"op": "NOT", "condition": {"op": "CONTAINS", "key": "run_content", "value": "s3"}}) == [
            "bare",
            "billing",
        ]
    finally:
        if use_async:
            async with db.db_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await db.db_engine.dispose()
        else:
            with db.db_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            db.db_engine.dispose()
