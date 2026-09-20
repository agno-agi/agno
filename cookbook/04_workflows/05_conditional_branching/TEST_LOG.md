# TEST_LOG for cookbook/04_workflows/05_conditional_branching

Generated: 2026-02-08 16:39:09

### loop_in_choices.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. ┃ Jupyter, in particular, is exceptional for data visualization and ┃

---

### nested_choices.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. Completed in 2.8s

---

### router_basic.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. DEBUG ********************** TOOL METRICS **********************

---

### router_with_loop.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. DEBUG Creating new async OpenAI client for model gpt-5.6-luna

---

### selector_media_pipeline.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. DEBUG Running: generate_image(prompt=...)

---

### selector_types.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. Completed in 2.4s

---

### step_choices_parameter.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. Completed in 1.7s

---

### string_selector.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. Completed in 8.4s

---

### router_jev_classifier.py

**Status:** PASS

**Description:** Workflow with a Jev `output_schema` classification step followed by a Router whose selector branches on the parsed pydantic object. Run with `.venv/Scripts/python.exe` (Windows, Python 3.12, typesafe-sdk 0.7.0), live TypeSafe and OpenAI APIs, 2026-09-21.

**Result:** The CSV crash was classified `bug_report` (urgent) and routed to the bug triager, which wrote an [URGENT] ticket; the dashboard-sharing message was classified `feature_request` (not urgent) and became a user story. First run exposed that an agent step receives the previous step's output as its message, so the specialists were changed to executor functions that run on `step_input.input`.

---
