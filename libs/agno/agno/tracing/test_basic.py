"""
Basic tests for Agno tracing functionality.

Run with: python -m pytest libs/agno/agno/tracing/test_basic.py
"""

import tempfile
from pathlib import Path

import pytest


def test_trace_span_creation():
    """Test TraceSpan creation and serialization"""
    from agno.tracing.schemas import TraceSpan

    trace = TraceSpan(
        trace_id="1234567890abcdef",
        span_id="abcdef123456",
        parent_span_id=None,
        name="test.operation",
        span_kind="INTERNAL",
        status_code="OK",
        status_message=None,
        start_time_ns=1000000000,
        end_time_ns=1000001000,
        duration_ms=1,
        attributes={"test": "value"},
        events=[],
        run_id="run123",
        session_id="session123",
        user_id="user123",
        agent_id="agent123",
        created_at=1234567890,
    )

    # Test to_dict
    trace_dict = trace.to_dict()
    assert trace_dict["trace_id"] == "1234567890abcdef"
    assert trace_dict["name"] == "test.operation"

    # Test from_dict
    trace2 = TraceSpan.from_dict(trace_dict)
    assert trace2.trace_id == trace.trace_id
    assert trace2.name == trace.name


def test_database_span_exporter():
    """Test DatabaseSpanExporter initialization"""
    from agno.db.sqlite import SqliteDb
    from agno.tracing.exporter import DatabaseSpanExporter

    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test.db"
        db = SqliteDb(db_file=str(db_file))
        exporter = DatabaseSpanExporter(db=db)

        assert exporter.db == db
        assert not exporter._shutdown


@pytest.mark.skipif(
    not _has_opentelemetry(),
    reason="OpenTelemetry packages not installed",
)
def test_setup_tracing():
    """Test setup_tracing function"""
    from agno.db.sqlite import SqliteDb
    from agno.tracing import setup_tracing

    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test.db"
        db = SqliteDb(db_file=str(db_file))

        # Should not raise
        setup_tracing(db=db, use_batch_processor=False)


@pytest.mark.skipif(
    not _has_opentelemetry(),
    reason="OpenTelemetry packages not installed",
)
def test_trace_storage_sqlite():
    """Test storing and retrieving traces from SQLite"""
    from agno.db.sqlite import SqliteDb
    from agno.tracing.schemas import TraceSpan

    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test.db"
        db = SqliteDb(db_file=str(db_file))

        # Create test trace
        trace = TraceSpan(
            trace_id="test_trace_123",
            span_id="span_123",
            parent_span_id=None,
            name="test.operation",
            span_kind="INTERNAL",
            status_code="OK",
            status_message=None,
            start_time_ns=1000000000,
            end_time_ns=1000001000,
            duration_ms=1,
            attributes={"test": "value"},
            events=[],
            run_id="run_123",
            session_id="session_123",
            user_id="user_123",
            agent_id="agent_123",
            created_at=1234567890,
        )

        # Store trace
        db.create_trace(trace)

        # Retrieve trace
        retrieved = db.get_trace(span_id="span_123")
        assert retrieved is not None
        assert retrieved.span_id == "span_123"
        assert retrieved.name == "test.operation"

        # Query traces
        traces = db.get_traces(agent_id="agent_123")
        assert len(traces) == 1
        assert traces[0].span_id == "span_123"


@pytest.mark.skipif(
    not _has_opentelemetry(),
    reason="OpenTelemetry packages not installed",
)
def test_trace_batch_storage():
    """Test batch trace storage"""
    from agno.db.sqlite import SqliteDb
    from agno.tracing.schemas import TraceSpan

    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test.db"
        db = SqliteDb(db_file=str(db_file))

        # Create multiple traces
        traces = [
            TraceSpan(
                trace_id="test_trace_123",
                span_id=f"span_{i}",
                parent_span_id=None,
                name=f"test.operation.{i}",
                span_kind="INTERNAL",
                status_code="OK",
                status_message=None,
                start_time_ns=1000000000 + i,
                end_time_ns=1000001000 + i,
                duration_ms=1,
                attributes={"index": i},
                events=[],
                run_id="run_123",
                session_id="session_123",
                user_id="user_123",
                agent_id="agent_123",
                created_at=1234567890,
            )
            for i in range(5)
        ]

        # Store traces in batch
        db.create_traces_batch(traces)

        # Query traces
        retrieved_traces = db.get_traces(run_id="run_123", limit=10)
        assert len(retrieved_traces) == 5


def _has_opentelemetry():
    """Check if OpenTelemetry packages are installed"""
    try:
        import opentelemetry  # noqa: F401
        from openinference.instrumentation.agno import AgnoInstrumentor  # noqa: F401

        return True
    except ImportError:
        return False

