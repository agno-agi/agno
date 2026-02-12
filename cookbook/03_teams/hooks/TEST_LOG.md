# Test Log: hooks

> Updated: 2026-02-12

### stream_hook.py

**Status:** PASS

**Description:** Demonstrates post-hook notification after streamed team response using `RunContext.metadata` to pass user email. Uses `YFinanceTools` to generate a financial report for AAPL.

**Result:** Completed successfully. Post-hook fired after streaming, correctly accessed `run_context.metadata["email"]` and sent mock email notification.

---

### pre_hook_input.py

**Status:** FAIL (timeout)

**Description:** Demonstrates complex pre-hooks with inner Agent calls for input validation and transformation. 5 test cases across 2 teams.

**Result:** Timed out at 120s. The validation pre-hook creates an inner Agent with `output_schema` for structured validation, causing multiple nested LLM roundtrips per test case. Consistently too slow for cookbook execution.

---

### post_hook_output.py

**Status:** FAIL (timeout)

**Description:** Demonstrates 6 types of post-hooks: quality validation (inner Agent), simple coordination check, metadata injection, collaboration summary, and structured response formatting.

**Result:** Timed out at 120s. Test 3 was still running when timeout hit. Multiple nested LLM roundtrips for post-hook validation are too slow within 120s timeout.

---
