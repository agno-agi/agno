# Test Log: other

> Updated: 2026-02-12

### background_execution.py

**Status:** PASS

**Description:** Async background execution — starts a team run with `background=True`, polls via `team.aget_run_output()` until COMPLETED, then demonstrates cancelling a background run with `team.acancel_run()`.

**Result:** Both examples ran successfully. Background run polled for ~20s before completing with correct thermodynamics summary. Cancellation example: run started with PENDING status, cancel sent after 3s, `acancel_run()` returned True. Final status was RUNNING (cancel was in-flight), which is expected behavior for async cancellation.

---
