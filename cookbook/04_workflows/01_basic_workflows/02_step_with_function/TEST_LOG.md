# TEST_LOG for cookbook/04_workflows/01_basic_workflows/02_step_with_function

> v2.5 audit — 2026-02-11 (timeout: 120s)

### step_with_function.py

**Status:** PASS

**Description:** Custom function executors (sync, sync-streaming, async-streaming) used as step executors in workflows.

**Result:** All 3 workflow variants (sync, sync-stream, async-stream) completed. Function executors correctly receive StepInput and yield StepOutput.

---

### step_with_class.py

**Status:** PASS

**Description:** Class-based step executors using `__call__` for both sync and async workflow execution.

**Result:** Both sync and async-streaming runs completed. Class executors correctly implement callable protocol.

---

### step_with_additional_data.py

**Status:** PASS

**Description:** Step executors consuming `additional_data` dict from workflow run input.

**Result:** Both sync-stream and async-stream runs completed. additional_data correctly propagated to step_input.additional_data.

---
