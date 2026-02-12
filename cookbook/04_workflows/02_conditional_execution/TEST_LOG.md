# TEST_LOG for cookbook/04_workflows/02_conditional_execution

> v2.5 audit — 2026-02-11 (timeout: 120s)

### condition_basic.py

**Status:** PASS

**Description:** Conditional step execution using a fact-check gate evaluator. If previous output contains statistical indicators, runs a fact-check step.

**Result:** Both sync-stream and async-stream runs completed. Condition evaluator correctly triggered fact-checking branch.

---

### condition_with_else.py

**Status:** PASS

**Description:** `Condition(..., else_steps=[...])` routing between technical and general support branches based on keyword detection.

**Result:** All 4 runs completed (sync tech, sync general, async tech, async general). Both if-branch and else-branch correctly executed based on input content.

---

### condition_with_list.py

**Status:** PASS

**Description:** Condition branches that execute a list of multiple steps, including parallel conditional blocks using ExaTools and HackerNewsTools.

**Result:** Both sync-stream and async runs completed. Parallel conditions within workflow executed correctly.

---

### condition_with_parallel.py

**Status:** PASS

**Description:** Multiple conditional branches executed in parallel (HN, web, Exa) before final synthesis. Uses ExaTools.

**Result:** All 4 run modes (sync, sync-stream, async, async-stream) completed. Parallel conditional research steps correctly filtered by evaluators.

---
