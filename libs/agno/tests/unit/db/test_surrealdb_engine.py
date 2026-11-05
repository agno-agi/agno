"""SurrealDb storage against a real in-process engine, so SDK behavior changes cannot hide behind mocks."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from agno.db.base import SessionType
from agno.db.schemas.memory import UserMemory
from agno.db.surrealdb import SurrealDb
from agno.run.agent import RunOutput
from agno.session import AgentSession
from agno.tracing.schemas import Span, Trace

surrealdb = pytest.importorskip("surrealdb")


@pytest.fixture
def db() -> SurrealDb:
    client = surrealdb.Surreal("mem://")
    database = uuid4().hex
    client.use("test", database)
    return SurrealDb(client, "mem://", {}, "test", database)


def _session(session_id: str = "s1") -> AgentSession:
    return AgentSession(session_id=session_id, agent_id="a1", user_id="u1", created_at=1700000000)


def test_session_round_trip_and_delete(db: SurrealDb):
    db.upsert_session(_session())

    stored = db.get_session("s1", SessionType.AGENT)
    assert stored is not None
    assert stored.session_id == "s1"

    assert db.delete_session("s1") is True
    assert db.get_session("s1", SessionType.AGENT) is None


def test_run_reads_treat_a_missing_runs_table_as_empty(db: SurrealDb):
    assert db.get_run("r1") is None
    assert db.get_runs() == []
    assert db.get_runs(deserialize=False) == ([], 0)


def test_run_reads_return_stored_runs(db: SurrealDb):
    db.upsert_run(RunOutput(run_id="r1", session_id="s1", agent_id="a1", content="hi"), session_id="s1", run_index=0)

    run = db.get_run("r1")

    assert run is not None
    assert run.run_id == "r1"
    assert [r.run_id for r in db.get_runs(session_id="s1")] == ["r1"]


def test_memory_round_trip_and_delete(db: SurrealDb):
    stored = db.upsert_user_memory(UserMemory(memory="likes tea", user_id="u1", memory_id="m1"))
    assert stored is not None

    fetched = db.get_user_memory("m1")
    assert fetched is not None
    assert fetched.memory == "likes tea"

    db.delete_user_memory("m1")
    assert db.get_user_memory("m1") is None


def test_clear_memories_removes_every_row(db: SurrealDb):
    db.upsert_user_memory(UserMemory(memory="likes tea", user_id="u1", memory_id="m1"))

    db.clear_memories()

    assert db.get_user_memories() == []


def test_schema_version_round_trip(db: SurrealDb):
    db.upsert_schema_version("agno_sessions", "3.1.0")

    assert db.get_latest_schema_version("agno_sessions") == "3.1.0"


def _trace(trace_id: str = "t1") -> Trace:
    now = datetime.now(timezone.utc)
    return Trace(
        trace_id=trace_id,
        name="trace",
        status="OK",
        start_time=now,
        end_time=now,
        duration_ms=0,
        total_spans=0,
        error_count=0,
        run_id="r1",
        session_id="s1",
        user_id=None,
        agent_id=None,
        team_id=None,
        workflow_id=None,
        created_at=now,
    )


def _span(span_id: str, status_code: str, trace_id: str = "t1") -> Span:
    now = datetime.now(timezone.utc)
    return Span(
        span_id=span_id,
        trace_id=trace_id,
        parent_span_id=None,
        name="span",
        span_kind="INTERNAL",
        status_code=status_code,
        status_message=None,
        start_time=now,
        end_time=now,
        duration_ms=0,
        attributes={},
        created_at=now,
    )


def test_get_trace_treats_a_missing_spans_table_as_zero_spans(db: SurrealDb):
    db.upsert_trace(_trace())

    trace = db.get_trace("t1")

    assert trace is not None
    assert (trace.total_spans, trace.error_count) == (0, 0)


def test_get_traces_treats_a_missing_spans_table_as_zero_spans(db: SurrealDb):
    db.upsert_trace(_trace())

    traces, total = db.get_traces()

    assert total == 1
    assert [(t.trace_id, t.total_spans, t.error_count) for t in traces] == [("t1", 0, 0)]


def test_trace_reads_count_stored_spans(db: SurrealDb):
    db.upsert_trace(_trace())
    db.create_span(_span("ok", "OK"))
    db.create_span(_span("bad", "ERROR"))

    trace = db.get_trace("t1")
    traces, _ = db.get_traces()

    assert trace is not None
    assert (trace.total_spans, trace.error_count) == (2, 1)
    assert [(t.total_spans, t.error_count) for t in traces] == [(2, 1)]
