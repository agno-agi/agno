# Test Log — 04_parallel_execution

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

| File | Status | Notes |
|------|--------|-------|
| parallel_basic.py | FAIL | First workflow completed (33.5s), second failed: "Event loop is closed" + NoneType parent_run_id |
| parallel_with_condition.py | FAIL | Killed by timeout 120 before completing; output was being generated but no "Completed" message |

## Summary

- **PASS:** 0
- **FAIL:** 2 (1 event loop closed, 1 timeout)
- **SKIP:** 0
