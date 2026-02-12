# REVIEW_LOG.md - 91 Tools Hooks

**Review Date:** 2026-02-11
**Branch:** `cookbooks/v2.5-testing`
**Reviewer:** Codex 5.3 + Opus 4.6

---

## Framework Issues

### [FRAMEWORK] function.py:703,731 — sync pre-hook calls async hook without awaiting
When a sync pre-hook is registered alongside an async post-hook, the async hook may not be properly awaited in the sync execution path. The `_run_pre_hook` method at line 703 doesn't differentiate between sync/async hooks in all code paths.

**Severity:** Medium
**Action:** Log only

### [FRAMEWORK] agent/_tools.py:396 — agent-level tool_hooks overwrite function/toolkit-level hooks
When an agent has `tool_hooks` set, these overwrite any hooks defined at the function or toolkit level rather than chaining them. This means toolkit-specific hooks are silently lost when agent-level hooks are present.

**Severity:** Medium
**Action:** Log only

### [FRAMEWORK] toolkit.py:18 — mutable default `tools=[]` risk
The `Toolkit` class uses a mutable default argument pattern that could lead to shared state between instances if not properly re-initialized in `__init__`.

**Severity:** Low
**Action:** Log only

---

## Quality Issues

- `tool_hook.py` — Good example of agent-level sync + async hooks
- `tool_hook_in_toolkit.py` — Shows validation_hook pattern with customer ID checking
- `tool_hook_in_toolkit_with_state.py` — Demonstrates RunContext access in hooks
- `tool_hook_in_toolkit_with_state_nested.py` — Shows function_name parameter for nested hooks
- `pre_and_post_hooks.py` — Shows @tool decorator pre/post hooks with async streaming
- `tool_hooks_in_toolkit_nested.py` — Demonstrates multiple stacked hooks execution order

---

## Compatibility

No v2.5 compatibility issues found. All files use standard imports and APIs.

## Fixes Applied

None needed.
