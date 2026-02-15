# Test Log: workflow

### basic_workflow.py

**Status:** PASS

**Description:** Simple linear workflow with 2 agents (HackerNews scraper + ContentPlanner). Uses SqliteDb, AgentOS server.

**Result:** Import and app construction OK.

---

### basic_chat_workflow_agent.py

**Status:** PASS

**Description:** Workflow with WorkflowAgent orchestrator, Condition for conditional editing, custom evaluator function. Uses PostgresDb.

**Result:** Import and app construction OK.

---

### basic_workflow_team.py

**Status:** PASS

**Description:** Workflow with a Team as one step (Research Team with 2 members). Uses SqliteDb.

**Result:** Import and app construction OK.

---

### customer_research_workflow_parallel.py

**Status:** PASS

**Description:** Complex parallel workflow with custom async executors, session state tracking, structured Pydantic output schemas. Multiple research phases with Parallel steps.

**Result:** Import and app construction OK.

---

### workflow_with_conditional.py

**Status:** PASS

**Description:** Linear workflow with Condition block for fact-checking (Research -> Summarize -> Condition -> Write). Uses WebSearchTools.

**Result:** Import and app construction OK.

---

### workflow_with_custom_function.py

**Status:** PASS

**Description:** Steps with custom `executor=` functions instead of agents. Both sync and async streaming executors demonstrated.

**Result:** Import and app construction OK.

---

### workflow_with_custom_function_updating_session_state.py

**Status:** PASS

**Description:** Custom executor that uses RunContext to read/update session_state across workflow runs.

**Result:** Import and app construction OK.

---

### workflow_with_history.py

**Status:** PASS

**Description:** Meal planning workflow with `add_workflow_history_to_steps=True` and `num_history_runs=3`. Includes custom analyzer step.

**Result:** Import and app construction OK.

---

### workflow_with_input_schema.py

**Status:** PASS

**Description:** Workflow with Pydantic `input_schema=ResearchTopic` for input validation.

**Result:** Import and app construction OK.

---

### workflow_with_loop.py

**Status:** PASS

**Description:** Loop wrapping steps with `end_condition` evaluator and `max_iterations=3`. End condition checks `List[StepOutput]`.

**Result:** Import and app construction OK.

---

### workflow_with_nested_steps.py

**Status:** PASS

**Description:** Advanced nesting: Loop inside Router for complex control flow. Uses PostgresDb.

**Result:** Import and app construction OK.

---

### workflow_with_parallel.py

**Status:** PASS

**Description:** Parallel execution of 3 research agents concurrently using `Parallel(step1, step2, step3)`.

**Result:** Import and app construction OK.

---

### workflow_with_parallel_and_custom_function_step_stream.py

**Status:** PASS

**Description:** Combines Parallel with custom async streaming executors yielding WorkflowRunOutputEvent objects.

**Result:** Import and app construction OK.

---

### workflow_with_router.py

**Status:** PASS

**Description:** Router for conditional step selection. Selector function detects tech keywords and routes to appropriate research path.

**Result:** Import and app construction OK.

---

### workflow_with_steps.py

**Status:** PASS

**Description:** Steps container for logical grouping of multiple steps into a named sequence (without parallelization).

**Result:** Import and app construction OK.

---
