from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, Status, StatusCode

from agno.db.sqlite import SqliteDb
from agno.os.routers.traces.schemas import TraceDetail
from agno.tracing.exporter import DatabaseSpanExporter
from agno.tracing.processor import AGNO_INSTRUMENTATION_SCOPE, AgnoSpanFilterProcessor
from agno.tracing.schemas import AGNO_RUN_ROOT_ATTRIBUTE

RUN_ATTRIBUTES = {
    "openinference.span.kind": "AGENT",
    "agno.agent.id": "weather-agent",
    "agno.run.id": "run-1",
    "session.id": "session-1",
    "input.value": "weather in Paris?",
}


def _request(provider, route, run=None):
    """Emit spans shaped like FastAPI's request tracing, optionally running an Agno run inside the endpoint."""
    http_tracer = provider.get_tracer("fastapi")
    agno_tracer = provider.get_tracer(AGNO_INSTRUMENTATION_SCOPE)
    with http_tracer.start_as_current_span(
        route,
        kind=SpanKind.SERVER,
        attributes={"http.request.method": route.split()[0], "http.route": route.split()[1]},
    ):
        with http_tracer.start_as_current_span("fastapi.dependencies"):
            pass
        with http_tracer.start_as_current_span("fastapi.endpoint"):
            if run is not None:
                with agno_tracer.start_as_current_span(run["name"], attributes=RUN_ATTRIBUTES) as run_span:
                    with agno_tracer.start_as_current_span(
                        "OpenAIResponses.ainvoke", attributes={"openinference.span.kind": "LLM"}
                    ):
                        pass
                    if run.get("error"):
                        run_span.set_status(Status(StatusCode.ERROR, "model failed"))
        with http_tracer.start_as_current_span("fastapi.serialization"):
            pass


def test_keep_mode_forwards_request_spans_with_run_nested_and_marked():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(AgnoSpanFilterProcessor(SimpleSpanProcessor(exporter), keep_outside_spans=True))
    try:
        _request(provider, "POST /agents/{agent_id}/runs", run={"name": "Weather_Agent.arun"})
    finally:
        provider.shutdown()

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert set(spans) == {
        "POST /agents/{agent_id}/runs",
        "fastapi.dependencies",
        "fastapi.endpoint",
        "fastapi.serialization",
        "Weather_Agent.arun",
        "OpenAIResponses.ainvoke",
    }
    run_span = spans["Weather_Agent.arun"]
    assert run_span.attributes[AGNO_RUN_ROOT_ATTRIBUTE] is True
    assert run_span.parent.span_id == spans["fastapi.endpoint"].context.span_id
    assert AGNO_RUN_ROOT_ATTRIBUTE not in spans["OpenAIResponses.ainvoke"].attributes


def test_keep_mode_forwards_request_root_before_its_earlier_children():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(AgnoSpanFilterProcessor(SimpleSpanProcessor(exporter), keep_outside_spans=True))
    try:
        _request(provider, "GET /sessions")
    finally:
        provider.shutdown()

    assert [span.name for span in exporter.get_finished_spans()] == [
        "GET /sessions",
        "fastapi.dependencies",
        "fastapi.endpoint",
        "fastapi.serialization",
    ]


def _store(tmp_path, *requests):
    db = SqliteDb(db_file=str(tmp_path / "traces.db"))
    provider = TracerProvider()
    provider.add_span_processor(
        AgnoSpanFilterProcessor(SimpleSpanProcessor(DatabaseSpanExporter(db=db)), keep_outside_spans=True)
    )
    try:
        for route, run in requests:
            _request(provider, route, run=run)
    finally:
        provider.shutdown()
    return db


def test_stored_traces_take_identity_from_the_run_and_name_from_the_request(tmp_path):
    db = _store(
        tmp_path,
        ("POST /agents/{agent_id}/runs", {"name": "Weather_Agent.arun"}),
        ("GET /sessions", None),
    )

    (run_trace,), _ = db.get_traces(kind="run")
    assert run_trace.name == "Weather_Agent.arun"
    assert (run_trace.agent_id, run_trace.run_id, run_trace.session_id) == ("weather-agent", "run-1", "session-1")

    (request_trace,), _ = db.get_traces(kind="request")
    assert request_trace.name == "GET /sessions"
    assert request_trace.agent_id is None

    endpoint_stats, _ = db.get_trace_stats(group_by="endpoint")
    assert [stat["name"] for stat in endpoint_stats] == ["GET /sessions"]


def test_run_status_is_not_overwritten_by_a_later_request_span(tmp_path):
    db = _store(tmp_path, ("POST /agents/{agent_id}/runs", {"name": "Weather_Agent.arun", "error": True}))

    (trace,), _ = db.get_traces()
    assert trace.status == "ERROR"


def test_trace_detail_nests_the_run_inside_the_request(tmp_path):
    db = _store(tmp_path, ("POST /agents/{agent_id}/runs", {"name": "Weather_Agent.arun"}))
    (trace,), _ = db.get_traces()

    detail = TraceDetail.from_trace_and_spans(trace, db.get_spans(trace_id=trace.trace_id))

    (root,) = detail.tree
    assert (root.type, root.name) == ("HTTP", "POST /agents/{agent_id}/runs")
    assert root.metadata == {"method": "POST", "route": "/agents/{agent_id}/runs"}
    endpoint = next(node for node in root.spans if node.name == "fastapi.endpoint")
    assert endpoint.type == "HTTP_INTERNAL"
    (run_node,) = endpoint.spans
    assert run_node.id == detail.run_span_id
    assert run_node.type == "AGENT"
    assert detail.input == "weather in Paris?"


def test_trace_detail_of_a_request_without_a_run_has_no_run_span(tmp_path):
    db = _store(tmp_path, ("GET /sessions", None))
    (trace,), _ = db.get_traces()

    detail = TraceDetail.from_trace_and_spans(trace, db.get_spans(trace_id=trace.trace_id))

    assert detail.run_span_id is None
    (root,) = detail.tree
    assert root.type == "HTTP"
    assert root.metadata == {"method": "GET", "route": "/sessions"}


def test_trace_list_filters_by_several_names_and_returns_request_details(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from agno.os.routers.traces.traces import get_traces_router

    db = _store(tmp_path, ("GET /sessions", None), ("GET /agents", None), ("GET /teams", None))
    app = FastAPI()
    app.include_router(get_traces_router(dbs={db.id: [db]}))

    response = TestClient(app).get(
        "/traces", params=[("kind", "request"), ("name", "GET /sessions"), ("name", "GET /teams")]
    )

    assert response.status_code == 200
    rows = response.json()["data"]
    assert sorted(row["name"] for row in rows) == ["GET /sessions", "GET /teams"]
    assert {row["request"]["method"] for row in rows} == {"GET"}
    assert {row["request"]["route"] for row in rows} == {"/sessions", "/teams"}
