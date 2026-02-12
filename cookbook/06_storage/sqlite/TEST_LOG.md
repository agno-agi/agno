# Test Log: sqlite

**Date:** 2026-02-11
**Environment:** `.venvs/demo/bin/python`
**Model:** gpt-4o, gpt-4o-mini

---

## Runtime Results

### sqlite_for_agent.py

**Status:** PASS
**Time:** ~10s
**Description:** SqliteDb for agent with WebSearchTools. Agent answers questions and persists history across calls.
**Triage:** n/a

---

### sqlite_for_team.py

**Status:** PASS
**Time:** ~60s
**Description:** SqliteDb for team with HackerNews + WebSearch. Returns structured Article output via output_schema.
**Triage:** n/a

---

### sqlite_for_workflow.py

**Status:** FAIL (timeout)
**Time:** >120s (2 attempts)
**Description:** SqliteDb for workflow with Research Team + Content Planner. Workflow header prints but execution exceeds 120s timeout on both attempts.
**Triage:** timeout — workflow with team + HackerNews + WebSearch + content planning is too API-heavy for 120s. The same workflow pattern passes with InMemoryDb (~88s) and async SQLite (~59s), suggesting intermittent API latency.

---

## Summary

| File | Status | Notes |
|------|--------|-------|
| `sqlite_for_agent.py` | PASS | ~10s |
| `sqlite_for_team.py` | PASS | ~60s |
| `sqlite_for_workflow.py` | FAIL | timeout >120s, 2 attempts |

**Totals:** 2 PASS, 1 FAIL, 0 SKIP
