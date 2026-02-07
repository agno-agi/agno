# TEST_LOG.md - Quick Start Cookbook

Test results for `cookbook/00_quickstart/` examples.

**Test Date:** 2026-02-07  
**Environment:** `direnv exec . .venvs/demo/bin/python`  
**Database:** `pgvector` container was already running (`pgvector`, port `5532`)  
**Logs:** `.context/quickstart_test_logs/`

---

## Structure Validation

### check_cookbook_pattern.py

**Status:** PASS

**Description:** Validates cookbook structure and formatting pattern for quickstart examples.

**Result:** `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/00_quickstart` reported `Violations: 0`.

---

## Runtime Validation

### agent_search_over_knowledge.py

**Status:** PASS

**Description:** Validates knowledge search flow with retrieval and response generation.

**Result:** Exited `0` and completed end-to-end run.

---

### agent_with_guardrails.py

**Status:** PASS

**Description:** Validates built-in/custom guardrails behavior during agent execution.

**Result:** Exited `0` and completed run.

---

### agent_with_memory.py

**Status:** PASS

**Description:** Validates memory extraction/storage/retrieval flow.

**Result:** Exited `0` and completed run.

---

### agent_with_state_management.py

**Status:** PASS

**Description:** Validates stateful tools and session state transitions.

**Result:** Exited `0` and completed run.

---

### agent_with_storage.py

**Status:** PASS

**Description:** Validates persisted session storage behavior.

**Result:** Exited `0` and completed run.

---

### agent_with_structured_output.py

**Status:** PASS

**Description:** Validates schema-constrained structured output generation.

**Result:** Exited `0` and completed run.

---

### agent_with_tools.py

**Status:** PASS

**Description:** Validates tool-using agent flow with market-data tools.

**Result:** Exited `0` and completed run.

---

### agent_with_typed_input_output.py

**Status:** PASS

**Description:** Validates typed request input and typed response output flow.

**Result:** Exited `0` and completed run.

---

### custom_tool_for_self_learning.py

**Status:** PASS

**Description:** Validates custom learning tool behavior and persistence.

**Result:** Exited `0` and completed run.

---

### human_in_the_loop.py

**Status:** FAIL

**Description:** Validates confirmation-required tool execution path.

**Result:** Reached `Confirmation Required` prompt, then failed in non-interactive execution with `EOFError` at `Prompt.ask` (`cookbook/00_quickstart/human_in_the_loop.py:184`).

---

### multi_agent_team.py

**Status:** PASS

**Description:** Validates multi-agent team collaboration and synthesis flow.

**Result:** Exited `0` and completed run.

---

### run.py

**Status:** PASS

**Description:** Startup-only validation for long-running AgentOS app server.

**Result:** Process timed out intentionally after startup markers were observed: `Uvicorn running`, `Started server process`, `Application startup complete`.

---

### sequential_workflow.py

**Status:** PASS

**Description:** Validates sequential multi-step workflow execution.

**Result:** Exited `0` and completed run.

---

## Summary

| File | Status | Notes |
|------|--------|-------|
| `agent_search_over_knowledge.py` | PASS | Exited `0` |
| `agent_with_guardrails.py` | PASS | Exited `0` |
| `agent_with_memory.py` | PASS | Exited `0` |
| `agent_with_state_management.py` | PASS | Exited `0` |
| `agent_with_storage.py` | PASS | Exited `0` |
| `agent_with_structured_output.py` | PASS | Exited `0` |
| `agent_with_tools.py` | PASS | Exited `0` |
| `agent_with_typed_input_output.py` | PASS | Exited `0` |
| `custom_tool_for_self_learning.py` | PASS | Exited `0` |
| `human_in_the_loop.py` | FAIL | `EOFError` on interactive confirmation prompt |
| `multi_agent_team.py` | PASS | Exited `0` |
| `run.py` | PASS | Startup validated, timed out by design |
| `sequential_workflow.py` | PASS | Exited `0` |

**Overall:** 12 PASS, 1 FAIL
