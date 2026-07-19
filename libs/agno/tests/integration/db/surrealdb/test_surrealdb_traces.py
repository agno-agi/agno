# Run SurrealDB in a container before running this script
#
# ```
# docker run --rm --pull always -p 8000:8000 surrealdb/surrealdb:latest start --user root --pass root
# ```
#
# or with
#
# ```
# surreal start -u root -p root
# ```
#
# Then, run this test like this:
#
# ```
# pytest libs/agno/tests/integration/db/surrealdb/test_surrealdb_traces.py
# ```

import time
from datetime import datetime, timezone

import pytest
from surrealdb import RecordID

from agno.db.surrealdb import SurrealDb
from agno.debug import enable_debug_mode
from agno.tracing.schemas import Span, Trace

enable_debug_mode()

# SurrealDB connection parameters
SURREALDB_URL = "ws://localhost:8000"
SURREALDB_USER = "root"
SURREALDB_PASSWORD = "root"
SURREALDB_NAMESPACE = "test"
SURREALDB_DATABASE = "test"


@pytest.fixture
def db() -> SurrealDb:
    """Create a SurrealDB memory database for testing."""
    creds = {"username": SURREALDB_USER, "password": SURREALDB_PASSWORD}
    db = SurrealDb(None, SURREALDB_URL, creds, SURREALDB_NAMESPACE, SURREALDB_DATABASE)
    return db


def test_crud_traces(db: SurrealDb):
    now = datetime.now(timezone.utc)
    trace = Trace(
        trace_id="1",
        name="test_trace",
        status="OK",
        start_time=now,
        end_time=now,
        duration_ms=0,
        total_spans=1,
        error_count=0,
        run_id="1",
        session_id="1",
        user_id=None,
        agent_id=None,
        team_id=None,
        workflow_id=None,
        created_at=now,
    )

    # upsert
    db.upsert_trace(trace)

    # get
    fetched = db.get_trace("1")
    assert fetched is not None
    assert fetched.trace_id == "1"


def test_trace_created_at_preserved_on_update(db: SurrealDb):
    """Test that trace created_at is preserved when updating."""
    now = datetime.now(timezone.utc)
    trace = Trace(
        trace_id="2",
        name="test_trace",
        status="OK",
        start_time=now,
        end_time=now,
        duration_ms=0,
        total_spans=1,
        error_count=0,
        run_id="1",
        session_id="1",
        user_id=None,
        agent_id=None,
        team_id=None,
        workflow_id=None,
        created_at=now,
    )
    db.upsert_trace(trace)

    table = db._get_table("traces")
    record_id = RecordID(table, "2")
    raw_result = db._query_one("SELECT * FROM ONLY $record_id", {"record_id": record_id}, dict)
    assert raw_result is not None
    original_created_at = raw_result.get("created_at")

    time.sleep(1.1)

    trace.status = "ERROR"
    trace.end_time = datetime.now(timezone.utc)
    db.upsert_trace(trace)

    raw_result = db._query_one("SELECT * FROM ONLY $record_id", {"record_id": record_id}, dict)
    assert raw_result is not None
    new_created_at = raw_result.get("created_at")

    # created_at should not change on update
    assert original_created_at == new_created_at


def test_crud_spans(db: SurrealDb):
    now = datetime.now(timezone.utc)

    # create parent trace first
    trace = Trace(
        trace_id="3",
        name="test_trace",
        status="OK",
        start_time=now,
        end_time=now,
        duration_ms=0,
        total_spans=1,
        error_count=0,
        run_id="1",
        session_id="1",
        user_id=None,
        agent_id=None,
        team_id=None,
        workflow_id=None,
        created_at=now,
    )
    db.upsert_trace(trace)

    span = Span(
        span_id="1",
        trace_id="3",
        parent_span_id=None,
        name="test_span",
        span_kind="INTERNAL",
        status_code="OK",
        status_message=None,
        start_time=now,
        end_time=now,
        duration_ms=0,
        attributes={},
        created_at=now,
    )

    # create
    db.create_span(span)

    # get
    fetched = db.get_span("1")
    assert fetched is not None
    assert fetched.span_id == "1"


def test_span_created_at_preserved_on_update(db: SurrealDb):
    """Test that span created_at is preserved when updating."""
    now = datetime.now(timezone.utc)

    trace = Trace(
        trace_id="4",
        name="test_trace",
        status="OK",
        start_time=now,
        end_time=now,
        duration_ms=0,
        total_spans=1,
        error_count=0,
        run_id="1",
        session_id="1",
        user_id=None,
        agent_id=None,
        team_id=None,
        workflow_id=None,
        created_at=now,
    )
    db.upsert_trace(trace)

    span = Span(
        span_id="2",
        trace_id="4",
        parent_span_id=None,
        name="test_span",
        span_kind="INTERNAL",
        status_code="OK",
        status_message=None,
        start_time=now,
        end_time=now,
        duration_ms=0,
        attributes={},
        created_at=now,
    )
    db.create_span(span)

    table = db._get_table("spans")
    record_id = RecordID(table, "2")
    raw_result = db._query_one("SELECT * FROM ONLY $record_id", {"record_id": record_id}, dict)
    assert raw_result is not None
    original_created_at = raw_result.get("created_at")

    time.sleep(1.1)

    span.status_code = "ERROR"
    span.end_time = datetime.now(timezone.utc)
    db.create_span(span)

    raw_result = db._query_one("SELECT * FROM ONLY $record_id", {"record_id": record_id}, dict)
    assert raw_result is not None
    new_created_at = raw_result.get("created_at")

    # created_at should not change on update
    assert original_created_at == new_created_at
