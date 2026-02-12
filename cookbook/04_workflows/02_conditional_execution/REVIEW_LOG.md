# Review Log: 02_conditional_execution

> Reviewed: 2026-02-11 (v2.5 audit)

## Framework Issues

[FRAMEWORK] workflow.py:4293 — Step with `add_workflow_history=True` and no Workflow DB is silently dropped (same as basic workflows).

## Cookbook Quality

[QUALITY] condition_basic.py — Good intro to Condition with fact-check gate. Uses `from agno.agent.agent import Agent` (internal path; prefer `from agno.agent import Agent`). Clear evaluator function pattern.

[QUALITY] condition_with_else.py — Strong demo of `else_steps` parameter with customer support routing. Tests both if-branch (technical) and else-branch (general) with sync and async. Defines `workflow_2` without description (minor inconsistency but intentional for minimal example).

[QUALITY] condition_with_list.py — Advanced demo: Parallel containing Conditions, each with multi-step lists. Uses ExaTools + HackerNewsTools. Same internal Agent import path.

[QUALITY] condition_with_parallel.py — Multiple conditional branches (HN, web, Exa) in Parallel. All 4 run modes tested. Same internal Agent import note.

## Fixes Applied

None needed — all 4 files PASS for v2.5.
Previously failed due to: 35s timeout (condition_basic, condition_with_else) and missing exa_py (condition_with_list, condition_with_parallel).
