# TEST_LOG.md - Demo Cookbook

Test results for `cookbook/01_demo/` — comprehensive demo app with agents, teams, workflows, and evals.

**Test Date:** 2026-02-11 (v2.5 review)
**Environment:** `.venvs/demo/bin/python` (Python 3.12)
**Model:** OpenAI (gpt-5.2, gpt-5.2-mini via registry)
**Database:** PostgreSQL+PgVector (localhost:5532), DuckDB (local files)
**Branch:** `cookbooks/v2.5-testing`

---

## Infrastructure

### db.py

**Status:** PASS

**Description:** Database configuration — PostgresDb connection and Knowledge factory with PgVector hybrid search.

**Result:** Import successful. `get_postgres_db()` returns PostgresDb, `create_knowledge(name, table)` returns Knowledge with PgVector + OpenAIEmbedder.

---

### registry.py

**Status:** PASS

**Description:** Shared Registry for models (OpenAIResponses) and tools (CalculatorTools).

**Result:** Import successful. Registry object created with models and tools registered.

---

### run.py

**Status:** PASS

**Description:** AgentOS entrypoint — registers all 9 agents, 2 teams, 2 workflows.

**Result:** Import successful. 9 agents, 2 teams, 2 workflows registered. Cosmetic tracing warning (`Agent._run` attribute renamed in v2.5, openinference not updated).

---

## Agents

### agents/pal/agent.py

**Status:** SKIP

**Description:** Personal Knowledge Agent — DuckDB + Exa MCP for personal knowledge management.

**Result:** Requires Exa MCP server (MCPTools) to be running externally.

---

### agents/seek/agent.py

**Status:** SKIP

**Description:** Deep Research Agent — Exa MCP + DuckDuckGo for multi-source research.

**Result:** Requires Exa MCP server. Has reasoning variant via `.deep_copy()`.

---

### agents/scout/agent.py

**Status:** SKIP

**Description:** Enterprise Knowledge Navigator — S3 + Exa MCP for internal document search.

**Result:** Requires Exa MCP server and AWS S3 bucket. Has reasoning variant.

---

### agents/dash/agent.py

**Status:** SKIP

**Description:** Self-Learning Data Agent — SQL + PostgreSQL with Formula 1 dataset.

**Result:** Requires PostgreSQL with F1 data loaded and optional Exa MCP. Has reasoning variant.

---

### agents/dex/agent.py

**Status:** SKIP

**Description:** Relationship Intelligence Agent — DuckDB + Exa MCP for people/interaction tracking.

**Result:** Requires Exa MCP server.

---

### agents/ace/agent.py

**Status:** SKIP

**Description:** Response & Drafting Agent — Exa MCP for context research, learns communication style.

**Result:** Requires Exa MCP server.

---

## Teams

### teams/research/team.py

**Status:** SKIP

**Description:** Multi-agent research coordinator — Seek + Scout + Dex collaboration.

**Result:** Depends on agents that require Exa MCP server.

---

### teams/support/team.py

**Status:** SKIP

**Description:** Question routing team — Ace + Scout + Dash with `respond_directly=True`.

**Result:** Depends on agents that require Exa MCP server.

---

## Workflows

### workflows/daily_brief/workflow.py

**Status:** PASS

**Description:** Morning briefing workflow — Parallel gather (calendar, email, news) then synthesize. Uses mock tools for calendar/email, DuckDuckGo for news.

**Result:** Exited `0` in ~47s. Produced comprehensive daily brief with calendar highlights, inbox priorities, and industry news. Parallel execution of 3 gather agents + sequential synthesis worked correctly.

---

### workflows/meeting_prep/workflow.py

**Status:** PASS

**Description:** Meeting preparation workflow — Parse meeting details, parallel research (attendees, context, external), then synthesize prep materials. Uses mock tools.

**Result:** Exited `0`. Produced detailed meeting prep with attendee backgrounds, context analysis, talking points, and decision framework. Three-stage pipeline (parse -> parallel research -> synthesize) executed correctly.

---

## Evals

### evals/run_evals.py

**Status:** SKIP

**Description:** Evaluation runner — 16 test cases across all agents, teams, and workflows.

**Result:** Cannot run without Exa MCP server (most test cases target agents that depend on it). Framework imports and test case definitions verified via run.py import.

---

### evals/test_cases.py

**Status:** PASS (import only)

**Description:** Test case definitions — 16 cases across 10 components.

**Result:** Imported successfully via run.py. TestCase dataclass, AGENT_TESTS, ALL_TEST_CASES, CATEGORIES all defined correctly.

---

## Summary

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| Infrastructure | `db.py` | PASS | |
| Infrastructure | `registry.py` | PASS | |
| Infrastructure | `run.py` | PASS | Cosmetic trace warning |
| Agent | `agents/pal/agent.py` | SKIP | Needs Exa MCP |
| Agent | `agents/seek/agent.py` | SKIP | Needs Exa MCP |
| Agent | `agents/scout/agent.py` | SKIP | Needs Exa MCP + S3 |
| Agent | `agents/dash/agent.py` | SKIP | Needs F1 data + Exa MCP |
| Agent | `agents/dex/agent.py` | SKIP | Needs Exa MCP |
| Agent | `agents/ace/agent.py` | SKIP | Needs Exa MCP |
| Team | `teams/research/team.py` | SKIP | Depends on MCP agents |
| Team | `teams/support/team.py` | SKIP | Depends on MCP agents |
| Workflow | `workflows/daily_brief/workflow.py` | PASS | ~47s, mock tools |
| Workflow | `workflows/meeting_prep/workflow.py` | PASS | Mock tools |
| Evals | `evals/run_evals.py` | SKIP | Needs MCP agents |
| Evals | `evals/test_cases.py` | PASS | Import only |

**Overall:** 6 PASS, 0 FAIL, 9 SKIP

**SKIP Reason:** All 6 agents use MCPTools with Exa MCP server, which must be running externally. Teams depend on these agents. Evals test these agents. The workflows are self-contained with mock tools and pass cleanly.
