# Review Log: 02_step_with_function

> Reviewed: 2026-02-11 (v2.5 audit)

## Framework Issues

Same workflow-level framework issues apply (see 01_sequence_of_steps/REVIEW_LOG.md).

## Cookbook Quality

[QUALITY] step_with_function.py — Thorough demo covering sync, sync-streaming, and async-streaming function executors. Uses `StepInput`/`StepOutput` from `agno.workflow.step` (works via transitive import; canonical path is `agno.workflow.types`). Custom executors assume `previous_step_content[:500]` is sliceable — safe in practice but `StepOutput.content` could theoretically be non-string.

[QUALITY] step_with_class.py — Good class-based executor demo using `__call__`. Same transitive import and slicing notes as above. Both sync and async class variants shown.

[QUALITY] step_with_additional_data.py — Strong demo of `additional_data` propagation. Shows enterprise metadata (user_email, priority, client_type) flowing through to step executors.

## Fixes Applied

None needed — all 3 files PASS for v2.5.
