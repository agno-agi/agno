# Test Log: async_sqlite

**Date:** 2026-02-11
**Environment:** `.venvs/demo/bin/python`
**Model:** gpt-4o, gpt-4o-mini

---

## Runtime Results

### async_sqlite_for_agent.py

**Status:** PASS
**Time:** ~10s
**Description:** AsyncSqliteDb for agent. Context preserved across two async calls (Canada population then national anthem).
**Triage:** regression (fixed in v25-fixes)
**Fix:** Double `asyncio.run()` wrapped into single `async def main()`.
**Re-verified:** 2026-02-14 — async refactor confirmed working, web search tool called, session context maintained.

---

### async_sqlite_for_team.py

**Status:** PASS
**Time:** ~40s
**Description:** AsyncSqliteDb for team with HackerNews + WebSearch. Returns structured Article output.
**Triage:** n/a

---

### async_sqlite_for_workflow.py

**Status:** PASS
**Time:** ~59s
**Description:** AsyncSqliteDb for workflow with Research Team + Content Planner. 2-step async workflow produces content plan.
**Triage:** n/a

---

## Summary

| File | Status | Notes |
|------|--------|-------|
| `async_sqlite_for_agent.py` | PASS | regression (fixed), double asyncio.run |
| `async_sqlite_for_team.py` | PASS | ~40s |
| `async_sqlite_for_workflow.py` | PASS | ~59s |

**Totals:** 3 PASS, 0 FAIL, 0 SKIP
