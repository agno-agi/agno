# TEST_LOG for cookbook/04_workflows/06_advanced_concepts/session_state

Generated: 2026-02-08 16:39:09

### rename_session.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 120s).

**Result:** Completed successfully. Workflow ran research team + content planner, generated article, then renamed session. SqliteDb added, method renamed from `rename_session` to correct API.
**Re-verified:** 2026-02-14 — v25-fixes applied (SqliteDb + method rename), runs cleanly in ~29s.

---

### state_in_condition.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. Completed in 3.2s

---

### state_in_function.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. DEBUG Creating new sync OpenAI client for model gpt-4o

---

### state_in_router.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. - Useful large-scale quantum computing likely requires **quantum error

---

### state_with_agent.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. Final workflow session state: {'shopping_list': []}

---

### state_with_team.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. DEBUG [ERROR] Step 'Write Tests' not found in the list

---
