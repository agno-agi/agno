# Test Log: 09_decision_logs

**Date:** 2026-02-10
**Environment:** `.venvs/demo/bin/python`
**Model:** gpt-4o
**Services:** pgvector

## Structure Check

**Result:** Checked 2 file(s). Violations: 0
**Details:** Clean

---

## Runtime Results

### 01_basic_decision_log.py

**Status:** PASS
**Time:** ~30s
**Description:** AGENTIC decision logging. Agent logs a language choice decision via tools. Originally failed with `AttributeError: 'Agent' object has no attribute 'get_learning_machine'` -- fixed by changing to `agent.learning_machine` property access.
**Output:** Decision logged with rationale and alternatives, retrievable in later session.
**Triage:** Regression (fixed). Changed `agent.get_learning_machine()` to `agent.learning_machine`.

---

### 02_decision_log_always.py

**Status:** PASS
**Time:** ~35s
**Description:** ALWAYS mode decision logging. Agent auto-logs tool calls as decisions without explicit tool invocation. Same regression fix applied as 01.
**Output:** Decisions auto-extracted from tool usage, persisted and searchable.
**Triage:** Regression (fixed). Same `agent.learning_machine` property fix.

---

## Summary

| File | Status | Triage | Notes |
|------|--------|--------|-------|
| 01_basic_decision_log.py | PASS | Regression (fixed) | Was `get_learning_machine()`, now `learning_machine` |
| 02_decision_log_always.py | PASS | Regression (fixed) | Same property access fix |

**Totals:** 2 PASS, 0 FAIL, 0 SKIP, 0 ERROR
