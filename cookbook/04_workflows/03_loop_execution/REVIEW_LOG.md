# Review Log: 03_loop_execution

> Reviewed: 2026-02-11 (v2.5 audit)

## Framework Issues

[FRAMEWORK] workflow.py:4293 — Step with `add_workflow_history=True` and no Workflow DB is silently dropped (same as other workflow dirs).

## Cookbook Quality

[QUALITY] loop_basic.py — Clean demo of Loop with `end_condition` evaluator and `max_iterations` guard. Evaluator checks content length > 200 chars. All 4 run modes tested (sync, sync-stream, async, async-stream). Uses `from agno.workflow import Loop, Step, Workflow` (public path, good).

[QUALITY] loop_with_parallel.py — Strong advanced demo: Loop body with Parallel (3 concurrent steps) + sequential step. Same content-length evaluator pattern. 3 run modes tested. Good composition of Loop + Parallel primitives.

## Fixes Applied

None needed — both files PASS for v2.5.
Previously failed due to 35s timeout (workflows with loops and parallel steps need more time).
