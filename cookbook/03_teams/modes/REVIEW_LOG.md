# Review Log: modes

> Updated: 2026-02-11

## Framework Issues

(none found — all 4 TeamMode variants work correctly)

## Cookbook Quality

[QUALITY] All modes cookbooks — Consistent, well-structured examples. Each file has clear docstring, member agents, team setup, and run section. Good progression from basic → advanced within each mode.

[QUALITY] All modes cookbooks — Use `from agno.team.team import Team` instead of `from agno.team import Team`. Both work but the latter is the canonical v2.5 import.

[QUALITY] coordinate/02_with_tools.py + broadcast/03_research_sweep.py — DuckDuckGoTools fails with SSL certificate errors in some network environments. These cookbooks work correctly code-wise but are fragile in restrictive network setups.

[QUALITY] tasks/ — Good demonstration of sequential, parallel, and dependency-based task execution. The `max_iterations=10` setting is a good practice to prevent infinite loops.

## Fixes Applied

(none needed — all cookbooks use correct v2.5 patterns)
