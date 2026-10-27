"""Session search contracts across SQL, asynchronous SQL, and portable adapters."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agno.db.base import AsyncBaseDb
from agno.db.in_memory import InMemoryDb
from agno.db.json import JsonDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os.routers.session.session import attach_routes
from agno.session import AgentSession, TeamSession, WorkflowSession


def eq(key, value):
    return {"op": "EQ", "key": key, "value": value}


def build_client(db, isolated=False):
    app = FastAPI()

    @app.middleware("http")
    async def scope(request, call_next):
        request.state.user_id = "alice"
        request.state.scopes = ["sessions:read"]
        request.state.user_isolation_enabled = isolated
        return await call_next(request)

    router = APIRouter()
    attach_routes(router, {"test": [db]})
    app.include_router(router)
    return TestClient(app)


@pytest.fixture(params=["sqlite", "async_sqlite", "memory", "json"])
def db(request, tmp_path):
    if request.param == "sqlite":
        database = SqliteDb(db_file=str(tmp_path / "test.db"))
    elif request.param == "async_sqlite":
        database = AsyncSqliteDb(db_file=str(tmp_path / "test.db"))
    elif request.param == "json":
        database = JsonDb(db_path=str(tmp_path))
    else:
        database = InMemoryDb()
    sessions = [
        AgentSession(
            session_id="agent-1",
            agent_id="support",
            user_id="alice",
            created_at=100,
            session_data={"session_name": "Billing 100%", "other": "unrelated"},
        ),
        TeamSession(
            session_id="team-1",
            team_id="support-team",
            user_id="alice",
            created_at=200,
            session_data={"session_name": "Billing review"},
        ),
        WorkflowSession(
            session_id="workflow-1",
            workflow_id="support-flow",
            user_id="bob",
            created_at=300,
            session_data={"session_name": "Report"},
        ),
        AgentSession(session_id="agent-2", agent_id="sales", user_id="alice", created_at=400),
    ]
    for session in sessions:
        if isinstance(database, AsyncBaseDb):
            asyncio.run(database.upsert_session(session))
        else:
            database.upsert_session(session)
    return database


def test_schema_is_not_captured_as_session_id(db):
    response = build_client(db).get("/sessions/filter-schema")
    assert response.status_code == 200
    fields = {field["key"] for field in response.json()["fields"]}
    assert fields == {
        "session_id",
        "session_name",
        "session_type",
        "user_id",
        "agent_id",
        "team_id",
        "workflow_id",
        "created_at",
        "updated_at",
    }


def test_nested_filter_counts_before_pagination(db):
    response = build_client(db).post(
        "/sessions/search",
        json={
            "filter": {
                "op": "AND",
                "conditions": [
                    eq("user_id", "alice"),
                    {"op": "OR", "conditions": [eq("agent_id", "support"), eq("team_id", "support-team")]},
                ],
            },
            "limit": 1,
            "page": 2,
            "sort_order": "asc",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [s["session_id"] for s in body["data"]] == ["team-1"]
    assert body["meta"]["total_count"] == 2
    assert body["meta"]["total_pages"] == 2


@pytest.mark.parametrize(
    "expression,expected",
    [
        ({"op": "CONTAINS", "key": "session_name", "value": "BILLING"}, ["team-1", "agent-1"]),
        ({"op": "CONTAINS", "key": "session_name", "value": "%"}, ["agent-1"]),
        ({"op": "CONTAINS", "key": "session_name", "value": "unrelated"}, []),
        ({"op": "STARTSWITH", "key": "session_name", "value": "bill"}, ["team-1", "agent-1"]),
        ({"op": "IN", "key": "session_type", "values": ["team", "workflow"]}, ["workflow-1", "team-1"]),
        ({"op": "GTE", "key": "created_at", "value": "1970-01-01T01:05:00+01:00"}, ["agent-2", "workflow-1"]),
        ({"op": "LT", "key": "updated_at", "value": 200}, ["agent-1"]),
        ({"op": "NEQ", "key": "session_name", "value": "Report"}, ["team-1", "agent-1"]),
    ],
)
def test_filter_semantics(db, expression, expected):
    response = build_client(db).post("/sessions/search", json={"filter": expression})
    assert response.status_code == 200, response.text
    assert [s["session_id"] for s in response.json()["data"]] == expected


def test_type_selector_and_user_isolation_combine_with_expression(db):
    response = build_client(db, isolated=True).post(
        "/sessions/search",
        json={
            "filter": {"op": "OR", "conditions": [eq("user_id", "bob"), eq("user_id", "alice")]},
            "session_type": "agent",
        },
    )
    assert response.status_code == 200
    assert [s["session_id"] for s in response.json()["data"]] == ["agent-2", "agent-1"]
    denied = build_client(db, isolated=True).post("/sessions/search", json={"filter": eq("user_id", "bob")})
    assert denied.json()["meta"]["total_count"] == 0


@pytest.mark.parametrize(
    "expression",
    [
        {},
        eq("runs", "secret"),
        eq("user_id", None),
        eq("session_type", "invalid"),
        {"op": "IN", "key": "user_id", "values": "alice"},
        {"op": "AND", "conditions": []},
        {"op": "OR", "conditions": [None]},
        {"op": "GT", "key": "user_id", "value": "alice"},
        {"op": "GTE", "key": "created_at", "value": "yesterday"},
    ],
)
def test_invalid_filters_rejected_even_with_empty_database(expression):
    response = build_client(InMemoryDb()).post("/sessions/search", json={"filter": expression})
    assert response.status_code == 400


def test_deep_filter_rejected():
    expression = eq("user_id", "alice")
    for _ in range(12):
        expression = {"op": "AND", "conditions": [expression]}
    assert build_client(InMemoryDb()).post("/sessions/search", json={"filter": expression}).status_code == 400


@pytest.mark.parametrize("body", [{"page": 0}, {"limit": 0}, {"limit": 1001}, {"sort_by": "runs"}])
def test_invalid_pagination_and_sort(body):
    assert build_client(InMemoryDb()).post("/sessions/search", json=body).status_code == 422


def test_fallback_scans_more_than_one_batch():
    db = InMemoryDb()
    for i in range(205):
        db.upsert_session(AgentSession(session_id=str(i), agent_id="a", user_id="alice", created_at=i))
    response = build_client(db).post(
        "/sessions/search",
        json={
            "filter": {"op": "GTE", "key": "created_at", "value": 198},
            "page": 2,
            "limit": 3,
        },
    )
    assert response.json()["meta"]["total_count"] == 7
    assert [s["session_id"] for s in response.json()["data"]] == ["201", "200", "199"]


def test_remote_search_preserves_scope_table_and_auth():
    from agno.os.schema import PaginatedResponse, PaginationInfo
    from agno.remote.base import RemoteDb

    remote = MagicMock(spec=RemoteDb)
    remote.session_table_name = "custom"
    remote.search_sessions = AsyncMock(
        return_value=PaginatedResponse(data=[], meta=PaginationInfo(page=1, limit=20, total_count=0, total_pages=0))
    )
    response = build_client(remote, isolated=True).post(
        "/sessions/search?db_id=test&table=custom",
        json={"filter": eq("user_id", "bob")},
        headers={"Authorization": "Bearer example"},
    )
    assert response.status_code == 200, response.text
    kwargs = remote.search_sessions.call_args.kwargs
    assert kwargs["user_id"] == "alice"
    assert kwargs["table"] == "custom"
    assert kwargs["headers"] == {"Authorization": "Bearer example"}


def test_postgres_uses_json_name_and_epoch_dates():
    from sqlalchemy import BigInteger, Column, MetaData, Table, select
    from sqlalchemy.dialects import postgresql

    from agno.db.session_filters import SESSION_FILTER_FIELDS, session_filter_to_sqlalchemy

    table = Table(
        "sessions",
        MetaData(),
        Column("session_data", postgresql.JSONB),
        *[
            Column(key, BigInteger if key.endswith("_at") else postgresql.TEXT)
            for key in SESSION_FILTER_FIELDS
            if key != "session_name"
        ],
    )
    clause = session_filter_to_sqlalchemy(
        {
            "op": "AND",
            "conditions": [
                eq("session_name", "Billing"),
                {"op": "GTE", "key": "created_at", "value": "1970-01-01T00:05:00Z"},
            ],
        },
        table,
    )
    sql = select(table).where(clause).compile(dialect=postgresql.dialect())
    assert "->>" in str(sql)
    assert 300 in sql.params.values()


def test_search_requires_read_scope():
    from agno.os.scopes import get_default_scope_mappings, get_required_scopes_for_route

    mappings = get_default_scope_mappings()
    assert get_required_scopes_for_route(mappings, "POST", "/sessions/search") == ["sessions:read"]


def test_search_preserves_inferred_display_names(db):
    from agno.models.message import Message
    from agno.run.agent import RunOutput
    from agno.run.base import RunStatus

    session = AgentSession(
        session_id="unnamed",
        agent_id="support",
        user_id="alice",
        created_at=500,
        runs=[
            RunOutput(
                run_id="run-1", status=RunStatus.completed, messages=[Message(role="user", content="Help with billing")]
            )
        ],
    )
    if isinstance(db, AsyncBaseDb):
        asyncio.run(db.upsert_session(session))
        asyncio.run(db.upsert_run(session.runs[0], session_id="unnamed"))
    else:
        db.upsert_session(session)
        db.upsert_run(session.runs[0], session_id="unnamed")
    client = build_client(db)
    normal = client.get("/sessions").json()["data"]
    expected = next(s["session_name"] for s in normal if s["session_id"] == "unnamed")
    filtered = client.post("/sessions/search", json={"filter": eq("session_id", "unnamed")})
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["data"][0]["session_name"] == expected == "Help with billing"


@pytest.mark.parametrize("use_async", [False, True])
def test_python_client_search_preserves_remote_scope(use_async):
    from agno.client import AgentOSClient

    client = AgentOSClient(base_url="http://localhost:9999")
    result = {"data": [], "meta": {"page": 2, "limit": 10, "total_count": 0, "total_pages": 0}}
    client._request = MagicMock(return_value=result)
    client._apost = AsyncMock(return_value=result)
    kwargs = dict(filter_expr=eq("user_id", "bob"), user_id="alice", db_id="db-1", table="custom", page=2, limit=10)
    response = asyncio.run(client.asearch_sessions(**kwargs)) if use_async else client.search_sessions(**kwargs)
    call = client._apost.call_args if use_async else client._request.call_args
    assert call.kwargs["data"]["filter"] == {"op": "AND", "conditions": [eq("user_id", "alice"), eq("user_id", "bob")]}
    assert call.kwargs["params"] == {"db_id": "db-1", "table": "custom"}
    assert response.meta.page == 2
