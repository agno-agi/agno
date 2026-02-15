# TEST_LOG.md - 93 Components Cookbook

Test results for `cookbook/93_components/` examples.

**Test Date:** 2026-02-11
**Environment:** `.venvs/demo/bin/python`
**Branch:** `cookbooks/v2.5-testing`

---

### save_agent.py

**Status:** PASS

**Description:** Creates an agent with OpenAIChat model and saves it to PostgreSQL.

**Result:** Saved agent as version 1. No errors.

---

### get_agent.py

**Status:** PASS

**Description:** Loads a previously saved agent by ID and runs a query.

**Result:** Agent loaded successfully, responded to "How many people live in Canada?" with correct answer. 18.2s response time.

---

### save_team.py

**Status:** PASS

**Description:** Creates a team with researcher and writer agents, saves to PostgreSQL.

**Result:** Saved team as version 1. No errors.

---

### get_team.py

**Status:** PASS

**Description:** Loads a previously saved team by ID and runs it with streaming.

**Result:** Team loaded, delegated tasks to researcher-agent and writer-agent, produced article about internet history. 70s response time.

---

### save_workflow.py

**Status:** PASS

**Description:** Creates a workflow with two sequential steps (research + content planning), saves to PostgreSQL.

**Result:** Saved workflow as version 1. No errors.

---

### get_workflow.py

**Status:** PASS

**Description:** Loads a previously saved workflow by ID and runs it.

**Result:** Workflow loaded (2 steps), executed both steps (Research Step + Content Planning Step) on "AI trends in 2024". 25.9s total.

---

### registry.py

**Status:** PASS

**Description:** Creates a Registry with tools, models, schemas, and saves an agent with output_schema.

**Result:** Ran without errors. Agent saved. Note: the get_agent_by_id call is commented out (by design).

---

### agent_os_registry.py

**Status:** SKIP

**Description:** Configures AgentOS with Registry and serves a FastAPI app.

**Result:** Skipped — starts a web server (not suitable for non-interactive testing).

---

### demo.py

**Status:** SKIP

**Description:** Full AgentOS demo with Registry including tools, functions, schemas, models, and vector DBs.

**Result:** Skipped — starts a web server (not suitable for non-interactive testing).

---

### workflows/save_conditional_steps.py

**Status:** PASS

**Description:** Creates a workflow with Condition step (evaluator function), saves and loads back with Registry.

**Result:** Saved and loaded successfully. 3 steps confirmed. Condition + Registry round-trip works.

---

### workflows/save_parallel_steps.py

**Status:** PASS

**Description:** Creates a workflow with Parallel steps (HackerNews + Web research in parallel), saves and loads.

**Result:** Saved and loaded successfully. 3 steps confirmed. Parallel step serialization works.

---

### workflows/save_custom_steps.py

**Status:** PASS

**Description:** Creates a workflow with custom executor function step, saves and loads back with Registry.

**Result:** Saved and loaded successfully. 2 steps confirmed. Custom executor + Registry round-trip works.

---

### workflows/save_loop_steps.py

**Status:** PASS

**Description:** Creates a workflow with Loop step (end_condition function, max 3 iterations), saves and loads with Registry.

**Result:** Saved and loaded successfully. 2 steps confirmed. Loop + end_condition + Registry round-trip works.

---

### workflows/save_router_steps.py

**Status:** PASS

**Description:** Creates a workflow with Router step (selector function with choices), saves and loads with Registry.

**Result:** Saved and loaded successfully. 2 steps confirmed. Router + selector + Registry round-trip works.

---

## Summary

| Status | Count |
|--------|-------|
| PASS   | 12    |
| SKIP   | 2     |
| FAIL   | 0     |
| **Total** | **14** |
