# Agno Performance Benchmarks

The canonical performance benchmark suite for Agno. Every number here measures
**framework overhead only**: the suite uses in-process mock models, so no
benchmark depends on a provider, an API key or the network. Results are
reproducible on any machine.

For examples of the `PerformanceEval` API itself (including benchmarks that
call real models), see `cookbook/09_evals/performance/`.

Cross-framework comparisons (Agno vs LangGraph, PydanticAI, CrewAI: cold
import, agent construction time and memory) live in `comparison/` — see its
README for the dedicated environment setup. Results feed the same report.

## What is measured

| Benchmark | File | What it measures |
|-----------|------|------------------|
| `import_agno`, `import_agno_agent` | `import_time.py` | Cold import in a fresh process, interpreter startup subtracted. Paid once per process: dominates CLI and serverless cold starts. |
| `instantiate_agent` | `instantiate_agent.py` | Creating a bare `Agent`. |
| `instantiate_agent_with_tools` | `instantiate_agent_with_tools.py` | Creating an `Agent` with five function tools. |
| `instantiate_team` | `instantiate_team.py` | Creating a `Team` with three member agents. |
| `instantiate_workflow` | `instantiate_workflow.py` | Creating a two-step `Workflow`. |
| `run_agent`, `arun_agent` | `run_agent.py` | One full `run()` / `arun()` with a mock model: the framework's per-run overhead. |
| `run_agent_streaming`, `arun_agent_streaming` | `run_agent_streaming.py` | One streaming run, event stream fully drained. |
| `run_agent_with_tools`, `arun_agent_with_tools` | `run_agent_with_tools.py` | A two-turn tool loop: tool call request, real tool execution, final answer. |
| `run_agent_with_storage`, `arun_agent_with_storage` | `run_agent_with_storage.py` | One run with an in-memory db and history enabled: session persistence overhead. |
| `memory_per_agent`, `memory_per_agent_with_tools` | `memory_footprint.py` | Net resident memory per live agent, measured over batches of 1000. |

## Running

```bash
# Full suite (a few minutes), results written to results/
.venvs/demo/bin/python cookbook/performance/run_all.py

# Quick smoke run
.venvs/demo/bin/python cookbook/performance/run_all.py --quick

# Single benchmark, human-readable output
.venvs/demo/bin/python cookbook/performance/run_agent.py
```

Unlike most cookbook folders, this suite needs only core agno: any
environment with `agno` installed works, including the dev `.venv`.

`run_all.py` runs each benchmark in a fresh Python process, one at a time.
Do not run benchmarks concurrently and close CPU-heavy applications first:
contention skews timings.

## Reports and baselines

```bash
# Render results/summary.json into a self-contained HTML report
.venvs/demo/bin/python cookbook/performance/report.py
```

The report is written to `report/agno-performance.html`. Local run output
(`results/`, `report/`) is gitignored; published reference runs are checked
in under `baselines/` as `<date>-<machine>.json` and can be rendered with
`report.py --results baselines/<file>`.

## Methodology notes

- **Mock models, real loop.** The mock models subclass `agno.models.base.Model`
  and drive the complete run loop: message building, tool dispatch, event
  streaming, run output construction and session bookkeeping. The provider
  adapter is replaced entirely, so provider-specific work that real
  integrations do inside agno (wire-format message conversion, provider
  response parsing) is excluded. Numbers are a floor on per-run overhead.
- **Streaming benchmarks stream a single chunk**, so they measure the fixed
  cost of the streaming machinery, not per-chunk cost over a long delta
  stream.
- **Runtime and memory are measured in separate passes** (a `PerformanceEval`
  behavior): tracemalloc slows execution, so timing runs are never traced.
- **Warmup runs are excluded** from statistics (10 per benchmark by default).
- **Each benchmark file runs in a fresh Python process.** The sync and async
  variants inside one file share that process; their benchmark functions are
  written so no state carries between iterations or variants.
- **Import time is measured in fresh subprocesses** because a module import
  only happens once per process; the median interpreter startup time is
  subtracted from every sample. Process-spawn variance stays in the samples,
  so read the median and treat sub-millisecond differences as noise.
- **Memory footprint keeps agents alive** and reports the net allocation delta
  per agent, which is what capacity planning needs. The instantiation
  benchmarks report the transient allocation peak of creating one agent,
  which is larger.
- Prefer **median and p95** over the mean; distributions have a long tail
  from GC pauses. The timing harness itself costs a couple hundred
  nanoseconds per call, a few percent of the microsecond-scale
  instantiation numbers.

## Environment variables

| Variable | Effect |
|----------|--------|
| `AGNO_BENCH_RESULTS_DIR` | Write one JSON result file per benchmark into this directory. |
| `AGNO_BENCH_ITERATIONS` | Override every benchmark's iteration count (smoke runs). |
| `AGNO_BENCH_QUIET` | Suppress tables and spinners; print one summary line per benchmark. |
