# Test Log — Context Compaction

Environment: `.venvs/demo` with `PYTHONPATH` pointing at the feature worktree; model `gpt-5.6-luna` via `OpenAIResponses`; `SqliteDb` at `tmp/compaction.db` (deleted before the first run).

Date: 2026-08-30, on the final `feat/compaction` build (post review fixes).

---

### 01_context_compaction.py

**Status:** PASS

**Description:** Six detailed database-internals questions on one session with `Compaction(context_window=8_000)`. Exercises the threshold trigger, background folds across runs, and the record chain readout.

**Result:** Exit 0, no errors. Three threshold records committed with real before/after numbers (`7929 -> 5582`, `8943 -> 4458`, `7618 -> 4949` tokens); the conversation never pauses and answers stay coherent across the folds.

---

### 02_manual_compact.py

**Status:** PASS

**Description:** Three short turns (a flaky-test debugging thread plus an unrelated reminder), then `agent.compact()` with focus instructions, then a recall question. Exercises the manual `/compact` analog and instruction steering. The window was tightened to `context_window=2_000` during testing: at 16k the whole conversation fit inside the kept tail and `compact()` correctly returned `None`, which demonstrated the no-op branch instead of the fold.

**Result:** Exit 0, no errors. The manual pass produces a record whose summary keeps the flaky-test detail per the instructions, and the follow-up question recovers both the PR-8812 fix and the Friday reminder from the summary plus tail.

---

### 03_compaction_events.py

**Status:** PASS

**Description:** Four streamed runs with `stream_events=True` and `background=False` on a 6k window, printing `CompactionStarted` / `CompactionCompleted` events inline with content.

**Result:** Exit 0, no errors. Two live event pairs streamed mid-run with real numbers: `[compaction started: reason=threshold tokens_before=6805]` → `[compaction completed: 6805 -> 1653 tokens, record cmp_a279...]` and a second pair at `6163 -> 1448`.

---

### 04_compaction_with_offload.py

**Status:** PASS

**Description:** `offload_tool_results=True` composed with `Compaction(context_window=8_000)` on a tool-using agent: fetch a large inventory, discuss it, then answer a question that requires reading the stored result back by id.

**Result:** Exit 0, no errors. The final turn reads the offloaded result via `search_result(result_id=res_0adc5d6485, ...)` and answers correctly — result ids survive compaction. This cookbook also caught a real integration bug during testing: with response chaining stripped by compaction, the Responses API rejected re-sent `function_call` items without their paired `reasoning` items (400). Fixed in the branch (reasoning items are captured regardless of `store` and re-sent, ordered before their function_call, whenever the request is not chaining); this run is the live confirmation.

---
