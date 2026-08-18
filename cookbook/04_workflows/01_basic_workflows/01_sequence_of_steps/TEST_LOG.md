# Test Log: 04_workflows/01_basic_workflows/01_sequence_of_steps


## Verification - 2026-08-18 (feat/v3.0)

**Environment:** `.venvs/demo/bin/python` | **Base Commit:** `5668fdfaa` (origin/feat/v3.0)

### sequence_of_steps.py

**Status:** PASS (environment noise)

**Description:** Two-step content workflow (research team then planning agent).

**Result:** First run completed end to end with transient connection retries. A rerun stalled inside get_top_hackernews_stories (external Hacker News API, 10 sequential fetches with 30s timeouts) - environmental, not framework code. Note: member agents use gpt-4o-mini via OpenAIChat, which violates the cookbook model conventions.

---

> Tests not yet run. Run each file and update this log.

### sequence_of_steps.py

**Status:** PENDING

**Description:** Runs sequence_of_steps.py and validates expected behavior.

---

### sequence_with_functions.py

**Status:** PENDING

**Description:** Runs sequence_with_functions.py and validates expected behavior.

---

### workflow_using_steps.py

**Status:** PENDING

**Description:** Runs workflow_using_steps.py and validates expected behavior.

---

### workflow_using_steps_nested.py

**Status:** PENDING

**Description:** Runs workflow_using_steps_nested.py and validates expected behavior.

---

### workflow_with_file_input.py

**Status:** PENDING

**Description:** Runs workflow_with_file_input.py and validates expected behavior.

---

### workflow_with_session_metrics.py

**Status:** PENDING

**Description:** Runs workflow_with_session_metrics.py and validates expected behavior.

---

