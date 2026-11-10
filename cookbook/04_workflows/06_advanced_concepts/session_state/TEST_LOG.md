# TEST_LOG for cookbook/04_workflows/06_advanced_concepts/session_state

Generated: 2026-02-08 16:39:09

### rename_session.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Exited with code 1. AttributeError: 'NoneType' object has no attribute 'session_data'

---

### state_in_condition.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. Completed in 3.2s

---

### state_in_function.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. DEBUG Creating new sync OpenAI client for model gpt-5.6-luna

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

### job_application_tracker.py

**Status:** PASS

**Description:** Executed with `.venv/bin/python` (three sync runs).

**Result:** Extracted three applications via output_schema; the tracker agent saved each through the save_application tool and listed them with the list_applications tool, so the tracker grew 1 -> 2 -> 3 across runs. Re-read in a fresh process returned the same records, confirming SqliteDb persistence.

---
