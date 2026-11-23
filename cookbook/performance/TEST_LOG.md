# Test Log

Environment: `.venv` (Python 3.12.8, agno 3.0.0a2, editable install), Apple M4 Max, macOS 15.
All benchmarks run with `AGNO_TELEMETRY=false` via `run_all.py` (fresh process per benchmark file).

## 2026-08-21

### run_all.py (full suite, final baseline)

**Status:** PASS

**Description:** Full sequential baseline at commit e86fff58d on an otherwise idle machine:
10 benchmark files, 16 result sets, summary.json written, zero failures, zero agno ERROR lines.
Snapshot committed as `baselines/2026-08-21-apple-m4-max.json` (raw sample lists stripped).

**Result:** Medians: agent instantiation 2.9 us / 5.1 KiB peak; team 15.8 us; workflow 6.5 us;
run 88 us; arun 91 us; streaming 100 / 112 us; tool-call run 370 us sync vs 618 us async;
storage run 322 us sync vs 326 us async; `import agno` 18 ms; `from agno.agent import Agent`
242 ms; resident memory 3.66 KiB per live agent.

---

### run_all.py --quick (smoke)

**Status:** PASS

**Description:** 5-iteration smoke of every benchmark; results isolated in `results/quick/`.

**Result:** All benchmarks complete and write JSON results; full-run results untouched.

---

### report.py

**Status:** PASS

**Description:** Rendered results/summary.json to report/agno-performance.html (standalone
document) and an artifact variant. Verified in browser in dark and light color schemes;
verified the quick-run caveat banner and missing-benchmark handling against synthetic inputs.

**Result:** Self-contained HTML renders correctly in both themes.

---

### comparison/run_all.py

**Status:** PASS

**Description:** Cross-framework comparison in `.venvs/compare` (agno 3.0.0a2 editable,
langgraph 1.2.11, langchain-openai 1.6.0, pydantic-ai 2.31.1, crewai 1.15.17), fresh process
per benchmark, telemetry disabled, placeholder API key (construction only, no network).

**Result:** Tooled-agent construction medians: agno 4.7 us / 7.1 KiB peak, LangGraph 1,147 us
(246x) / 146 KiB, PydanticAI 9,312 us (1,996x) / 39 KiB, CrewAI 18,700 us (4,012x) / 24 KiB.
Cold import of the Agent entrypoint (same venv): agno 281 ms, LangGraph 364 ms,
PydanticAI 514 ms, CrewAI 1,009 ms. Comparison sections render in report.py.

---

### Post-merge re-baseline (2026-08-21, after #9678 and #9689 merged)

**Status:** PASS

**Description:** Full core suite re-run on the feat/v3.0 tip (7aa29c691) containing the
lazy-import and runtime quick-win merges; snapshot committed as
`baselines/2026-08-21-apple-m4-max-post-merge.json`.

**Result:** Cold import of `agno.agent` 242 -> 158 ms; storage run 322 -> 201 us sync /
326 -> 242 us async; tool run 370 -> 337 us; plain run 88 -> 82 us (session conditions);
instantiation and resident memory unchanged.

---

### comparison/run_overhead_comparison.py (new)

**Status:** PASS

**Description:** Cross-framework single-turn mocked run added to the comparison suite:
identical shape per framework, model replaced at each framework's own boundary (Agno Model
subclass, LangChain GenericFakeChatModel, PydanticAI TestModel, CrewAI BaseLLM subclass).
Full comparison suite re-run in `.venvs/compare` against the merged tip.

**Result:** Medians: agno 65 us, LangGraph 310 us (4.8x), PydanticAI 2,258 us (35x),
CrewAI 6,283 us (97x); run memory peaks 16.6 / 55 / 105 / 96 KiB. Construction and import
sections re-measured in the same run; report gains a "Single-turn run vs other frameworks"
section.

---

### scripts/perf_setup.sh + rich summary tables (2026-08-21)

**Status:** PASS

**Description:** The suite now standardizes on `.venvs/perfenv` built by
`./scripts/perf_setup.sh` (updated to install agno editable from the checkout, with the
os extra since `agno.workflow` imports fastapi, plus the comparison frameworks). Both
runners finish with a rich summary table (median / p95 / memory per benchmark). Smoke ran
both suites end to end in the fresh perfenv.

**Result:** All benchmarks pass in perfenv, including `instantiate_workflow.py` which fails
without the os extra. Rich tables render for core and comparison runs.

---

### comparison/multi_turn_comparison.py (new)

**Status:** PASS

**Description:** Five-turn conversation per framework with history carried by each
framework's native mechanism (Agno session + in-memory db persistence per turn with the
history cap raised to cover the conversation; LangGraph InMemorySaver checkpointer per
thread; PydanticAI message_history; CrewAI five tasks chained via Task.context). Every
variant asserts post-conversation that history actually accumulated. During construction,
two silent-statelessness traps were caught by the guards: Agno's default num_history_runs=3
capped context (raised for parity), and LangGraph's message reducer dedupes by message id,
so a cycled shared AIMessage silently dropped responses (fixed with fresh objects per turn).

**Result:** Clean-run medians: agno 2.2 ms, LangGraph 3.4 ms (1.6x), PydanticAI 8.3 ms
(3.9x), CrewAI 24.4 ms (11x) per conversation. Note the multi-turn gap versus LangGraph is
narrower than single-turn (1.6x vs 4.9x): Agno's turns include full session persistence,
LangGraph's checkpointer is an in-memory dict. Published as measured.

---

### comparison/tool_run_comparison.py and comparison/long_conversation_comparison.py (new)

**Status:** PASS

**Description:** Two benchmarks added specifically to probe where Agno's deferred-work
design should struggle. Tool-call run: one real tool execution per run (mocked model
requests the call, framework dispatches the actual function, second turn answers; every
variant asserts execution; CrewAI excluded - its custom-model tool protocol is
version-internal text). 25-turn conversation: the 5-turn benchmark at length 25, where
history-proportional costs dominate.

**Result:** Tool-call run: agno 318 us, LangGraph 813 us (2.6x), PydanticAI 2,389 us
(7.5x) - agno still fastest despite paying deferred schema extraction per run, but the
margin is far narrower than construction. 25-turn conversation: **agno 37.8 ms LOSES to
LangGraph 22.3 ms (0.6x)**; PydanticAI 38.9 ms at parity; CrewAI 91.7 ms. Cause: per-turn
session re-serialization grows quadratically with conversation length versus LangGraph's
by-reference in-memory checkpointer. Published as measured; the growth term maps to the
roadmap's serialize-once and history copy-on-write items.

---

### Matched-configuration conversations + durable benchmark (2026-08-21)

**Status:** PASS

**Description:** After the 25-turn loss surfaced, three control experiments decomposed it:
cache_session=True recovers ~19% (31.1 vs 38.6 ms) and still loses; durable-vs-durable
(Agno SqliteDb vs LangGraph SqliteSaver) also loses (60-64 vs 39-42 ms) - refuting the
"we lose because we persist" hypothesis. The conversation benchmarks were therefore
restructured into matched configurations: in-memory rows run Agno with cache_session=True
(the analogue of LangGraph's always-cached saver, using unique session ids per conversation
to avoid the cache/db-swap bug found during probing and filed separately), and a new
durable row runs SqliteDb vs SqliteSaver with fresh database files per conversation.

**Result:** Clean run: 5-turn in-memory agno 1.9 ms (wins 2.0x over LangGraph); 25-turn
in-memory agno 32.4 vs LangGraph 23.7 ms (0.7x, loss); 25-turn durable agno 60.3 vs
LangGraph 38.8 ms (0.6x, loss). Conclusion recorded in the README results discussion: the
long-conversation loss is Agno's per-turn write-path serialization growing with history,
not a durability capability difference; short conversations widen Agno's win.

---

## Review round (2026-08-21)

A 34-agent adversarial review (methodology, mock fidelity, house rules, report, runner
robustness; every finding independently verified) confirmed 21 findings, all fixed:

- The storage benchmark originally drifted upward ~15% across iterations (InMemoryDb scans a
  growing session list) and the async variant ran against ~1010 sessions left by the sync pass,
  which fabricated a 180 us "async storage penalty". Both benchmark functions now reset to a
  fresh empty db each iteration (constant ~2.5 us); sync and async storage now measure equal.
- The verified re-run shows the tool-call async penalty (370 vs 618 us) is real, caused by
  asyncio.to_thread per sync tool call on the async path.
- Guards: every run benchmark asserts completion (and tool success where applicable), the
  streaming benchmark asserts error-free content, import failures surface stderr, the runner
  clears stale result files, and quick runs are isolated and labeled in the report.

## 2026-08-22

### comparison/run_all.py (full suite, after SqliteDb WAL journal mode)

**Status:** PASS

**Description:** Full sequential comparison run at commit 6dd178afe (feat/v3.0 plus the
SqliteDb WAL change) in a fresh perf environment; 10 benchmark files, zero failures,
summary.json written. Purpose: re-measure the durable 25-turn row now that SqliteDb runs
WAL journal mode, matching the configuration LangGraph's SqliteSaver already used.

**Result:** Durable 25-turn medians: agno 42.2 ms vs LangGraph 36.5 ms (0.9x) — up from
52.3 vs 39.0 ms (0.7x) before WAL; most of the previous gap was the journal-mode mismatch
(DELETE journal's file create, double fsync, and delete per commit). A standalone run of
durable_conversation_comparison.py in the same environment measured agno at 39.6 ms median,
at parity with LangGraph — run-to-run variance on this row is a few ms. All other rows
reproduced the published reference table within noise, except the cold-import rows, which
are inflated for every framework in this environment by full pydantic-ai pulling logfire
(its pydantic plugin hooks imports); the import rows were therefore left as published.
Reference table durable row and discussion updated in README.md.

---

## 2026-08-24 (run_id re-test)

`PerformanceResult` now requires `run_id` (eval runs are stored under a
per-execution id). The three direct constructions in this suite were updated to
pass `run_id=name`, so those three results are keyed by their metric name rather
than a fresh UUID. This does not make the committed baselines deterministic:
`save_result()` in `_bench.py` writes `asdict(result)`, so every entry produced
by `run_benchmarks()` now carries a per-run UUID alongside the `measured_at`
timestamp and the raw per-iteration samples, both of which already differ on
each regeneration.

### memory_footprint.py

**Status:** PASS

**Description:** Live run after `PerformanceResult(run_id=name, ...)` replaced the
two-argument construction; 1000 agents per sample, 5 samples.

**Result:** `memory_per_agent` median 3.66 KiB and `memory_per_agent_with_tools`
median 3.67 KiB per live agent.

---

### import_time.py

**Status:** PASS

**Description:** Live run with the same constructor change; interpreter startup
subtracted from each sample.

**Result:** `import_agno` median 23.0 ms, `import_agno_agent` median 209.0 ms.

---

### comparison/import_time_comparison.py

**Status:** PASS

**Description:** The comparison targets need the competitor frameworks, which the dev
venv does not carry, so this ran in a throwaway virtualenv holding agno 3.0.0a4 built
from this worktree plus langgraph 1.2.11, pydantic-ai-slim 2.31.1 and crewai 1.6.1.
10 samples per target, interpreter startup subtracted.

**Result:** Interpreter startup median 15.2 ms. `import_compare_agno` median 516.5 ms
(p95 532.2), `import_compare_langgraph` 1198.2 ms (p95 1257.6),
`import_compare_pydantic_ai` 786.1 ms (p95 827.7), `import_compare_crewai` 1483.8 ms
(p95 1557.0). These four are comparable to each other but not to the `import_time.py`
medians above: different virtualenv, and each target imports its framework's agent
construction path rather than the bare package.

---

## Notes

- 2026-08-21: First version of `_bench.py` stored the mock's requested tool name as
  `self._tool_name`, silently shadowing `Model._tool_name` (a sort-key method) and breaking
  every tooled run with "'str' object is not callable" while still exiting 0. Fixed by renaming
  the attribute and adding `ensure_completed()` guards so a failed run crashes its benchmark
  instead of timing the error path.
