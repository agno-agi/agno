# Agno Tracing

Agno Tracing provides OpenTelemetry-based observability for Agno agents, teams, and workflows. It uses the `openinference-instrumentation-agno` package for automatic instrumentation and provides a custom database exporter to store traces locally.

## Features

- **Automatic Instrumentation**: Zero-code-change tracing using OpenInference
- **Database Storage**: Traces stored in your Agno database (SQLite, PostgreSQL, etc.)
- **High-Level Operations**: Captures agent runs, model calls, and tool executions
- **OpenTelemetry Standard**: Compatible with external tools like Phoenix, Langfuse
- **Filtering & Querying**: Query traces by run_id, session_id, agent_id, etc.

## Installation

```bash
pip install opentelemetry-api opentelemetry-sdk openinference-instrumentation-agno
```

## Quick Start

```python
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tracing import setup_tracing

# Set up database
db = SqliteDb(db_file="tmp/traces.db")

# Enable tracing (call this once at startup)
setup_tracing(db=db)

# All agents are now automatically traced!
agent = Agent(
    name="My Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a helpful assistant",
)

agent.run("Hello!")

# Query traces
traces = db.get_traces(agent_id=agent.id, limit=10)
for trace in traces:
    print(f"{trace.name}: {trace.duration_ms}ms")
```

## What Gets Traced

The OpenInference instrumentor automatically captures:

- **Agent Runs**: Each `agent.run()` or `agent.arun()` call
- **Model Calls**: Each `model.response()` call including token usage
- **Tool Executions**: Each tool invocation with arguments and results
- **Teams**: Team coordination and member agent runs
- **Workflows**: Workflow steps and execution

## Trace Hierarchy

Traces are organized hierarchically:

```
agent.run (root span)
├── model.response (span)
├── tool_execution_1 (span)
├── model.response (span)
└── tool_execution_2 (span)
```

## Configuration

### Batch vs. Simple Processing

```python
# Batch processing (default, better performance)
setup_tracing(
    db=db,
    use_batch_processor=True,
    max_queue_size=2048,
    max_export_batch_size=512,
    schedule_delay_millis=5000,  # Export every 5 seconds
)

# Simple processing (immediate export, for debugging)
setup_tracing(db=db, use_batch_processor=False)
```

## Querying Traces

```python
# Get all traces for an agent
traces = db.get_traces(agent_id=agent.id)

# Get traces for a specific run
traces = db.get_traces(run_id=run.run_id)

# Get traces for a session
traces = db.get_traces(session_id=session.session_id)

# Filter by time range
traces = db.get_traces(
    start_time=start_ns,
    end_time=end_ns,
    limit=100,
)

# Get by trace_id to see full execution tree
traces = db.get_traces(trace_id=trace_id)
```

## Trace Data Structure

Each trace span contains:

```python
@dataclass
class TraceSpan:
    trace_id: str              # Groups related spans
    span_id: str               # Unique span identifier
    parent_span_id: Optional[str]  # Parent span (for hierarchy)
    name: str                  # Operation name (e.g., "agent.run")
    span_kind: str             # INTERNAL, SERVER, CLIENT, etc.
    status_code: str           # UNSET, OK, ERROR
    status_message: Optional[str]
    start_time_ns: int         # Start time (nanoseconds)
    end_time_ns: int           # End time (nanoseconds)
    duration_ms: int           # Duration in milliseconds
    attributes: Dict[str, Any] # OpenTelemetry attributes
    events: List[Dict[str, Any]]  # Span events
    run_id: Optional[str]      # Associated run ID
    session_id: Optional[str]  # Associated session ID
    user_id: Optional[str]     # Associated user ID
    agent_id: Optional[str]    # Associated agent ID
    created_at: int            # Creation timestamp
```

## Database Support

Trace methods are currently implemented for:

- ✅ SQLite (`SqliteDb`)
- 🚧 PostgreSQL (`PostgresDb`) - TODO
- 🚧 MySQL (`MySQLDb`) - TODO
- 🚧 Async PostgreSQL (`AsyncPostgresDb`) - TODO

## External Tool Integration

Since Agno tracing uses OpenTelemetry, you can also export to external tools:

```python
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from openinference.instrumentation.agno import AgnoInstrumentor

# Export to Phoenix, Langfuse, etc.
tracer_provider = TracerProvider()
tracer_provider.add_span_processor(
    SimpleSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:6006/v1/traces"))
)

AgnoInstrumentor().instrument(tracer_provider=tracer_provider)
```

## Performance Considerations

- **Minimal Overhead**: Batch processing reduces performance impact
- **Non-Blocking**: Trace writes never block agent execution
- **Error Handling**: Tracing failures don't crash your application
- **Configurable**: Adjust batch sizes and delays based on your needs

## Examples

See `cookbook/integrations/observability/trace_to_database.py` for a complete example.

## Architecture

```
Agent.run()
    ↓
OpenInference Instrumentation (automatic)
    ↓
OpenTelemetry TracerProvider
    ↓
DatabaseSpanExporter (custom)
    ↓
Agno Database (agno_traces table)
```

## Troubleshooting

### No traces captured

1. Ensure `openinference-instrumentation-agno` is installed
2. Call `setup_tracing()` before creating agents
3. Check database table creation with `db._get_table(table_type="traces")`

### Traces not appearing immediately

- Batch processing has a 5-second delay by default
- Use `use_batch_processor=False` for immediate export during debugging

### ImportError

```bash
pip install opentelemetry-api opentelemetry-sdk openinference-instrumentation-agno
```

## Future Enhancements

- Implement trace methods for all database types
- Add trace visualization tools
- Support custom span attributes
- Trace sampling and filtering
- Performance metrics dashboard

