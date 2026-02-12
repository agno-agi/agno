# REVIEW_LOG.md - Quick Start Cookbook

Code review findings for `cookbook/00_quickstart/` — three-layer audit.

**Review Date:** 2026-02-11
**Reviewer:** Codex GPT-5.3 + Opus 4.6 cross-review
**Branch:** `cookbooks/v2.5-testing`
**Scope:** Framework code used by quickstart + all 13 cookbook .py files

---

## [FRAMEWORK] Framework Bugs & Regressions

### [HIGH] Workflow output_files never assigned to response

**Location:** `libs/agno/agno/workflow/workflow.py:1717`

`output_files` is collected/extended across all execution paths (sync, async, stream, async stream) but is never assigned to `workflow_run_response.files`. Any workflow step that produces output files silently loses them.

**Impact:** Affects `sequential_workflow.py` and any workflow producing files.

---

### [HIGH] Async generator tool wrapper returns instead of yielding

**Location:** `libs/agno/agno/tools/decorator.py:196`

`async_gen_wrapper` is defined as `async def` but uses `return func(...)` instead of `async for ... yield`. This converts async generator tools into coroutines that return the generator object rather than yielding values. Callers expecting `async for` will get a single generator object.

**Impact:** Any `@tool` wrapping an async generator function.

---

### [MEDIUM] SqliteDb.close() doesn't clear scoped sessions

**Location:** `libs/agno/agno/db/sqlite/sqlite.py:180`

`close()` disposes the engine but does not call `self.Session.remove()` to clear thread-local scoped sessions. In multi-threaded environments (e.g., AgentOS serving multiple requests), stale sessions may remain in thread-local storage after close.

**Impact:** Affects `agent_with_storage.py` and any agent using SqliteDb in server context.

---

### [LOW] Step retry_count field mismatch

**Location:** `libs/agno/agno/workflow/step.py:75` vs `:518`, `:814`, `:1043`, `:1332`

Internal field is `_retry_count` (line 75) but assignment writes to `self.retry_count` (lines 518, 814, 1043, 1332). The underscore-prefixed field and the assigned field are different attributes, meaning `_retry_count` is never updated.

**Impact:** Low — retry tracking may be inaccurate but doesn't affect execution flow.

---

### [LOW] Agent ThreadPoolExecutor leak

**Location:** `libs/agno/agno/agent/agent.py:659`

`ThreadPoolExecutor` is lazily created with no teardown path. When many short-lived Agent instances are created (e.g., in tests), each gets its own executor with 3 threads that are never shut down.

**Impact:** Low — affects long-running processes creating many agents. No impact on quickstart examples.

---

## [QUALITY] Teaching Clarity

### [MEDIUM] Structured output encourages hallucination

**Location:** `cookbook/00_quickstart/agent_with_structured_output.py:81`

Instructions say "If exact data isn't available, provide your best estimate" — this encourages the model to hallucinate financial values rather than returning null/unknown. For a teaching example about structured output, this sends the wrong message about reliability.

**Recommendation:** Change to "If data is unavailable, set the field to None" and make fields Optional.

---

### [MEDIUM] Self-learning tool relies on prompt-only confirmation

**Location:** `cookbook/00_quickstart/custom_tool_for_self_learning.py:61`

The `save_learning` tool can be called freely by the agent. The instructions say "Only call save_learning AFTER the user says yes" but this is just prompt discipline — no actual enforcement. A teaching example should either use `requires_confirmation=True` or acknowledge the limitation.

---

### [LOW] Shared persistent paths across examples

**Location:** `cookbook/00_quickstart/agent_with_storage.py:30`, `agent_search_over_knowledge.py:29`

Multiple quickstart files share the same `tmp/agents.db` and `tmp/chromadb/` paths. Running examples in sequence can cause cross-contamination of data. Learners may see confusing state from previous runs.

**Recommendation:** Use unique paths per example or add cleanup notes.

---

## [COMPAT] v2.5 Compatibility

**No issues found.** All imports, APIs, and patterns are clean v2.5.

---

## Summary

| Layer | HIGH | MEDIUM | LOW |
|-------|------|--------|-----|
| FRAMEWORK | 2 | 1 | 2 |
| QUALITY | 0 | 2 | 1 |
| COMPAT | 0 | 0 | 0 |
| **Total** | **2** | **3** | **3** |
