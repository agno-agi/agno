# Observability

Agno provides comprehensive observability through built-in metrics, OpenTelemetry tracing, and integrations with all major observability platforms.

**Directory:** `libs/agno/agno/tracing/`
**Cookbook:** `cookbook/92_integrations/observability/` · `cookbook/05_agent_os/tracing/`

---

## Built-in metrics

Every agent run automatically tracks:

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(model=OpenAIChat(id="gpt-4o"), debug_mode=True)
response = agent.run("Explain quantum entanglement")

# Metrics are attached to every RunResponse
metrics = response.metrics

print(f"Input tokens:         {metrics.input_tokens}")
print(f"Output tokens:        {metrics.output_tokens}")
print(f"Cached tokens:        {metrics.cached_tokens}")
print(f"Reasoning tokens:     {metrics.reasoning_tokens}")
print(f"Total tokens:         {metrics.total_tokens}")
print(f"Total cost (USD):     ${metrics.total_cost:.6f}")
print(f"Prompt tokens:        {metrics.prompt_tokens}")
print(f"Time (seconds):       {metrics.response_timer.elapsed:.2f}s")
```

### Session-level aggregated metrics

```python
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=PostgresDb(table_name="sessions", db_url=DB_URL),
    session_id="my-session",
)

agent.print_response("Question 1")
agent.print_response("Question 2")

# Get aggregated metrics for the session
session_metrics = agent.get_session_metrics()
print(f"Session total tokens: {session_metrics.total_tokens}")
print(f"Session total cost:   ${session_metrics.total_cost:.4f}")
```

---

## OpenTelemetry tracing

Agno emits OTEL spans for every agent run, team execution, and workflow step.

**File:** `libs/agno/agno/tracing/setup.py`

### Setup

```python
from agno.tracing import setup_tracing

# Configure OTEL exporter (e.g., OTLP gRPC)
setup_tracing(
    endpoint="http://localhost:4317",   # OTLP receiver
    service_name="my-agno-app",
    trace_all_runs=True,
)
```

### Basic agent tracing

**Cookbook:** `cookbook/05_agent_os/tracing/01_basic_agent_tracing.py`

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    name="my-agent",
    monitoring=True,    # enable per-run trace emission
)
agent.print_response("What is 10 + 10?")
```

Each span captures:
- `agent.name` — agent identifier
- `model.name` — LLM used
- `run.id` — unique run ID
- `tokens.input` / `tokens.output` / `tokens.total`
- `cost.usd`
- `tool_calls` — list of tools called with args
- `duration_ms` — total run duration

### Team tracing

```python
from agno.team import Team

team = Team(
    name="research-team",
    members=[agent1, agent2],
    monitoring=True,   # traces team + all member runs
)
team.print_response("Research quantum computing breakthroughs")
```

Each team run creates a parent span with child spans for each member agent.

### Trace to database

**Cookbook:** `cookbook/05_agent_os/tracing/trace_to_database.py`

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb

# Store trace data in PostgreSQL for custom querying
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=PostgresDb(table_name="sessions", db_url=DB_URL),
    monitoring=True,
    store_runs_in_db=True,   # persist each run as a database record
)
```

---

## Platform integrations

### Langfuse

**Cookbook:** `cookbook/92_integrations/observability/langfuse_via_openinference.py`

```python
from openinference.instrumentation.agno import AgnoInstrumentor
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
import os

os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-..."
os.environ["LANGFUSE_SECRET_KEY"] = "sk-..."

provider = TracerProvider()
provider.add_span_processor(
    SimpleSpanProcessor(
        OTLPSpanExporter(
            endpoint="https://cloud.langfuse.com/api/public/otel/v1/traces",
            headers={
                "Authorization": "Basic " + base64_encode(f"{LANGFUSE_PUBLIC_KEY}:{LANGFUSE_SECRET_KEY}")
            },
        )
    )
)
trace.set_tracer_provider(provider)
AgnoInstrumentor().instrument()

# Now all agent runs are automatically traced to Langfuse
agent = Agent(model=OpenAIChat(id="gpt-4o"))
agent.print_response("Hello!")
```

### Arize Phoenix

**Cookbook:** `cookbook/92_integrations/observability/arize_phoenix_via_openinference.py`

```python
import phoenix as px
from openinference.instrumentation.agno import AgnoInstrumentor
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

# Local Phoenix server
px.launch_app()
endpoint = "http://localhost:6006/v1/traces"

provider = TracerProvider()
provider.add_span_processor(
    SimpleSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
)
trace.set_tracer_provider(provider)
AgnoInstrumentor().instrument()

agent = Agent(model=OpenAIChat(id="gpt-4o"))
agent.print_response("Explain machine learning in simple terms")

print(f"View traces: http://localhost:6006")
```

### AgentOps

**Cookbook:** `cookbook/92_integrations/observability/agent_ops.py`

```python
import agentops
agentops.init(api_key=os.environ["AGENTOPS_API_KEY"])

# All runs automatically tracked by AgentOps
agent = Agent(model=OpenAIChat(id="gpt-4o"))
agent.print_response("What is AI?")

agentops.end_session("Success")
```

### LangSmith

**Cookbook:** `cookbook/92_integrations/observability/langsmith_via_openinference.py`

```python
import os
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_API_KEY"] = "ls-..."
os.environ["LANGCHAIN_PROJECT"] = "my-agno-project"

from openinference.instrumentation.agno import AgnoInstrumentor
AgnoInstrumentor().instrument()

agent = Agent(model=OpenAIChat(id="gpt-4o"))
agent.print_response("Hello!")
```

### Other supported platforms

All of these are available in `cookbook/92_integrations/observability/`:

| Platform | File |
|----------|------|
| Logfire | `logfire_via_openinference.py` |
| Weave (W&B) | `weave_op.py` |
| Opik | `opik_via_openinference.py` |
| LangTrace | `langtrace_op.py` |
| LangWatch | `langwatch_op.py` |
| Maxim | `maxim_ops.py` |
| Atla | `atla_op.py` |
| Traceloop | `traceloop_op.py` |

---

## AgentOS monitoring dashboard

When deploying via `AgentOS`, the `/metrics` and `/traces` endpoints expose runtime data:

```bash
# Get platform metrics
GET /metrics

# Get recent traces
GET /traces?limit=50&agent_id=my-agent

# Health check
GET /health
```

Connect to `os.agno.com` for a visual dashboard showing:
- Run history per agent
- Token usage and cost over time
- Tool call frequency
- Error rates and latency percentiles
- Active sessions

---

## Debug mode

For development, enable verbose logging to stdout:

```python
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    debug_mode=True,        # verbose console logging
    show_tool_calls=True,   # print tool call details
)
```

`debug_mode=True` logs:
- Full message history sent to the model
- Tool call arguments and raw responses
- Token usage per call
- Timing for each operation

---

## Trace schema

**File:** `libs/agno/agno/tracing/schemas.py`

Each trace span contains:

```json
{
  "span_name": "agent.run",
  "trace_id": "...",
  "span_id": "...",
  "attributes": {
    "agno.agent.name": "my-agent",
    "agno.run.id": "run-abc123",
    "agno.model.name": "gpt-4o",
    "agno.tokens.input": 123,
    "agno.tokens.output": 456,
    "agno.tokens.total": 579,
    "agno.cost.usd": 0.00087,
    "agno.tool_calls": "[{\"name\": \"duckduckgo_search\", \"args\": {\"query\": \"...\"}}]",
    "agno.session.id": "session-xyz",
    "agno.user.id": "user-42"
  },
  "duration_ms": 1234,
  "status": "OK"
}
```

---

## Filtering traces

**Cookbook:** `cookbook/05_agent_os/tracing/08_advanced_trace_filtering.py`

```python
from agno.tracing import setup_tracing

setup_tracing(
    trace_filter={
        "min_duration_ms": 500,          # only trace slow runs
        "exclude_agents": ["test-agent"], # skip test agents
        "include_tool_calls": True,       # always include tool call spans
    }
)
```

---

## Multi-DB scenario tracing

**Cookbook:** `cookbook/05_agent_os/tracing/06_tracing_with_multi_db_scenario.py`

For multi-agent systems where different agents use different databases, each generates independent trace trees that are correlated by session ID.
