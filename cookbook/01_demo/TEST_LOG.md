# Demo Cookbook Test Log

Last updated: 2026-02-13

## Test Environment

- Database: PostgreSQL with PgVector at localhost:5532
- Python: `.venvs/demo/bin/python`
- Model: gpt-5.2 (OpenAI)

---

## Syntax and Import Validation

### run.py

**Status:** PASS

**Description:** Verified that run.py compiles and all import paths resolve correctly (agents, team, workflows, registry, db).

**Result:** `py_compile` passes. Runtime import requires `PARALLEL_API_KEY` env var (needed by Seek's ParallelTools at instantiation time).

---

### evals/test_cases.py

**Status:** PASS

**Description:** Verified test case module imports cleanly and contains correct agent/team/workflow references.

**Result:** 12 test cases across 7 components: claw, dash, scout, seek, research-team, daily-brief, meeting-prep.

---

### evals/run_evals.py

**Status:** PASS

**Description:** Verified eval runner compiles and `get_component()` maps to all active agents.

**Result:** `py_compile` passes. Removed stale branches for deleted agents (pal, dex, ace, support-team).

---

## Agents

### agents/claw/agent.py

**Status:** PENDING

**Description:** Personal AI assistant with CodingTools, 3-tier governance, input/output guardrails, audit hooks.

**Result:** Not yet tested live. Requires `OPENAI_API_KEY`.

---

### agents/dash/agent.py

**Status:** PENDING

**Description:** Self-learning data agent for F1 racing dataset. SQL tools with semantic model and business context.

**Result:** Not yet tested live. Requires `OPENAI_API_KEY` and loaded F1 data.

---

### agents/scout/agent.py

**Status:** PENDING

**Description:** Enterprise S3 knowledge navigator with intent routing and source registry.

**Result:** Not yet tested live. Requires `OPENAI_API_KEY` and loaded knowledge.

---

### agents/seek/agent.py

**Status:** PENDING

**Description:** Deep research agent with Exa MCP tools and 4-phase methodology.

**Result:** Not yet tested live. Requires `OPENAI_API_KEY` and `PARALLEL_API_KEY`.

---

## Team

### teams/research/team.py

**Status:** PENDING

**Description:** Seek + Scout coordinate mode team for multi-dimensional research.

**Result:** Not yet tested live. Instructions updated to reflect 2-member team.

---

## Workflows

### workflows/daily_brief/workflow.py

**Status:** PENDING

**Description:** 3 parallel gatherers (calendar, email, news) then 1 synthesizer.

**Result:** Not yet tested live.

---

### workflows/meeting_prep/workflow.py

**Status:** PENDING

**Description:** Parse meeting, then 3 parallel researchers, then 1 synthesizer.

**Result:** Not yet tested live.

---

## Summary

| Category | Tests | Passed | Pending |
|----------|-------|--------|---------|
| Syntax/Import | 3 | 3 | 0 |
| Agents | 4 | 0 | 4 |
| Team | 1 | 0 | 1 |
| Workflows | 2 | 0 | 2 |
| **Total** | **10** | **3** | **7** |

## Changes in This Update

- Removed agents: PAL, DEX, ACE (not ready for prime time)
- Removed Support Team (depended on ACE)
- Updated Research Team: removed Dex, now Seek + Scout only
- Removed reasoning variant exports from all agent `__init__.py` files
- Cleaned up evals: 12 test cases (was 16), added CLAW_TESTS
- Cleaned up config.yaml: removed stale quick prompts and reasoning variants
- Rewrote README.md to reflect 4-agent, 1-team, 2-workflow architecture
