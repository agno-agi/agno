"""
Trace ID On Run Output
======================

Demonstrates how the OpenTelemetry trace_id of a run is surfaced on the
RunOutput and on every streamed event when tracing is enabled.

The trace_id is captured synchronously from the OTel context at run start, so
clients can correlate a run with its trace in real time - without querying
the database and without waiting for the run to finish. The same trace_id
identifies the trace in the Agno database, the AgentOS traces API, and any
external OTLP destination (Langfuse, Arize Phoenix, MLflow) configured via
setup_tracing(exporters=[...]).

A typical use case is user feedback: read trace_id off the RunStarted event
while the response is still streaming, then attach a thumbs up/down score to
that trace in your observability platform.

The agno.utils.otel.get_current_trace_id() helper used internally is also
public - any code running inside the run (tools, hooks) can call it to tag
its own logs or side effects with the active trace.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tracing import setup_tracing
from agno.utils.otel import get_current_trace_id

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Set up database
db = SqliteDb(db_file="tmp/traces.db")

# Set up tracing - this instruments ALL agents automatically.
# Pass exporters=[...] as well to also export to Langfuse/Phoenix/MLflow.
setup_tracing(db=db)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
def log_with_trace_context(message: str) -> str:
    """Tool demonstrating direct use of the helper: any code running inside
    the run (tools, hooks) can read the active trace_id from the OTel context."""
    trace_id = get_current_trace_id()
    print(f"  [inside tool] current trace_id: {trace_id}")
    return f"Logged: {message}"


agent = Agent(
    name="Traced Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[log_with_trace_context],
    db=db,
    instructions="You are a helpful assistant. Use the log_with_trace_context tool once, then answer.",
)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
def run_demo() -> None:
    # --- Streaming: the trace_id arrives on the FIRST event, before any content
    print("=" * 60)
    print("Streaming run - trace_id is available immediately:")
    print("=" * 60)
    for event in agent.run(
        "Log the message 'hello' and tell me a one-line joke.",
        stream=True,
        stream_events=True,
    ):
        if event.event in ("RunStarted", "RunCompleted"):
            print(f"  event={event.event}  trace_id={event.trace_id}")

    # --- Non-streaming: the trace_id is on the returned RunOutput
    print("\n" + "=" * 60)
    print("Non-streaming run - trace_id on the RunOutput:")
    print("=" * 60)
    response = agent.run("Say hi in three words.")
    print(f"  response.run_id:   {response.run_id}")
    print(f"  response.trace_id: {response.trace_id}")

    # The serialized output (what AgentOS APIs return) carries it too
    output_dict = response.to_dict()
    print("\n  Serialized RunOutput (subset):")
    for key in ("run_id", "trace_id", "agent_name", "status", "content"):
        print(f"    {key}: {output_dict.get(key)}")

    # --- Correlate: the same trace_id identifies the trace in the database
    trace = db.get_trace(run_id=response.run_id)
    if trace:
        print("\n  Trace stored in database:")
        print(f"    trace_id:    {trace.trace_id}")
        print(f"    total_spans: {trace.total_spans}")
        print(f"    matches RunOutput.trace_id: {trace.trace_id == response.trace_id}")
        # The same id can be used with external tools, e.g. the Langfuse
        # Scores API: langfuse.create_score(trace_id=response.trace_id, ...)
    else:
        print(
            "\n  No trace found. Make sure openinference-instrumentation-agno is installed."
        )


if __name__ == "__main__":
    run_demo()
