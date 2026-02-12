# Review Log: task_mode

> Reviewed: 2026-02-11 (v2.5 audit)

## Framework Issues

[FRAMEWORK] team/_run.py:841,2238 — Task-mode streaming fallback yields non-iterator. If any task_mode cookbook were to use `stream=True`, it would silently fall back to non-streaming. This is documented with a log_warning but the return type is incorrect.

## Cookbook Quality

[QUALITY] 01-07 all import Team from `agno.team.team` (internal path). Should use `from agno.team import Team` for v2.5 idiomatic usage. Works but not best practice.

[QUALITY] 04_async_task_mode.py — Docstring says "run multiple requests concurrently" but tasks execute sequentially via `asyncio.run()`.

## Fixes Applied

None needed — all 7 files are LIKELY OK for v2.5.
