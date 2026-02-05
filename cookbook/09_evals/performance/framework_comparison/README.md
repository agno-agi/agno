# Framework Performance Comparison

This directory contains benchmarks comparing Agno performance against:
- Direct OpenAI API calls
- LangChain
- AgentOS API layer

## Key Findings

### 1. Telemetry Overhead
Agno's telemetry (enabled by default) adds ~200ms per call by sending HTTP requests to the telemetry API.

**Solution:** Disable telemetry for performance-critical applications:
```python
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    telemetry=False,  # Saves ~200ms per call
)
```

Or set environment variable: `AGNO_TELEMETRY=false`

### 2. Framework Overhead (with telemetry disabled)

| Framework | Latency | Overhead vs Direct OpenAI |
|-----------|---------|---------------------------|
| Direct OpenAI | ~415ms | baseline |
| LangChain | ~460ms | ~50ms |
| Agno Agent | ~415ms | **~0ms** |

### 3. API Layer Overhead

| Configuration | Overhead vs Direct Agent |
|--------------|--------------------------|
| Barebones FastAPI | ~60ms |
| AgentOS API | ~80ms |
| AgentOS vs FastAPI | **+20ms** |

AgentOS adds only ~20ms over barebones FastAPI for enterprise features (sessions, memory, RBAC, multi-agent support).

## Benchmark Scripts

### Direct Agent Comparison
```bash
# Compare Agno vs LangChain vs Direct OpenAI
python cookbook/09_evals/performance/framework_comparison/three_way_benchmark.py

# Test telemetry impact
python cookbook/09_evals/performance/framework_comparison/telemetry_test.py
```

### API Layer Comparison
```bash
# Start servers (in separate terminals)
python cookbook/09_evals/performance/framework_comparison/servers/agentos_server.py
python cookbook/09_evals/performance/framework_comparison/servers/fastapi_server.py

# Run API benchmark
python cookbook/09_evals/performance/framework_comparison/api_layer_benchmark.py
```

## Files

| File | Description |
|------|-------------|
| `three_way_benchmark.py` | Main benchmark: Agno vs LangChain vs Direct OpenAI |
| `telemetry_test.py` | Isolates telemetry impact (~200ms) |
| `api_layer_benchmark.py` | Compares API layer overhead |
| `servers/agentos_server.py` | Minimal AgentOS server for benchmarking |
| `servers/fastapi_server.py` | Barebones FastAPI server for comparison |
