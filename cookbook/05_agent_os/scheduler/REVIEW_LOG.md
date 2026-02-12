# Review Log — scheduler/

## Framework Issues

[FRAMEWORK] agno/scheduler/manager.py:193 — `ScheduleManager.list()` passes `offset=` parameter, but `SqliteDb.get_schedules()` and `PostgresDb.get_schedules()` expect `page=` (page-based pagination). Same issue for `get_schedule_runs()`. This causes all ScheduleManager list/display operations to fail. Affects 5 of 10 scheduler cookbooks.

[FRAMEWORK] agno/scheduler/manager.py:160 — `ScheduleManager.create()` raises ValueError on duplicate names without an `if_exists` option by default. All standalone cookbooks (except demo.py) fail on re-run because DB files persist between runs.

## Cookbook Quality

[QUALITY] async_schedule.py — Missing `if_exists="update"` on create calls, making re-runs fail.
[QUALITY] multi_agent_schedules.py — Same issue.
[QUALITY] run_history.py — Same issue.
[QUALITY] schedule_validation.py — Same issue.
[QUALITY] team_workflow_schedules.py — Same issue.
[QUALITY] demo.py — Good: uses `if_exists="update"` for idempotent re-runs.

## Fixes Applied

(none — framework bugs, not fixable in cookbooks)
