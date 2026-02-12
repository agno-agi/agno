# Review Log: 01_sequence_of_steps

> Reviewed: 2026-02-11 (v2.5 audit)

## Framework Issues

[FRAMEWORK] workflow.py:4293 — Step with `add_workflow_history=True` and no Workflow DB is silently dropped from execution instead of raising an error.

[FRAMEWORK] workflow.py:1642,2186 — `session_state` passed to function-based workflows via `self.session_state` may be stale; active state lives in run/session context.

## Cookbook Quality

[QUALITY] sequence_of_steps.py — Comprehensive demo of all 5 run modes (sync, sync-stream, async, async-stream, event-stream). Well-structured with clear sections. Uses both Team steps and Agent steps with SqliteDb persistence. Strong pedagogical value.

[QUALITY] sequence_with_functions.py — Good demo of inline async generator functions as step executors. Minor: `<research_results>` XML tags opened/closed correctly despite Codex flagging (double-checked).

[QUALITY] workflow_using_steps.py — Clean use of `Steps` container with 3-agent pipeline. Good sync+async coverage.

[QUALITY] workflow_using_steps_nested.py — Strong advanced example combining `Steps`, `Condition`, `Parallel`. Requires `exa_py` (now available in demo venv). Demonstrates `is_tech_topic` evaluator with Parallel nesting inside Condition.

[QUALITY] workflow_with_file_input.py — Simple file input demo. Clear and focused.

[QUALITY] workflow_with_session_metrics.py — Good metrics collection example showing duration and step counts.

## Fixes Applied

None needed — all 6 files PASS for v2.5.
