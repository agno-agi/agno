# REVIEW_LOG.md - Demo Cookbook

Code review findings for `cookbook/01_demo/` — three-layer audit.

**Review Date:** 2026-02-11
**Reviewer:** Codex GPT-5.3 + Opus 4.6 cross-review
**Branch:** `cookbooks/v2.5-testing`
**Scope:** Framework code (LearningMachine, MCPTools, Parallel, Team, Agent.deep_copy) + all demo cookbook files

---

## [FRAMEWORK] Framework Bugs & Regressions

### [HIGH] Parallel executor crash with zero steps

**Location:** `libs/agno/agno/workflow/parallel.py:339`

`ThreadPoolExecutor(max_workers=len(self.steps))` crashes with `ValueError` when `self.steps` is empty (max_workers=0 is invalid). No guard for empty step list.

**Impact:** Any `Parallel()` with zero steps crashes. Low likelihood in practice but no defensive check.

---

### [HIGH] Parallel branches share mutable session_state

**Location:** `libs/agno/agno/workflow/parallel.py:293`

Parallel branches share the same `run_context.session_state` dict reference. Concurrent writes from different threads can cause race conditions or data corruption.

**Impact:** Affects `daily_brief` and `meeting_prep` workflows if parallel agents modify session state simultaneously. May cause intermittent data corruption.

---

### [HIGH] MCPTools.__aexit__ doesn't clean _run_sessions

**Location:** `libs/agno/agno/tools/mcp/mcp.py:538`

`MCPTools.__aexit__()` closes the main client but does not clean up per-run sessions (`_run_sessions` dict). Sessions created between `__aenter__` and `__aexit__` leak their transport resources.

**Impact:** Affects all 6 agents (pal, seek, scout, dash, dex, ace) that use MCPTools. Resources leak on context manager exit.

---

### [HIGH] respond_directly mutates member output_schema

**Location:** `libs/agno/agno/team/_default_tools.py:374`

In the `respond_directly` flow, the framework temporarily sets `member.output_schema = None` to prevent structured output interference, but this mutates the shared agent instance. If the team is used concurrently or the agent is reused, its `output_schema` is permanently cleared.

**Impact:** Affects support team (`respond_directly=True`). If agents have `output_schema`, it gets silently cleared on first use.

---

### [MEDIUM] deep_copy() shares LearningMachine instance

**Location:** `libs/agno/agno/agent/_utils.py:211`

`Agent.deep_copy()` intentionally shares the `learning` (LearningMachine) instance between original and copy. This means the reasoning variant (e.g., `reasoning_dash`) shares learning state with the base agent, which may cause unexpected cross-contamination.

**Impact:** Affects all reasoning variants (reasoning_dash, reasoning_scout, reasoning_seek). Shared learning state is likely intentional but undocumented.

---

### [MEDIUM] LearningMachine silent type coercion

**Location:** `libs/agno/agno/learn/machine.py:202`

LearningMachine accepts non-config truthy values (e.g., a plain dict or string) for config parameters and silently coerces them, rather than raising a TypeError. This can mask configuration bugs.

---

### [MEDIUM] custom_stores bypass protocol validation

**Location:** `libs/agno/agno/learn/machine.py:158`

`custom_stores` are inserted without validating they implement the `LearningStore` protocol. Invalid stores will fail silently or crash at runtime during learning operations.

---

## [QUALITY] Teaching Clarity

### [MEDIUM] Exa credential defaults to empty string

**Location:** `cookbook/01_demo/agents/pal/agent.py:40` (and similar in all 6 agents)

`EXA_API_KEY` defaults to `""` via `getenv("EXA_API_KEY", "")`. This allows agent creation to succeed but MCP connection will fail at runtime with a confusing error. Should either fail fast or document the requirement.

---

### [MEDIUM] Evals use non-deterministic substring matching

**Location:** `cookbook/01_demo/evals/run_evals.py:167`

Evaluations check for expected substrings in LLM responses (`check_strings`). Since LLM output is non-deterministic, this can produce flaky results. The eval framework should acknowledge this limitation or use more robust checking.

---

### [LOW] Hard-coded mock dates

**Location:** `cookbook/01_demo/workflows/daily_brief/workflow.py:36`, `meeting_prep/workflow.py:38`

Mock calendar/email data uses hard-coded dates (February 6). This makes the workflow output look stale. Using `datetime.now()` or a note explaining the mock data would improve clarity.

---

## [COMPAT] v2.5 Compatibility

### [LOW] Import style preference (not breaking)

**Location:** `cookbook/01_demo/teams/research/team.py:17`, `teams/support/team.py:17`

Uses `from agno.team.team import Team` instead of `from agno.team import Team`. Both work — the module-level import is valid and not deprecated. Similarly, `from agno.workflow.parallel import Parallel` works alongside `from agno.workflow import Parallel`.

**Status:** Informational only. No fix needed.

---

### Cross-validated: respond_directly is NOT deprecated

Codex flagged `respond_directly=True` as legacy, but cross-validation confirms it's still a current Team parameter. The TeamMode enum is a separate concept for team execution mode (coordinate/route/broadcast/tasks), not a replacement for `respond_directly`.

**Status:** No issue. Codex finding was a false positive.

---

### Cross-validated: Import-time instantiation is standard

Codex flagged module-level agent creation as non-v2.5, but this is standard cookbook pattern used across the codebase.

**Status:** No issue. Codex finding was a false positive.

---

## Summary

| Layer | HIGH | MEDIUM | LOW | False Positive |
|-------|------|--------|-----|----------------|
| FRAMEWORK | 4 | 3 | 0 | 0 |
| QUALITY | 0 | 2 | 1 | 0 |
| COMPAT | 0 | 0 | 1 | 2 |
| **Total** | **4** | **5** | **2** | **2** |

**Key takeaway:** Framework-level issues are real and worth tracking (especially Parallel race conditions and MCPTools cleanup). Quality issues are minor. No actual v2.5 compatibility breaks — all imports and APIs are valid.
