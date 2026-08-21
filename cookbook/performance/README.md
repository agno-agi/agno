# Agno Performance Benchmarks

This suite measures framework overhead: the time and memory an agent
framework itself adds to importing, constructing, and running an agent,
isolated from any model provider. All benchmarks replace the model with an
in-process mock at the framework's own model boundary, so no measurement
depends on a provider, an API key, or the network, and every result is
reproducible from a checkout of this repository.

It has two parts: the Agno suite, which tracks Agno's own overhead across
releases against committed baselines, and a cross-framework comparison
measuring the same operations in LangGraph, PydanticAI, and CrewAI under
identical conditions.

## Reference results

Measured 2026-08-21 on an Apple M4 Max, Python 3.12, all four frameworks
installed in a single environment, one sequential run, medians reported.
Framework versions: LangGraph 1.2.11, PydanticAI 2.31.1, CrewAI 1.15.17;
Agno at the feat/v3.0 tip.

| Metric | Agno | LangGraph | PydanticAI | CrewAI |
|---|---|---|---|---|
| Single-turn run (mocked model) | 65 us | 320 us (4.9x) | 1,592 us (24x) | 5,234 us (80x) |
| 5-turn conversation (mocked model) | 2.2 ms | 3.4 ms (1.6x) | 8.3 ms (3.9x) | 24.4 ms (11x) |
| Agent construction (1 tool) | 4.6 us | 1,105 us (239x) | 9,664 us (2,090x) | 19,323 us (4,178x) |
| Construction memory peak | 7.1 KiB | 146 KiB (21x) | 39 KiB (5.6x) | 24 KiB (3.4x) |
| Cold import | 250 ms | 390 ms (1.6x) | 533 ms (2.1x) | 1,105 ms (4.4x) |

Multipliers are relative to Agno. The committed reference runs, including
per-benchmark distributions, are under `baselines/`; the definition of each
metric is below, and `comparison/README.md` documents exactly where each
framework's mock intervenes.

## 1. Environment setup

```bash
./scripts/perf_setup.sh
```

Creates `.venvs/perfenv` with Agno installed editable from this checkout —
benchmarks measure the working tree, not a release — together with the
comparison frameworks. The install is editable, so code changes take effect
without rebuilding; re-run the script only when dependencies change.

## 2. Agno benchmarks

```bash
.venvs/perfenv/bin/python cookbook/performance/run_all.py
```

Runs every Agno benchmark sequentially, each in a fresh Python process, and
prints a summary table of medians, p95s, and memory. Results are written as
JSON to `results/`, one file per benchmark plus `summary.json`. Run on an
otherwise idle machine; CPU contention skews timings.

`--quick` runs a five-iteration smoke in about thirty seconds; its output
is isolated in `results/quick/` so it can never be mistaken for a baseline.
Any benchmark file also runs standalone
(`.venvs/perfenv/bin/python cookbook/performance/run_agent.py`) with
detailed per-run tables.

## 3. Cross-framework comparison

```bash
.venvs/perfenv/bin/python cookbook/performance/comparison/run_all.py
```

Runs the comparison benchmarks — cold import, one-tool agent construction,
and a mocked single-turn run per framework — and prints the
Agno-versus-frameworks table with multipliers, followed by the full summary.
Results are written to `results/comparison/summary.json` with framework
versions recorded.

## 4. Report

```bash
.venvs/perfenv/bin/python cookbook/performance/report.py
```

Renders `results/` into a self-contained HTML report at
`report/agno-performance.html`: the comparison table with multipliers, then
per-metric charts and full statistics for every benchmark. The comparison
sections appear whenever `results/comparison/summary.json` exists. Any
committed baseline renders the same way via
`report.py --results baselines/<file>`.

## Measurement definitions

| Benchmark | File | Definition |
|-----------|------|------------|
| `import_agno`, `import_agno_agent` | `import_time.py` | Wall time to import in a fresh process, median interpreter startup subtracted. Paid once per process; dominates CLI and serverless cold starts. |
| `instantiate_agent` | `instantiate_agent.py` | Constructing a bare `Agent`. |
| `instantiate_agent_with_tools` | `instantiate_agent_with_tools.py` | Constructing an `Agent` with five function tools. |
| `instantiate_team` | `instantiate_team.py` | Constructing a `Team` with three member agents. |
| `instantiate_workflow` | `instantiate_workflow.py` | Constructing a two-step `Workflow`. |
| `run_agent`, `arun_agent` | `run_agent.py` | One complete `run()` / `arun()` against the mock model: per-run framework overhead. |
| `run_agent_streaming`, `arun_agent_streaming` | `run_agent_streaming.py` | One streaming run with the event stream fully drained. |
| `run_agent_with_tools`, `arun_agent_with_tools` | `run_agent_with_tools.py` | A two-turn tool loop: tool call request, real tool execution, final answer. |
| `run_agent_with_storage`, `arun_agent_with_storage` | `run_agent_with_storage.py` | One run with an in-memory database and history enabled: session persistence overhead. |
| `memory_per_agent`, `memory_per_agent_with_tools` | `memory_footprint.py` | Net resident memory per live agent over batches of 1000 held alive. |

For examples of the `PerformanceEval` API itself, including benchmarks that
call real models, see `cookbook/09_evals/performance/`.

## Methodology

- **Mock models drive the real loop.** Each mock subclasses the framework's
  model interface and returns a canned response, so message construction,
  tool dispatch, event streaming, output construction, and session
  bookkeeping all execute exactly as in production; only the provider call
  is replaced. Work a real provider integration performs inside the
  framework (wire-format conversion, response parsing) is excluded, so
  every reported number — for every framework — is a floor on that
  framework's per-run overhead.
- **Process isolation.** Each benchmark file runs in a fresh Python process
  so no benchmark inherits another's warmed caches or allocator state. Sync
  and async variants within one file share a process; their benchmark
  functions are written so no state carries between iterations or variants.
- **Runtime and memory are measured in separate passes** (a
  `PerformanceEval` property): tracemalloc slows execution, so timed
  iterations are never traced.
- **Warmup runs are excluded** from all statistics (10 per benchmark by
  default).
- **Correctness is asserted inside every run benchmark**: the run must
  complete with the expected content, and tool benchmarks additionally
  require that the tool executed without error. A broken code path crashes
  its benchmark rather than silently contributing error-path timings.
- **Import time** is measured in fresh subprocesses because a module import
  happens once per process; the median interpreter startup is subtracted
  from each sample.
- **Memory footprint** holds agents alive and reports the net allocation
  delta per agent, which is the quantity capacity planning needs; the
  instantiation benchmarks report the larger transient allocation peak of
  construction.
- **Statistics**: medians and p95 are reported in preference to means;
  distributions carry a long tail from garbage collection pauses. The timing
  harness costs roughly two hundred nanoseconds per call, a few percent of
  the microsecond-scale construction numbers and negligible elsewhere.

## Limitations

- Absolute values are machine- and environment-dependent. Import times in
  particular scale with the number of installed packages, so the comparison
  environment (which carries all four frameworks) reads higher than a lean
  install for every framework. Ratios transfer across environments;
  absolute values should only be compared within one.
- Mocked-run numbers are per-framework floors, not full provider-path
  costs. A comparison at the HTTP boundary — a canned response beneath each
  framework's real provider adapter — would include client-side provider
  work and is the natural extension of this suite.
- The streaming benchmarks stream a single chunk and therefore measure the
  fixed cost of the streaming machinery, not per-chunk cost over a long
  delta stream.
- CrewAI's single-turn run includes constructing a `Task` and `Crew`,
  because a crew kickoff is that framework's unit of request execution; its
  `Agent` is reused, as in the other frameworks. See
  `comparison/README.md` for all per-framework accounting decisions.
- The five-turn conversation uses each framework's native history mechanism,
  and those mechanisms do different amounts of work per turn: Agno's figure
  includes reading and persisting the session on every turn, LangGraph's
  includes graph-state checkpointing, PydanticAI's includes no persistence
  at all. The comparison is between each framework's idiomatic multi-turn
  path, not between identical operations.

## Environment variables

| Variable | Effect |
|----------|--------|
| `AGNO_BENCH_RESULTS_DIR` | Write one JSON result file per benchmark into this directory. |
| `AGNO_BENCH_ITERATIONS` | Override every benchmark's iteration count. |
| `AGNO_BENCH_QUIET` | Suppress tables and spinners; print one summary line per benchmark. |
