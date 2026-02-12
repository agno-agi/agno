# TEST_LOG for cookbook/04_workflows/04_parallel_execution

Generated: 2026-02-11

### parallel_basic.py

**Status:** PASS

**Description:** Tests Parallel step execution with two research agents (HackerNews + Web) followed by sequential write and review steps. All 4 execution variants tested.

**Result:**
- Sync: PASS (16.4s)
- Sync streaming: PASS (27.4s)
- Async: PASS (25.4s)
- Async streaming: PASS (38.2s, retry on attempt 1 due to "Event loop is closed" error)

**Notes:** The async streaming variant hits an "Event loop is closed" error on its first attempt when run after `asyncio.run()` for async non-streaming. The framework retry mechanism recovers gracefully. This is a framework-level issue with multiple `asyncio.run()` calls in the same process — [A] FRAMEWORK, log-only.

---

### parallel_with_condition.py

**Status:** PASS (partial)

**Description:** Combines Condition evaluators with Parallel execution for adaptive research. Uses ExaTools (requires EXA_API_KEY), HackerNewsTools, and WebSearchTools. Tests sync-stream and async-stream variants.

**Result:**
- Sync streaming: PASS (99.1s, Exa tool errors for unsupported 'github' category — LLM hallucination, not framework bug)
- Async streaming: TIMEOUT (killed at 120s — not enough time after 99.1s first variant)

**Notes:**
- Required `exa_py` package installation (`uv pip install exa_py`)
- Only tests 2 of 4 variants (missing sync and async non-streaming) — [B] COOKBOOK QUALITY
- Single run takes ~99s, making 2 variants in 120s impossible — consider separating into individual test calls
- Exa `category: github` errors are LLM hallucination, not framework/cookbook issue

---
