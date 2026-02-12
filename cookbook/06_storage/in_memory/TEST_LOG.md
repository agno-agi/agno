# Test Log: in_memory

**Date:** 2026-02-11
**Environment:** `.venvs/demo/bin/python`
**Model:** gpt-4o, gpt-4o-mini

---

## Runtime Results

### in_memory_storage_for_agent.py

**Status:** PASS
**Time:** ~8s
**Description:** InMemoryDb for single agent. Agent responds to cooking recipe request with session context.
**Triage:** n/a

---

### in_memory_storage_for_team.py

**Status:** PASS
**Time:** ~59s
**Description:** InMemoryDb for team with HackerNews + WebSearch agents. Returns structured Article output via output_schema.
**Triage:** n/a

---

### in_memory_storage_for_workflow.py

**Status:** PASS
**Time:** ~88s
**Description:** InMemoryDb for workflow with Research Team (2 agents) + Content Planner. 2-step workflow produces 4-week content plan.
**Triage:** n/a

---

## Summary

| File | Status | Notes |
|------|--------|-------|
| `in_memory_storage_for_agent.py` | PASS | ~8s |
| `in_memory_storage_for_team.py` | PASS | ~59s, team + output_schema |
| `in_memory_storage_for_workflow.py` | PASS | ~88s, workflow + team |

**Totals:** 3 PASS, 0 FAIL, 0 SKIP
