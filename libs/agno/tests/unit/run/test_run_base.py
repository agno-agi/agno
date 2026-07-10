# tests/run/test_run_base.py
import json

from agno.run.agent import RunContentEvent


# ✅ Test 1: When OTEL is activated, to_json() includes the trace_id
def test_to_json_includes_trace_id_when_otel_active():
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider()
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span("test-span"):
        event = RunContentEvent(content="hello")
        result = json.loads(event.to_json())

    assert "trace_id" in result
    assert len(result["trace_id"]) == 32  # 128-bit hex


# ✅ Test 2: When OTEL is unavailable, the system does not crash and the JSON remains valid
def test_to_json_no_crash_when_otel_missing(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "opentelemetry", None)

    event = RunContentEvent(content="hello")
    result = json.loads(event.to_json())

    assert "content" in result  # JSON remains valid even when OTEL is unavailable
    assert "trace_id" not in result  # trace_id is not included when OTEL is unavailable
