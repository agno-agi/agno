# REVIEW_LOG.md - 91 Tools Exceptions

**Review Date:** 2026-02-11
**Branch:** `cookbooks/v2.5-testing`
**Reviewer:** Codex 5.3 + Opus 4.6

---

## Framework Issues

### [FRAMEWORK] function.py:394 — requires_user_input + user_input_fields breaks semantics
`requires_user_input=True` combined with `user_input_fields` on a Function changes the HITL behavior but the field interaction is not well-documented. The `RetryAgentRun` and `StopAgentRun` exceptions bypass HITL entirely, which is correct but may surprise users expecting HITL hooks to fire.

**Severity:** Low
**Action:** Log only

---

## Quality Issues

- `retry_tool_call.py` — Good teaching example of RetryAgentRun with session_state
- `retry_tool_call_from_post_hook.py` — Shows post-hook raising RetryAgentRun (advanced pattern)
- `stop_agent_exception.py` — Clean StopAgentRun example

---

## Compatibility

No v2.5 compatibility issues found. All files use standard imports and APIs.

## Fixes Applied

None needed.
