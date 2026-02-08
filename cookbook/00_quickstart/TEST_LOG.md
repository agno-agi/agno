# TEST_LOG.md - Quick Start Cookbook

Test results for `cookbook/00_quickstart/` examples.

**Test Date:** 2026-02-08  
**Environment:** `.venvs/demo/bin/python` with `direnv` exports loaded  
**Database:** `pgvector` container running (`pgvector`, port `5532`)  
**Execution Artifacts:** `.context/quickstart_results.json`, `.context/quickstart_logs/*.log`

---

## Structure Validation

### check_cookbook_pattern.py

**Status:** PASS

**Description:** Validates cookbook structure and formatting pattern for quickstart examples.

**Result:** `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/00_quickstart` reported `Checked 13 file(s) ... Violations: 0`.

---

### style_guide_compliance_scan

**Status:** PASS

**Description:** Validates module docstring with `=====` underline, section banners, import placement, `if __name__ == "__main__":` gate, and no emoji characters.

**Result:** Custom style scan over all 13 runnable files reported `STYLE_OK` with no issues.

---

## Runtime Validation

### agent_search_over_knowledge.py

**Status:** PASS

**Description:** Validates knowledge-base loading/search and response generation.

**Result:** Exited `0` in 8.74s; completed the knowledge-search flow.

---

### agent_with_guardrails.py

**Status:** PASS

**Description:** Validates guardrails for PII, prompt-injection, and spam-like input.

**Result:** Exited `0` in 13.18s; guardrail validation errors were emitted as expected for blocked inputs and valid input was processed.

---

### agent_with_memory.py

**Status:** PASS

**Description:** Validates memory extraction and recall behavior.

**Result:** Exited `0` in 25.43s; memory operations completed successfully.

---

### agent_with_state_management.py

**Status:** PASS

**Description:** Validates stateful tool interactions and session watchlist behavior.

**Result:** Exited `0` in 15.95s; session state flow completed.

---

### agent_with_storage.py

**Status:** PASS

**Description:** Validates persisted session storage and response generation.

**Result:** Exited `0` in 26.65s; completed end-to-end persisted-session flow.

---

### agent_with_structured_output.py

**Status:** PASS

**Description:** Validates schema-constrained output generation.

**Result:** Exited `0` in 14.34s; structured output returned. Non-fatal warning observed about non-text response parts (`function_call` parts concatenated to text).

---

### agent_with_tools.py

**Status:** PASS

**Description:** Validates tool-using agent behavior with market-data tools.

**Result:** Exited `0` in 10.52s; tool-driven analysis flow completed.

---

### agent_with_typed_input_output.py

**Status:** PASS

**Description:** Validates typed request input and typed response output flow.

**Result:** Exited `0` in 18.10s; typed I/O flow completed. Non-fatal warning observed about non-text response parts (`function_call` parts concatenated to text).

---

### custom_tool_for_self_learning.py

**Status:** PASS

**Description:** Validates custom learning tool save/search behavior.

**Result:** Exited `0` in 24.48s; learning retrieval worked.

---

### human_in_the_loop.py

**Status:** PASS

**Description:** Validates confirmation-required tool execution.

**Result:** Exited `0` in 10.79s; confirmation path exercised with stdin `y` and execution completed.

---

### multi_agent_team.py

**Status:** PASS

**Description:** Validates team collaboration, delegation, and synthesis flow.

**Result:** Exited `0` in 94.08s; multi-agent team run completed successfully in this environment.

---

### run.py

**Status:** PASS

**Description:** Startup-only validation for long-running AgentOS server.

**Result:** Ran for 25s and intentionally timed out (`exit 124`) after startup checks; observed `Uvicorn running on` and `Application startup complete`.

---

### sequential_workflow.py

**Status:** PASS

**Description:** Validates sequential multi-step workflow execution.

**Result:** Exited `0` in 37.27s; workflow completed all steps.

---

## Summary

| File | Status | Notes |
|------|--------|-------|
| `agent_search_over_knowledge.py` | PASS | Exited `0`; knowledge-search flow completed |
| `agent_with_guardrails.py` | PASS | Exited `0`; guardrails blocked invalid inputs and allowed valid input |
| `agent_with_memory.py` | PASS | Exited `0`; memory flow completed |
| `agent_with_state_management.py` | PASS | Exited `0`; session state flow completed |
| `agent_with_storage.py` | PASS | Exited `0`; persisted-session response completed |
| `agent_with_structured_output.py` | PASS | Exited `0`; structured output returned with non-fatal non-text-parts warning |
| `agent_with_tools.py` | PASS | Exited `0`; tool-driven analysis completed |
| `agent_with_typed_input_output.py` | PASS | Exited `0`; typed I/O completed with non-fatal non-text-parts warning |
| `custom_tool_for_self_learning.py` | PASS | Exited `0`; learning save/search completed |
| `human_in_the_loop.py` | PASS | Exited `0`; approval path completed with stdin `y` |
| `multi_agent_team.py` | PASS | Exited `0`; team collaboration flow completed |
| `run.py` | PASS | Startup markers observed; intentionally timed out after 25s |
| `sequential_workflow.py` | PASS | Exited `0`; sequential workflow completed |

**Overall:** 13 PASS, 0 FAIL
