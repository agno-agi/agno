# Task Mode Cookbook - Test Log

## Test Environment
- Virtual environment: `.venvs/demo/bin/python`
- Date: 2026-02-10

---

### 01_basic_task_mode.py

**Status:** PASS

**Description:** Tests a team in task mode with 3 member agents (Researcher, Writer, Critic). The team leader decomposes a quantum computing briefing request into discrete tasks, assigns them to members, and synthesizes results.

**Result:** Team successfully created 3 research tasks and executed them in parallel via `execute_tasks_parallel`, then created sequential writing and review tasks with proper dependencies. All tasks completed successfully. `mark_all_complete` called with summary. Response time: ~60s.

---

### 02_parallel_tasks.py

**Status:** PASS

**Description:** Tests parallel task execution with 3 analyst agents (Market, Tech, Financial). The team leader creates independent analysis tasks and runs them concurrently.

**Result:** Team created 3 analysis tasks assigned to the correct specialists and executed all 3 in parallel with `execute_tasks_parallel`. After completion, called `mark_all_complete` with a comprehensive summary. Response time: ~35s.

---

### 03_task_mode_with_tools.py

**Status:** PASS

**Description:** Tests task mode with tool-equipped agents. The Web Researcher uses DuckDuckGo tools to search the web, and the Summarizer compiles findings.

**Result:** Team created a web research task (executed by Web Researcher who used DuckDuckGo search), then created a summarization task with dependency on research. Tasks executed in correct dependency order. Final summary covered LLM developments including multimodal capabilities, SFT improvements, scalability, and new metrics. Response time: ~34s.

---

### 04_async_task_mode.py

**Status:** PASS

**Description:** Tests the async API (`arun`) with task mode. A project team (Planner, Executor, Reviewer) creates an onboarding checklist through a plan-execute-review pipeline.

**Result:** Team successfully used async execution path (`OpenAI Async Response`). Created planning, execution, and review tasks with proper dependencies. All tasks completed and `mark_all_complete` called. Demonstrated async task mode works end-to-end.

---

### 05_dependency_chain.py

**Status:** PASS

**Description:** Tests complex dependency chains with 4 agents in a product launch pipeline (Market Researcher -> Product Strategist -> Content Creator -> Launch Coordinator).

**Result:** Team created 4 tasks with chained `depends_on` relationships. Tasks executed sequentially respecting dependencies: market research first, then strategy (depending on research), then content (depending on strategy), then launch plan (depending on all three). Response time: ~83s.

---

### 06_custom_tools.py

**Status:** PASS

**Description:** Tests task mode with agents using custom Python function tools (compound interest calculator, loan payment calculator, risk assessor).

**Result:** Team created 3 tasks (mortgage calc, investment calc, risk assessment) and ran them in parallel via `execute_tasks_parallel`. Member agents correctly invoked their custom tools - Financial Calculator computed $2,275.44/month mortgage and $246,340.14 investment growth; Risk Assessor evaluated MODERATE risk (score 70/100). Financial Advisor then synthesized recommendations. Response time: ~37s.

---

### 07_multi_run_session.py

**Status:** PASS

**Description:** Tests multi-run session persistence. Two sequential runs use the same `session_id`, with the second run referencing findings from the first.

**Result:** Both runs used session ID `task-mode-demo-session`. Run 1 researched microservices vs monolithic architecture. Run 2 successfully provided a concrete recommendation (monolithic for 5-person startup) based on prior analysis. Task state persisted across runs within the same session.

---
