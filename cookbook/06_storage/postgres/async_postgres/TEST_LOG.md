# Test Log: async_postgres

**Date:** 2026-02-11
**Environment:** `.venvs/demo/bin/python`
**Model:** gpt-4o, gpt-4o-mini
**Services:** pgvector (port 5532)

---

## Runtime Results

### async_postgres_for_agent.py

**Status:** PASS
**Time:** ~10s
**Description:** AsyncPostgresDb for agent. Context preserved across two async calls (Canada population then national anthem).
**Triage:** regression (fixed in v25-fixes)
**Fix:** Double `asyncio.run()` wrapped into single `async def main()`.
**Re-verified:** 2026-02-14 — async refactor confirmed working, web search tool called, session context maintained across turns.

---

### async_postgres_for_team.py

**Status:** PASS
**Time:** ~50s
**Description:** AsyncPostgresDb for team with HackerNews + WebSearch. Returns structured Article output.
**Triage:** n/a

---

### async_postgres_for_workflow.py

**Status:** PASS
**Time:** ~61s
**Description:** AsyncPostgresDb for workflow with Research Team + Content Planner. 2-step async workflow produces content plan.
**Triage:** n/a

---

## Summary

| File | Status | Notes |
|------|--------|-------|
| `async_postgres_for_agent.py` | PASS | regression (fixed), double asyncio.run |
| `async_postgres_for_team.py` | PASS | ~50s |
| `async_postgres_for_workflow.py` | PASS | ~61s |

**Totals:** 3 PASS, 0 FAIL, 0 SKIP
