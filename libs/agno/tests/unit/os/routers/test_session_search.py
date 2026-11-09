"""Session search contracts across SQL, asynchronous SQL, and portable adapters."""

import asyncio
import functools
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
    assert response.json()["logical_operators"] == ["AND", "OR", "NOT"]
    labels = {field["key"]: field["label"] for field in response.json()["fields"]}
    assert labels["session_name"] == "Saved Session Name"


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
        ({"op": "NOT", "condition": eq("agent_id", "support")}, ["agent-2"]),
        ({"op": "NOT", "condition": eq("session_name", "Report")}, ["team-1", "agent-1"]),
        ({"op": "NOT", "condition": {"op": "NOT", "condition": eq("agent_id", "support")}}, ["agent-1"]),
        (
            {"op": "NOT", "condition": {"op": "OR", "conditions": [eq("agent_id", "support"), eq("user_id", "bob")]}},
            ["agent-2"],
        ),
        (
            {"op": "NOT", "condition": {"op": "AND", "conditions": [eq("agent_id", "support"), eq("user_id", "bob")]}},
            ["agent-2", "team-1", "agent-1"],
        ),
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
        {"op": "NOT"},
        {"op": "NOT", "condition": None},
        {"op": "NOT", "condition": []},
        {"op": "NOT", "condition": eq("runs", "secret")},
        {"op": "GT", "key": "user_id", "value": "alice"},
        {"op": "GTE", "key": "created_at", "value": "yesterday"},
    ],
)
def test_invalid_filters_rejected_even_with_empty_database(expression):
    response = build_client(InMemoryDb()).post("/sessions/search", json={"filter": expression})
    assert response.status_code == 400


@pytest.mark.parametrize("op", ["AND", "NOT"])
def test_deep_filter_rejected(op):
    expression = eq("user_id", "alice")
    for _ in range(12):
        expression = (
            {"op": "AND", "conditions": [expression]} if op == "AND" else {"op": "NOT", "condition": expression}
        )
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

    from agno.db.session_filters import SESSION_FILTER_FIELDS, normalize_session_filter, session_filter_to_sqlalchemy

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
    expression = normalize_session_filter(
        {
            "op": "AND",
            "conditions": [
                eq("session_name", "Billing"),
                {"op": "GTE", "key": "created_at", "value": "1970-01-01T00:05:00Z"},
            ],
        }
    )
    clause = session_filter_to_sqlalchemy(expression, table)
    sql = select(table).where(clause).compile(dialect=postgresql.dialect())
    assert "->>" in str(sql)
    assert 300 in sql.params.values()


def test_mysql_compares_strings_case_sensitively():
    from sqlalchemy import JSON, BigInteger, Column, MetaData, String, Table, select
    from sqlalchemy.dialects import mysql

    from agno.db.session_filters import SESSION_FILTER_FIELDS, session_filter_to_sqlalchemy

    table = Table(
        "sessions",
        MetaData(),
        Column("session_data", JSON),
        *[
            Column(key, BigInteger if key.endswith("_at") else String(128))
            for key in SESSION_FILTER_FIELDS
            if key != "session_name"
        ],
    )
    expression = {
        "op": "AND",
        "conditions": [eq("user_id", "Alice"), {"op": "GT", "key": "created_at", "value": 5}],
    }
    sql = str(
        select(table)
        .where(session_filter_to_sqlalchemy(expression, table, collation="utf8mb4_bin"))
        .compile(dialect=mysql.dialect())
    )
    assert "user_id COLLATE utf8mb4_bin" in sql
    assert "created_at COLLATE" not in sql


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


@pytest.mark.parametrize("db_class", [SqliteDb, AsyncSqliteDb])
def test_search_does_not_reread_unnamed_sessions(tmp_path, db_class):
    db = db_class(db_file=str(tmp_path / "test.db"))
    for i in range(5):
        session = AgentSession(session_id=f"unnamed-{i}", agent_id="support", user_id="alice", created_at=i)
        if isinstance(db, AsyncBaseDb):
            asyncio.run(db.upsert_session(session))
        else:
            db.upsert_session(session)
    reads = []
    original = db.get_session
    if isinstance(db, AsyncBaseDb):

        async def counting_get_session(*args, **kwargs):
            reads.append(kwargs.get("session_id"))
            return await original(*args, **kwargs)
    else:

        def counting_get_session(*args, **kwargs):
            reads.append(kwargs.get("session_id"))
            return original(*args, **kwargs)

    db.get_session = counting_get_session
    response = build_client(db).post("/sessions/search", json={"filter": eq("agent_id", "support")})
    assert response.status_code == 200, response.text
    assert len(response.json()["data"]) == 5
    assert reads == []


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


MONGO_EXPRESSIONS = [
    eq("user_id", "alice"),
    {"op": "NEQ", "key": "session_name", "value": "Report"},
    {"op": "IN", "key": "session_type", "values": ["team", "workflow"]},
    {"op": "CONTAINS", "key": "session_name", "value": "100%"},
    {"op": "STARTSWITH", "key": "session_name", "value": "bill"},
    {"op": "GTE", "key": "created_at", "value": 200},
    {"op": "NOT", "condition": {"op": "CONTAINS", "key": "session_name", "value": "billing"}},
    {"op": "NOT", "condition": {"op": "IN", "key": "agent_id", "values": ["support"]}},
    {"op": "NOT", "condition": {"op": "LT", "key": "created_at", "value": 300}},
    {
        "op": "NOT",
        "condition": {"op": "OR", "conditions": [eq("user_id", "bob"), eq("session_name", "Billing review")]},
    },
    {
        "op": "AND",
        "conditions": [
            eq("user_id", "alice"),
            {"op": "OR", "conditions": [eq("session_type", "team"), {"op": "LTE", "key": "created_at", "value": 100}]},
        ],
    },
]


@pytest.mark.parametrize("expression", MONGO_EXPRESSIONS)
def test_mongo_translation_matches_portable_filter(expression):
    mongomock = pytest.importorskip("mongomock")
    from agno.db.session_filters import matches_session_filter, normalize_session_filter, session_filter_to_mongo

    documents = [
        {
            "session_id": "agent-1",
            "session_type": "agent",
            "agent_id": "support",
            "user_id": "alice",
            "created_at": 100,
            "session_data": {"session_name": "Billing 100%"},
        },
        {
            "session_id": "team-1",
            "session_type": "team",
            "team_id": "support-team",
            "user_id": "alice",
            "created_at": 200,
            "session_data": {"session_name": "Billing review"},
        },
        {
            "session_id": "workflow-1",
            "session_type": "workflow",
            "workflow_id": "support-flow",
            "user_id": "bob",
            "created_at": 300,
            "session_data": {"session_name": "Report"},
        },
        {
            "session_id": "agent-2",
            "session_type": "agent",
            "agent_id": "sales",
            "user_id": "alice",
            "created_at": 400,
            "session_data": None,
        },
    ]
    collection = mongomock.MongoClient().db.sessions
    collection.insert_many([dict(d) for d in documents])
    normalized = normalize_session_filter(expression)
    found = {d["session_id"] for d in collection.find(session_filter_to_mongo(normalized))}
    expected = {d["session_id"] for d in documents if matches_session_filter(d, normalized)}
    assert found == expected


def test_fallback_reads_sessions_once():
    db = InMemoryDb()
    for i in range(205):
        db.upsert_session(AgentSession(session_id=str(i), agent_id="a", user_id="alice", created_at=i))
    calls = []
    original = db.get_sessions

    @functools.wraps(original)
    def counting_get_sessions(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    db.get_sessions = counting_get_sessions
    sessions, total = db.search_sessions(filter_expr=eq("agent_id", "a"), limit=3, page=2)
    assert total == 205
    assert [s["session_id"] for s in sessions] == ["201", "200", "199"]
    assert len(calls) == 1
    assert calls[0].get("limit") is None and calls[0]["include_runs"] is False


def test_top_level_session_name_matches():
    from agno.db.session_filters import matches_session_filter

    renamed = {"session_id": "s", "session_name": "Renamed", "session_data": {}}
    assert matches_session_filter(renamed, {"op": "CONTAINS", "key": "session_name", "value": "renamed"})


def test_search_limit_is_capped():
    response = build_client(InMemoryDb()).post("/sessions/search", json={"limit": 101})
    assert response.status_code == 422


def test_unknown_db_returns_404():
    response = build_client(InMemoryDb()).post("/sessions/search?db_id=missing", json={})
    assert response.status_code == 404


@pytest.mark.parametrize("error, status", [(ValueError("bad sort"), 400), (RuntimeError("down"), 500)])
def test_search_maps_database_errors(error, status):
    db = InMemoryDb()
    db.search_sessions = MagicMock(side_effect=error)
    response = build_client(db).post("/sessions/search", json={})
    assert response.status_code == status
    assert str(error) in response.json()["detail"]


@pytest.mark.parametrize("remote_status", [404, 405])
def test_remote_without_search_returns_501(remote_status):
    import httpx

    from agno.remote.base import RemoteDb

    remote = MagicMock(spec=RemoteDb)
    remote.session_table_name = "sessions"
    request = httpx.Request("POST", "http://remote/sessions/search")
    remote.search_sessions = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "not found", request=request, response=httpx.Response(remote_status, request=request)
        )
    )
    response = build_client(remote).post("/sessions/search", json={})
    assert response.status_code == 501


def test_fallback_batches_runs_for_unnamed_sessions(tmp_path):
    from agno.models.message import Message
    from agno.run.agent import RunOutput
    from agno.run.base import RunStatus

    db = JsonDb(db_path=str(tmp_path))
    for i in range(3):
        run = RunOutput(
            run_id=f"run-{i}", status=RunStatus.completed, messages=[Message(role="user", content=f"Question {i}")]
        )
        db.upsert_session(
            AgentSession(session_id=f"s-{i}", agent_id="support", user_id="alice", created_at=i, runs=[run])
        )
        db.upsert_run(run, session_id=f"s-{i}")
    reads, batches = [], []
    original_get_session, original_batch = db.get_session, db._get_sessions_runs

    @functools.wraps(original_get_session)
    def counting_get_session(*args, **kwargs):
        reads.append(kwargs.get("session_id"))
        return original_get_session(*args, **kwargs)

    def counting_batch(session_ids):
        batches.append(list(session_ids))
        return original_batch(session_ids)

    db.get_session, db._get_sessions_runs = counting_get_session, counting_batch
    response = build_client(db).post("/sessions/search", json={"filter": eq("agent_id", "support")})
    assert response.status_code == 200, response.text
    assert [s["session_name"] for s in response.json()["data"]] == ["Question 2", "Question 1", "Question 0"]
    assert reads == []
    assert batches == [["s-2", "s-1", "s-0"]]


def _runs_for(session_id, count):
    from agno.run.agent import RunOutput
    from agno.run.base import RunStatus

    return [RunOutput(run_id=f"{session_id}-run-{n}", status=RunStatus.completed) for n in range(count)]


def test_redis_batches_run_reads_into_two_round_trips():
    fakeredis = pytest.importorskip("fakeredis")
    from agno.db.redis import RedisDb

    client = fakeredis.FakeRedis()
    db = RedisDb(redis_client=client)
    session_ids = [f"s-{i}" for i in range(5)]
    for sid in session_ids:
        db.upsert_session(AgentSession(session_id=sid, agent_id="a", user_id="alice", created_at=1))
        for run in _runs_for(sid, 2):
            db.upsert_run(run, session_id=sid)
    expected = {sid: db._get_session_runs_data(sid) for sid in session_ids}

    direct, executes = [], []
    for name in ("zrange", "get"):
        original = getattr(client, name)
        setattr(client, name, lambda *a, _n=name, _o=original, **k: direct.append(_n) or _o(*a, **k))
    original_pipeline = client.pipeline

    def counting_pipeline(*args, **kwargs):
        pipeline = original_pipeline(*args, **kwargs)
        original_execute = pipeline.execute
        pipeline.execute = lambda *a, **k: executes.append(1) or original_execute(*a, **k)
        return pipeline

    client.pipeline = counting_pipeline
    grouped = db._get_sessions_runs(session_ids)
    assert grouped == expected
    assert all(len(runs) == 2 for runs in grouped.values())
    assert direct == []
    assert len(executes) == 2


def test_valkey_batches_run_reads_into_two_round_trips(monkeypatch):
    pytest.importorskip("glide_sync")
    import json

    from glide_sync import GlideClient, RangeByIndex, RequestError

    import agno.db.valkey.valkey as valkey_module
    from agno.db.valkey import ValkeyDb

    # Other Valkey tests swap in stub GLIDE types at module level; use the real ones here.
    monkeypatch.setattr(valkey_module, "RangeByIndex", RangeByIndex)
    monkeypatch.setattr(valkey_module, "RequestError", RequestError)

    client = MagicMock(spec=GlideClient)
    db = ValkeyDb(valkey_client=client)
    rows = {
        f"s-{i}-run-{n}": {"run_id": f"s-{i}-run-{n}", "run_index": n, "run_data": {"run_id": f"s-{i}-run-{n}"}}
        for i in range(3)
        for n in range(2)
    }
    client.exec.side_effect = [
        [[f"s-{i}-run-1".encode(), f"s-{i}-run-0".encode()] for i in range(3)],
        [json.dumps(rows[rid]).encode() for i in range(3) for rid in (f"s-{i}-run-1", f"s-{i}-run-0")],
    ]
    grouped = db._get_sessions_runs([f"s-{i}" for i in range(3)])
    assert client.exec.call_count == 2
    client.zrange.assert_not_called()
    client.get.assert_not_called()
    assert grouped == {f"s-{i}": [{"run_id": f"s-{i}-run-0"}, {"run_id": f"s-{i}-run-1"}] for i in range(3)}


def test_dynamo_queries_sessions_concurrently():
    import threading
    import time

    from agno.db.dynamo import DynamoDb
    from agno.db.dynamo.utils import serialize_to_dynamo_item

    client = MagicMock()
    db = DynamoDb(db_client=client)
    db._get_table = MagicMock(return_value="runs")
    in_flight, peak, lock = [0], [0], threading.Lock()

    def query(**kwargs):
        sid = kwargs["ExpressionAttributeValues"][":sid"]["S"]
        with lock:
            in_flight[0] += 1
            peak[0] = max(peak[0], in_flight[0])
        time.sleep(0.05)
        with lock:
            in_flight[0] -= 1
        item = {"run_id": f"{sid}-run", "session_id": sid, "run_index": 0, "run_data": {"run_id": f"{sid}-run"}}
        return {"Items": [serialize_to_dynamo_item(item)]}

    client.query.side_effect = query
    session_ids = [f"s-{i}" for i in range(5)]
    grouped = db._get_sessions_runs(session_ids)
    assert grouped == {sid: [{"run_id": f"{sid}-run"}] for sid in session_ids}
    assert client.query.call_count == 5
    assert peak[0] > 1


def test_singlestore_filter_uses_supported_sql():
    from sqlalchemy import JSON, BigInteger, Column, MetaData, String, Table, func, select
    from sqlalchemy.dialects import mysql

    from agno.db.session_filters import SESSION_FILTER_FIELDS, session_filter_to_sqlalchemy

    table = Table(
        "sessions",
        MetaData(),
        Column("session_data", JSON),
        *[
            Column(key, BigInteger if key.endswith("_at") else String(128))
            for key in SESSION_FILTER_FIELDS
            if key != "session_name"
        ],
    )
    expression = {
        "op": "AND",
        "conditions": [
            eq("user_id", "alice"),
            {"op": "NOT", "condition": {"op": "CONTAINS", "key": "session_name", "value": "100%_\\"}},
            {"op": "STARTSWITH", "key": "agent_id", "value": "sup"},
        ],
    }
    name_column = func.JSON_EXTRACT_STRING(table.c.session_data, "session_name")
    compiled = (
        select(table)
        .where(session_filter_to_sqlalchemy(expression, table, session_name_column=name_column, backslash_like=True))
        .compile(dialect=mysql.dialect())
    )
    sql = str(compiled)
    assert "JSON_EXTRACT_STRING" in sql
    assert "JSON_UNQUOTE" not in sql and "ESCAPE" not in sql and "COLLATE" not in sql
    assert "%100\\%\\_\\\\%" in compiled.params.values()
    assert "sup%" in compiled.params.values()
