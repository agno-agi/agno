# Test Log: hooks

> Updated: 2026-02-11

### stream_hook.py

**Status:** PASS

**Description:** Demonstrates post-hook notification after streamed team response using `RunContext.metadata` to pass user email. Uses `YFinanceTools` to generate a financial report for AAPL.

**Result:** Completed successfully in ~14s. Post-hook fired after streaming, correctly accessed `run_context.metadata["email"]` and sent mock email notification.

---

### pre_hook_input.py

**Status:** FAIL (timeout)

**Description:** Demonstrates complex pre-hooks with inner Agent calls for input validation (`comprehensive_team_input_validation`) and transformation (`transform_team_input`). 5 test cases across 2 teams.

**Result:** Timed out at 180s. The validation pre-hook creates an inner Agent (gpt-5.2) with `output_schema` for structured validation, causing multiple nested LLM roundtrips per test case. First test case (complex software project) never completed within timeout. Prior run (2026-02-08) also timed out — this is structurally too slow for reasonable cookbook execution.

---

### post_hook_output.py

**Status:** PASS

**Description:** Demonstrates 6 types of post-hooks: quality validation (inner Agent), simple coordination check, metadata injection, collaboration summary, and structured response formatting (inner Agent). 6 test cases across 5 different teams.

**Result:** All 6 test cases completed successfully. Validation hooks, metadata injection, and structured formatting all worked correctly. Async and sync mixed usage functioned. Prior run (2026-02-08) had timed out — this run completed.

---
