# TEST_LOG.md - 91 Tools Hooks

**Test Date:** 2026-02-11
**Branch:** `cookbooks/v2.5-testing`

---

### tool_hook.py

**Status:** PASS

**Description:** Agent-level tool_hooks with sync and async variants using WebSearchTools.

**Result:** Both sync and async hooks fired correctly. Web search completed.

---

### tool_hook_in_toolkit.py

**Status:** PASS

**Description:** Toolkit with validation_hook checking customer IDs before tool execution.

**Result:** Validation hook triggered, tool executed with both sync and async paths.

---

### tool_hook_in_toolkit_with_state.py

**Status:** PASS

**Description:** Tool hook using RunContext to access session_state.

**Result:** Session state accessible in hook. Profile retrieved.

---

### tool_hook_in_toolkit_with_state_nested.py

**Status:** PASS

**Description:** Multiple nested tool hooks using RunContext and function_name parameter.

**Result:** Nested hooks chained correctly. Profile retrieved.

---

### pre_and_post_hooks.py

**Status:** PASS

**Description:** Pre/post hooks on @tool decorator with async variants and streaming.

**Result:** Both pre and post hooks fired. HackerNews stories fetched via streaming.

---

### tool_hooks_in_toolkit_nested.py

**Status:** PASS

**Description:** Multiple stacked hooks with both sync and async implementations.

**Result:** Nested hooks executed in correct order. Customer profile deleted via hook chain.

---

## Summary

| PASS | FAIL | SKIP | Total |
|------|------|------|-------|
| 6    | 0    | 0    | 6     |
