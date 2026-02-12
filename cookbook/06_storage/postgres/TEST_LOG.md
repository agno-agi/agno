# Test Log: postgres

**Date:** 2026-02-11
**Environment:** `.venvs/demo/bin/python`
**Model:** gpt-4o, gpt-4o-mini
**Services:** pgvector (port 5532)

---

## Runtime Results

### postgres_for_agent.py

**Status:** PASS
**Time:** ~10s
**Description:** PostgresDb for agent with WebSearchTools. Agent answers questions and persists history.
**Triage:** n/a

---

### postgres_for_team.py

**Status:** PASS
**Time:** ~51s
**Description:** PostgresDb for team with HackerNews + WebSearch. Returns structured Article output via output_schema.
**Triage:** n/a

---

### postgres_for_workflow.py

**Status:** PASS
**Time:** ~69s
**Description:** PostgresDb for workflow with Research Team + Content Planner. 2-step workflow produces content plan.
**Triage:** n/a

---

## Summary

| File | Status | Notes |
|------|--------|-------|
| `postgres_for_agent.py` | PASS | ~10s |
| `postgres_for_team.py` | PASS | ~51s |
| `postgres_for_workflow.py` | PASS | ~69s |

**Totals:** 3 PASS, 0 FAIL, 0 SKIP
