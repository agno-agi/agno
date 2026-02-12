# Review Log: 03_function_workflows

> Reviewed: 2026-02-11 (v2.5 audit)

## Framework Issues

Same workflow-level framework issues apply (see 01_sequence_of_steps/REVIEW_LOG.md).

## Cookbook Quality

[QUALITY] function_workflow.py — Comprehensive demo of function-based workflows (steps=callable) with all 4 variants: sync, sync-stream, async, async-stream. Uses `WorkflowExecutionInput` signature correctly. Minor: `custom_execution_function_async` (line 135) uses `research_team.run()` (sync) inside an async function; should use `await research_team.arun()` for proper async behavior. Also uses `gpt-5.2` model for streaming_hackernews_agent which may surprise users expecting gpt-4o.

## Fixes Applied

None needed — all 1 file PASS for v2.5.
