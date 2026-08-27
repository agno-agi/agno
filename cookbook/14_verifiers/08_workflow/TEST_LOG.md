# Test Log

## 2026-08-27 — gpt-5.5, demo venv

### verify_step.py

**Status:** PASS

**Description:** Workflow [write -> Verify(on_fail="write", max_rounds=2) -> publish] with a file-and-content check as the gate. The writer produced RELEASE_NOTES.md correctly on round one; the Verify step passed (record verified/passed, 1 attempt) and the publisher ran. The loop-back-with-evidence leg is pinned by the unit suite (the re-entered step's input carries the verification block).

**Result:** Success. Note: the absorbed segment step ("write") nests under the Verify StepOutput.steps rather than appearing at the top level of step_results.

---

## 2026-08-27 — review follow-up (not a live run)

`verify_step.py` gained `stop_when_unverified=True` on its Verify step after review: when the
gate ends unverified, the workflow now stops instead of publishing anyway. Pinned by the unit
suite (`test_verify_step.py`); the example itself has not been re-run against a live model since
the change.

---
