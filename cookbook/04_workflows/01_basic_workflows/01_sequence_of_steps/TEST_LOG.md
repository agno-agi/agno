# TEST_LOG for cookbook/04_workflows/01_basic_workflows/01_sequence_of_steps

> v2.5 audit — 2026-02-11 (timeout: 120s)

### sequence_of_steps.py

**Status:** PASS

**Description:** Sequential workflow with sync, async, streaming, and event-streaming runs using Team + Agent steps.

**Result:** All 5 run modes (sync, sync-stream, async, async-stream, event-stream) completed successfully.

---

### sequence_with_functions.py

**Status:** PASS

**Description:** Sequential workflow using inline async generator functions as step executors to prepare inputs between steps.

**Result:** Completed successfully. Function executors correctly receive and transform StepInput.

---

### workflow_using_steps.py

**Status:** PASS

**Description:** Workflow using a `Steps` sequence container with research, writing, and editing steps.

**Result:** Both sync and async runs completed. Steps container correctly chains agent execution.

---

### workflow_using_steps_nested.py

**Status:** PASS

**Description:** Nested workflow composition using `Steps`, `Condition`, and `Parallel` primitives with ExaTools.

**Result:** Completed with streaming. Condition evaluator correctly detected tech topic and triggered parallel research.

---

### workflow_with_file_input.py

**Status:** PASS

**Description:** Workflow that reads input from a file path and processes it through sequential steps.

**Result:** Completed successfully. File content correctly passed as workflow input.

---

### workflow_with_session_metrics.py

**Status:** PASS

**Description:** Workflow demonstrating session metrics collection including duration and step counts.

**Result:** Completed. Metrics correctly reported step count and execution time.

---
