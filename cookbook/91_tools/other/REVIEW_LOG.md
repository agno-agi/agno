# REVIEW_LOG.md - 91 Tools Other

**Review Date:** 2026-02-11
**Branch:** `cookbooks/v2.5-testing`
**Reviewer:** Codex 5.3 + Opus 4.6

---

## Framework Issues

### [FRAMEWORK] function.py:394 — requires_user_input + user_input_fields semantic conflict
The `requires_user_input=True` flag combined with `user_input_fields` on Function creates ambiguous behavior. The field names suggest data collection, but the flag suggests pausing for human input. The two mechanisms serve different purposes but share the same code path.

**Severity:** Medium
**Action:** Log only

### [FRAMEWORK] agent/_tools.py:396 — agent-level tool_hooks overwrite function/toolkit-level hooks
(Same as tool_hooks finding.) Agent tool_hooks replace rather than chain with toolkit-level hooks.

**Severity:** Medium
**Action:** Log only

---

## Quality Issues

- `human_in_the_loop.py` — Uses rich.Prompt for interactive confirmation (SKIP in automated testing)
- `stop_after_tool_call_dual_inheritance.py` — Teaches session_state as auto-injected via RunContext, but the pattern of dual inheritance (Toolkit + another base) is advanced and may confuse beginners
- `cache_tool_calls.py` — Good async caching example with WebSearchTools + YFinanceTools
- `complex_input_types.py` — Excellent example of Pydantic models as tool inputs
- `session_state_tool.py` — Clean RunContext session_state manipulation example
- Several files mix sync and async patterns in the same script (educational but potentially confusing)

---

## Compatibility

No v2.5 compatibility issues found. All files use standard imports and APIs.

## Fixes Applied

None needed.
