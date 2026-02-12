# TEST_LOG for cookbook/04_workflows/07_cel_expressions

Generated: 2026-02-11

**Note:** Required `cel-python` package installation (`uv pip install cel-python`).

## condition/

### cel_basic.py

**Status:** PASS

**Description:** CEL `input.contains("urgent")` condition with if/else branches. 2 runs.

**Result:** Both completed (urgent: routed to urgent handler, normal: routed to normal handler). 1.8s total.

---

### cel_additional_data.py

**Status:** PASS

**Description:** CEL condition using additional_data fields. 2 runs.

**Result:** Completed (5.8s, 10.0s).

---

### cel_previous_step.py

**Status:** PASS

**Description:** CEL condition using previous step output content. 2 runs.

**Result:** Completed (10.4s, 2.9s).

---

### cel_previous_step_outputs.py

**Status:** PASS

**Description:** CEL condition accessing previous_step_outputs map. 2 runs.

**Result:** Completed (30.0s, 48.2s).

---

### cel_session_state.py

**Status:** PASS

**Description:** CEL condition using session state variables. 5 runs.

**Result:** All completed (9.6s, 3.1s, 2.6s, 6.1s, 4.5s). Session state correctly tracked across runs.

---

## loop/

### cel_compound_exit.py

**Status:** PASS

**Description:** CEL compound exit condition combining multiple checks. 1 run.

**Result:** Completed in 89.9s.

---

### cel_content_keyword.py

**Status:** PASS

**Description:** CEL end condition checking for keyword in output content. 1 run.

**Result:** Completed in 8.0s.

---

### cel_iteration_limit.py

**Status:** PASS

**Description:** CEL `current_iteration >= 2` with max_iterations=10. Verifies early exit. 1 run.

**Result:** Completed in 20.7s.

---

### cel_step_outputs_check.py

**Status:** PASS

**Description:** CEL end condition checking step output properties. 1 run.

**Result:** Completed in 50.0s.

---

## router/

### cel_additional_data_route.py

**Status:** PASS

**Description:** CEL router using additional_data for routing decisions. 2 runs.

**Result:** Completed (6.8s, 2.4s).

---

### cel_previous_step_route.py

**Status:** PASS

**Description:** CEL router using previous step content for routing. 2 runs.

**Result:** Completed (4.6s, 3.6s).

---

### cel_session_state_route.py

**Status:** PASS

**Description:** CEL router using session state for adaptive routing. Multiple runs.

**Result:** Completed (8.8s, 21.6s).

---

### cel_ternary.py

**Status:** PASS

**Description:** CEL ternary operator `input.contains("video") ? "Video Handler" : "Image Handler"`. 2 runs.

**Result:** Completed (17.2s, 11.2s). Correctly routed video and image requests.

---

### cel_using_step_choices.py

**Status:** PASS

**Description:** CEL router with step_choices parameter. 2 runs.

**Result:** Completed (13.5s, 27.7s).

---
