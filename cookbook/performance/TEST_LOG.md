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

## Notes

- 2026-08-21: First version of `_bench.py` stored the mock's requested tool name as
  `self._tool_name`, silently shadowing `Model._tool_name` (a sort-key method) and breaking
  every tooled run with "'str' object is not callable" while still exiting 0. Fixed by renaming
  the attribute and adding `ensure_completed()` guards so a failed run crashes its benchmark
  instead of timing the error path.
