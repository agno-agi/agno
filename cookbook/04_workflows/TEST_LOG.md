# Test Log — cookbook/04_workflows

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

## Summary

| Directory | Files | PASS | FAIL | SKIP |
|-----------|-------|------|------|------|
| 01_basic_workflows | 10 | 7 | 3 | 0 |
| 02_conditional_execution | 4 | 3 | 1 | 0 |
| 03_loop_execution | 2 | 2 | 0 | 0 |
| 04_parallel_execution | 2 | 0 | 2 | 0 |
| 05_conditional_branching | 8 | 8 | 0 | 0 |
| 06_advanced_concepts | 38 | 26 | 2 | 10 |
| 07_cel_expressions | 14 | 14 | 0 | 0 |
| **Total** | **78** | **60** | **8** | **10** |

## Failure Summary

| File | Error |
|------|-------|
| 01/.../sequence_of_steps.py | httpx.ReadTimeout |
| 01/.../step_with_function.py | httpx.ReadTimeout |
| 01/.../function_workflow.py | httpx.ReadTimeout |
| 02/condition_with_parallel.py | Event loop is closed + NoneType parent_run_id |
| 04/parallel_basic.py | Event loop is closed + NoneType parent_run_id |
| 04/parallel_with_condition.py | Killed by timeout 120 |
| 06/.../access_previous_outputs.py | TypeError: NoneType has no len() |
| 06/.../structured_io_team.py | Killed by timeout 120 |

## Skip Summary

- 4 interactive CLI files (history/ subdirectory)
- 3 long-running server files (long_running/ subdirectory)
- 1 remote workflow (requires AgentOS server)
- 1 websocket client (interactive)
- 1 websocket server (server process)

See individual subdirectory TEST_LOG.md files for detailed per-file results.
