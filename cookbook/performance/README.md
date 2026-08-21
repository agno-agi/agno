# Agno Performance Benchmarks

Agno is the fastest way to run agents in production — and this folder proves
it on your machine, in about five minutes, with no API keys and no network.

Reference numbers (Apple M4 Max, medians, all frameworks in one environment):

| | **Agno** | LangGraph | PydanticAI | CrewAI |
|---|---|---|---|---|
| Single-turn agent run | **65 us** | 310 us (4.8x) | 2,258 us (35x) | 6,283 us (97x) |
| Agent construction (1 tool) | **4.7 us** | 1,440 us (306x) | 10,303 us (2,192x) | 20,792 us (4,424x) |
| Memory per run | **16.6 KiB** | 55 KiB | 105 KiB | 96 KiB |
| Cold import | **254 ms** | 383 ms | 515 ms | 986 ms |

Every number is framework overhead only: in-process mock models drive each
framework's complete run loop, so nothing depends on a provider or your
network connection, and results reproduce anywhere.

## Run it yourself

Two commands from the repo root:

```bash
./scripts/perf_setup.sh
```

```bash
.venvs/perfenv/bin/python cookbook/performance/run_all.py --all
```

That is the whole flow. The first command builds `.venvs/perfenv` (agno
installed editable from your checkout, plus LangGraph, PydanticAI and
CrewAI). The second runs the full agno suite and the cross-framework
comparison — each benchmark in its own fresh process — prints rich summary
tables in the terminal, and renders a self-contained HTML report:

```bash
open cookbook/performance/report/agno-performance.html
```

Close CPU-heavy applications first and let it run alone: contention skews
timings.

## Useful variations

```bash
# Agno suite only, no comparison (this is the regression-tracking set)
.venvs/perfenv/bin/python cookbook/performance/run_all.py

# 30-second smoke of everything (results isolated in results/quick/)
.venvs/perfenv/bin/python cookbook/performance/run_all.py --all --quick

# One benchmark, with rich per-run tables
.venvs/perfenv/bin/python cookbook/performance/run_agent.py

# Custom iteration count
AGNO_BENCH_ITERATIONS=1000 .venvs/perfenv/bin/python cookbook/performance/run_agent.py
```

The agno-only benchmarks need nothing beyond core agno, so any environment
with `agno[os]` installed runs them (including the dev `.venv`); the
comparison needs `.venvs/perfenv`. Reference runs are checked in under
`baselines/` as `<date>-<machine>.json` and any of them renders with
`report.py --results baselines/<file>`; local run output (`results/`,
`report/`) is gitignored.

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

Cross-framework benchmarks live in `comparison/` (cold import, one-tool
construction, mocked single-turn run) with fairness notes on exactly where
each framework's mock cuts. For examples of the `PerformanceEval` API itself
(including benchmarks that call real models), see
`cookbook/09_evals/performance/`.

## Methodology notes

- **Mock models, real loop.** The mock models subclass `agno.models.base.Model`
  and drive the complete run loop: message building, tool dispatch, event
  streaming, run output construction and session bookkeeping. The provider
  adapter is replaced entirely, so provider-specific work that real
  integrations do inside agno (wire-format message conversion, provider
  response parsing) is excluded. Numbers are a floor on per-run overhead —
  and the same is true for every compared framework.
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
  so read the median and treat sub-millisecond differences as noise. Absolute
  import times scale with how many packages the environment carries; compare
  ratios across environments, absolutes only within one.
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
