# TEST_LOG.md - 91 Tools Decorator

**Test Date:** 2026-02-11
**Branch:** `cookbooks/v2.5-testing`

---

### tool_decorator.py

**Status:** PASS

**Description:** Basic @tool with show_result=True, sync weather tool + async static method variant.

**Result:** Weather tool called and result shown correctly.

---

### async_tool_decorator.py

**Status:** PASS

**Description:** Async @tool using AsyncIterator and httpx.AsyncClient for HackerNews.

**Result:** Async tool fetched top HackerNews stories via streaming.

---

### cache_tool_calls.py

**Status:** PASS

**Description:** @tool with cache_results=True and stop_after_tool_call=True.

**Result:** Tool results cached correctly. Raw JSON output returned with stop_after_tool_call.

---

### stop_after_tool_call.py

**Status:** PASS

**Description:** @tool with stop_after_tool_call=True returns tool result directly.

**Result:** Agent stopped after tool call. Returned "42" correctly.

---

### tool_decorator_on_class_method.py

**Status:** PASS

**Description:** @tool decorator on Toolkit class methods with Generator return type.

**Result:** Class method tool called. Greeting returned with multiplier value.

---

### tool_decorator_with_hook.py

**Status:** PASS

**Description:** @tool with tool_hooks parameter for pre/post processing.

**Result:** Hooks fired. HackerNews stories fetched.

---

### tool_decorator_with_instructions.py

**Status:** PASS

**Description:** @tool with name, description, show_result, and instructions parameters.

**Result:** Custom-named tool called. HackerNews stories retrieved.

---

## Summary

| PASS | FAIL | SKIP | Total |
|------|------|------|-------|
| 7    | 0    | 0    | 7     |
