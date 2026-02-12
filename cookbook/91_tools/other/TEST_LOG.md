# TEST_LOG.md - 91 Tools Other

**Test Date:** 2026-02-11
**Branch:** `cookbooks/v2.5-testing`

---

### add_tool_after_initialization.py

**Status:** PASS

**Description:** Using agent.add_tool() to add a weather tool after agent initialization.

**Result:** Tool added dynamically. Weather query answered.

---

### cache_tool_calls.py

**Status:** PASS

**Description:** Async agent with cache_results=True on WebSearchTools and YFinanceTools.

**Result:** Async web search completed. Apple news retrieved with caching.

---

### complex_input_types.py

**Status:** PASS

**Description:** Pydantic models as tool inputs (UserProfile, TaskConfig with enums/nested models).

**Result:** User profile created. Task creation handled complex input types.

---

### human_in_the_loop.py

**Status:** SKIP

**Description:** Pre-hook with user confirmation using rich.Prompt before tool execution.

**Result:** Skipped — requires interactive terminal input (rich.Prompt).

---

### include_exclude_tools.py

**Status:** PASS

**Description:** Built-in toolkits with exclude_tools and include_tools parameters.

**Result:** Calculator tools correctly limited. Math computation completed.

---

### include_exclude_tools_custom_toolkit.py

**Status:** PASS

**Description:** Custom Toolkit with include_tools to expose only specific methods.

**Result:** Only retrieve_customer_profile exposed (delete excluded). Profile retrieved.

---

### session_state_tool.py

**Status:** PASS

**Description:** Tool manipulating session_state via RunContext.

**Result:** Session state updated correctly. Capital of Germany stored as "Berlin".

---

### stop_after_tool_call.py

**Status:** PASS

**Description:** WebSearchTools with stop_after_tool_call_tools and show_result_tools.

**Result:** Raw web search results returned. Agent stopped after tool call.

---

### stop_after_tool_call_dual_inheritance.py

**Status:** PASS

**Description:** Toolkit with dual inheritance pattern using stop_after_tool_call_tools.

**Result:** filter_changed tool called, agent stopped. Custom render type returned.

---

### stop_after_tool_call_in_toolkit.py

**Status:** PASS

**Description:** Toolkit with stop_after_tool_call_tools parameter.

**Result:** increment_and_stop called. Counter set to 10, agent stopped.

---

## Summary

| PASS | FAIL | SKIP | Total |
|------|------|------|-------|
| 9    | 0    | 1    | 10    |
