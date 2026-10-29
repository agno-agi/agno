from unittest.mock import MagicMock

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agno.tracing.exporter import DatabaseSpanExporter
from agno.tracing.processor import AGNO_INSTRUMENTATION_SCOPE, AgnoSpanFilterProcessor


@pytest.fixture
def provider_and_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(AgnoSpanFilterProcessor(SimpleSpanProcessor(exporter)))
    yield provider, exporter
    provider.shutdown()


def _exported(exporter):
    return {span.name: span for span in exporter.get_finished_spans()}


def test_agno_span_inside_foreign_span_is_exported_as_root(provider_and_exporter):
    provider, exporter = provider_and_exporter
    agno_tracer = provider.get_tracer(AGNO_INSTRUMENTATION_SCOPE)
    http_tracer = provider.get_tracer("fastapi")

    with http_tracer.start_as_current_span("POST /agents/{agent_id}/runs"):
        with http_tracer.start_as_current_span("fastapi.endpoint"):
            with agno_tracer.start_as_current_span("Agent.arun") as run_span:
                with agno_tracer.start_as_current_span("OpenAIResponses.ainvoke"):
                    pass
                with http_tracer.start_as_current_span("user span in tool"):
                    pass

    spans = _exported(exporter)
    assert set(spans) == {"Agent.arun", "OpenAIResponses.ainvoke", "user span in tool"}
    assert spans["Agent.arun"].parent is None
    assert spans["Agent.arun"].context.span_id == run_span.get_span_context().span_id
    assert spans["OpenAIResponses.ainvoke"].parent.span_id == run_span.get_span_context().span_id
    assert spans["user span in tool"].parent.span_id == run_span.get_span_context().span_id


def test_nested_agno_runs_keep_their_parent(provider_and_exporter):
    provider, exporter = provider_and_exporter
    agno_tracer = provider.get_tracer(AGNO_INSTRUMENTATION_SCOPE)

    with agno_tracer.start_as_current_span("Team.arun") as team_span:
        with agno_tracer.start_as_current_span("Member.arun"):
            pass

    spans = _exported(exporter)
    assert spans["Team.arun"].parent is None
    assert spans["Member.arun"].parent.span_id == team_span.get_span_context().span_id


def test_runs_sharing_a_foreign_trace_get_traces_of_their_own(provider_and_exporter):
    provider, exporter = provider_and_exporter
    agno_tracer = provider.get_tracer(AGNO_INSTRUMENTATION_SCOPE)
    http_tracer = provider.get_tracer("fastapi")

    # e.g. two requests carrying the same traceparent header
    with http_tracer.start_as_current_span("POST /agents/{agent_id}/runs") as request_span:
        for name in ("Alice.arun", "Bob.arun"):
            with agno_tracer.start_as_current_span(name):
                with agno_tracer.start_as_current_span(f"{name}.model"):
                    pass

    spans = _exported(exporter)
    shared_trace_id = request_span.get_span_context().trace_id
    alice, bob = spans["Alice.arun"], spans["Bob.arun"]
    assert len({shared_trace_id, alice.context.trace_id, bob.context.trace_id}) == 3
    for run in (alice, bob):
        child = spans[f"{run.name}.model"]
        assert child.context.trace_id == run.context.trace_id
        assert (child.parent.trace_id, child.parent.span_id) == (run.context.trace_id, run.context.span_id)


def test_run_without_a_parent_keeps_its_trace_id(provider_and_exporter):
    provider, exporter = provider_and_exporter

    with provider.get_tracer(AGNO_INSTRUMENTATION_SCOPE).start_as_current_span("Agent.run") as run_span:
        pass

    (span,) = exporter.get_finished_spans()
    assert span.context.trace_id == run_span.get_span_context().trace_id


def test_runs_of_different_users_sharing_a_foreign_trace_are_stored_apart(tmp_path):
    from agno.db.sqlite import SqliteDb

    db = SqliteDb(db_file=str(tmp_path / "traces.db"))
    provider = TracerProvider()
    provider.add_span_processor(AgnoSpanFilterProcessor(SimpleSpanProcessor(DatabaseSpanExporter(db=db))))
    try:
        with provider.get_tracer("fastapi").start_as_current_span("POST /agents/{agent_id}/runs"):
            for user in ("alice", "bob"):
                with provider.get_tracer(AGNO_INSTRUMENTATION_SCOPE).start_as_current_span(
                    "Agent.arun",
                    attributes={"agno.agent.id": "agent", "agno.run.id": f"run-{user}", "user.id": user},
                ):
                    pass
    finally:
        provider.shutdown()

    for user in ("alice", "bob"):
        (trace,), _ = db.get_traces(run_id=f"run-{user}")
        assert trace.user_id == user


def test_spans_outside_agno_runs_are_dropped(provider_and_exporter):
    provider, exporter = provider_and_exporter
    http_tracer = provider.get_tracer("fastapi")

    with http_tracer.start_as_current_span("GET /sessions"):
        with http_tracer.start_as_current_span("fastapi.dependencies"):
            pass

    assert exporter.get_finished_spans() == ()


def test_database_exporter_reads_run_context_from_agno_root():
    db = MagicMock()
    provider = TracerProvider()
    provider.add_span_processor(AgnoSpanFilterProcessor(SimpleSpanProcessor(DatabaseSpanExporter(db=db))))
    try:
        attributes = {"agno.agent.id": "weather-agent", "agno.run.id": "run-1", "session.id": "session-1"}
        with provider.get_tracer("fastapi").start_as_current_span("POST /agents/{agent_id}/runs"):
            with provider.get_tracer(AGNO_INSTRUMENTATION_SCOPE).start_as_current_span(
                "Weather_Agent.arun", attributes=attributes
            ):
                pass
    finally:
        provider.shutdown()

    (trace,) = [call.args[0] for call in db.upsert_trace.call_args_list]
    assert trace.name == "Weather_Agent.arun"
    assert trace.agent_id == "weather-agent"
    assert trace.run_id == "run-1"
    assert trace.session_id == "session-1"
    stored = [span.name for call in db.create_spans.call_args_list for span in call.args[0]]
    assert stored == ["Weather_Agent.arun"]


def test_fastapi_native_spans_do_not_wrap_agno_runs(provider_and_exporter):
    pytest.importorskip("fastapi.telemetry")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    provider, exporter = provider_and_exporter
    app = FastAPI(telemetry={"tracer_provider": provider})

    @app.get("/run")
    def run():
        with provider.get_tracer(AGNO_INSTRUMENTATION_SCOPE).start_as_current_span("Agent.run"):
            pass
        return {}

    @app.get("/sessions")
    def sessions():
        return {}

    with TestClient(app) as client:
        assert client.get("/run").status_code == 200
        assert client.get("/sessions").status_code == 200

    spans = exporter.get_finished_spans()
    assert [span.name for span in spans] == ["Agent.run"]
    assert spans[0].parent is None
