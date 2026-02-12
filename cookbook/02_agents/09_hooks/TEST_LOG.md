# TEST LOG

Generated: 2026-02-10 UTC

Pattern Check: Checked 4 file(s) in cookbook/02_agents/hooks. Violations: 0

### post_hook_output.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### pre_hook_input.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### session_state_hooks.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### stream_hook.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### tool_hooks.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---


---

## v2.5 Audit Results

# TEST LOG

Generated: 2026-02-11 UTC (v2.5 review)

Pattern Check: Checked 4 file(s) in cookbook/02_agents/hooks. Violations: 0

### session_state_hooks.py

**Status:** PASS

**Description:** Pre-hook to track conversation topics in session state. Creates a classifier Agent inside the hook to categorize topics, then appends to session_state.

**Result:** Completed successfully. Topics tracked across 2 runs. Session state showed accumulated topic list: ['AI agents', 'Agno', ...].

---

### pre_hook_input.py

**Status:** PASS

**Description:** Pre-hook for comprehensive input validation using AI. Validates relevance, detail sufficiency, and safety via CheckTrigger. Tests 3 scenarios: valid, vague, off-topic.

**Result:** Completed successfully. Test 1 (valid) passed through. Test 2 (vague "invest money") correctly raised InputCheckError. Test 3 (off-topic "pizza recipe") correctly raised OFF_TOPIC error.

---

### stream_hook.py

**Status:** PASS

**Description:** Post-hook to send email notification after streaming response. Uses YFinanceTools for stock analysis with async post_hook.

**Result:** Completed successfully. Agent analyzed AAPL stock with streaming output. Post-hook email notification fired.

---

### post_hook_output.py

**Status:** PASS

**Description:** Post-hook for output quality/safety validation. Tests 3 scenarios: valid long response, too-brief response, and simple response.

**Result:** Completed successfully. Test 1 produced detailed response. Test 2 ("What is the capital of France?") correctly raised OutputCheckError for too-brief. Test 3 passed simple validation.

---
