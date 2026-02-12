# REVIEW_LOG.md - 91 Tools Decorator

**Review Date:** 2026-02-11
**Branch:** `cookbooks/v2.5-testing`
**Reviewer:** Codex 5.3 + Opus 4.6

---

## Framework Issues

### [FRAMEWORK] decorator.py:245 — @tool mutates config with kwargs
The `@tool` decorator mutates the tool config dict in-place when processing kwargs. If the same config object is reused (e.g., via module-level defaults), subsequent decorations could see stale values.

**Severity:** Low
**Action:** Log only

---

## Quality Issues

- `tool_decorator.py` — Good basic @tool example with show_result=True
- `async_tool_decorator.py` — Shows AsyncIterator return type with httpx.AsyncClient
- `cache_tool_calls.py` — Demonstrates cache_results=True + stop_after_tool_call=True combo
- `stop_after_tool_call.py` — Clean example of stop_after_tool_call=True returning raw result
- `tool_decorator_on_class_method.py` — Shows @tool on Toolkit class methods with Generator return
- `tool_decorator_with_hook.py` — Demonstrates tool_hooks parameter on @tool
- `tool_decorator_with_instructions.py` — Shows name/description/instructions overrides

---

## Compatibility

No v2.5 compatibility issues found. All files use standard imports and APIs.

## Fixes Applied

None needed.
