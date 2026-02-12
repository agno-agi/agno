# Review Log: context_management

> Updated: 2026-02-11

## Framework Issues

[FRAMEWORK] libs/agno/agno/team/_init.py:220+229 — No validation for `num_history_runs` or `max_tool_calls_from_history` with negative values. Negative values would cause unexpected behavior in list slicing.

[FRAMEWORK] libs/agno/agno/team/_run.py:1269 vs 2717 — Sync/async inconsistency: sync path resolves `add_history_to_context` differently from async. Async defers more to `resolve_run_options()` while sync has inline logic.

[FRAMEWORK] libs/agno/agno/team/team.py:179 — `additional_input` is accepted as a Team parameter but the actual few-shot injection happens only at the message-building layer. No validation that the provided messages have correct role alternation (user/assistant pairs).

## Cookbook Quality

[QUALITY] few_shot_learning.py — Clear example of `additional_input` pattern. The few-shot examples are well-crafted and realistic.

[QUALITY] filter_tool_calls_from_history.py — Good demo of `max_tool_calls_from_history`. 4 sequential runs is effective at showing context accumulation. Runs close to 120s timeout with 4 web search runs.

[QUALITY] introduction.py — Minimal and readable. Could benefit from showing that introduction is only displayed on first interaction (not repeated).

## Fixes Applied

None — all cookbooks are compatible with v2.5 API as-is.
