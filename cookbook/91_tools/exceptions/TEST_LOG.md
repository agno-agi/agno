# TEST_LOG.md - 91 Tools Exceptions

**Test Date:** 2026-02-11
**Branch:** `cookbooks/v2.5-testing`

---

### retry_tool_call.py

**Status:** PASS

**Description:** Tool raises RetryAgentRun with new instructions when shopping list has < 3 items.

**Result:** RetryAgentRun triggered correctly. Agent retried with updated instructions. Session state updated.

---

### retry_tool_call_from_post_hook.py

**Status:** PASS

**Description:** Post-hook on @tool raises RetryAgentRun to force agent re-run.

**Result:** Post-hook triggered RetryAgentRun correctly. Agent retried and completed.

---

### stop_agent_exception.py

**Status:** PASS

**Description:** Tool raises StopAgentRun to halt agent after tool execution.

**Result:** StopAgentRun triggered correctly. Agent stopped after tool execution.

---

## Summary

| PASS | FAIL | SKIP | Total |
|------|------|------|-------|
| 3    | 0    | 0    | 3     |
