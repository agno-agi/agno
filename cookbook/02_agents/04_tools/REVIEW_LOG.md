# REVIEW LOG — callable_factories

Generated: 2026-02-11 UTC (v2.5 three-layer review)

## Summary

3 files reviewed. No fixes required.

## 01_callable_tools.py

- **[FRAMEWORK]** `tools=tools_for_user` (callable) is valid. Detected via `is_callable_factory()` at `agent.py:543`. RunContext injection works via signature inspection in `utils/callables.py`.
- **[QUALITY]** Excellent educational value. Shows role-based tool gating with clear print statements.
- **[COMPAT]** `from agno.run import RunContext` is the correct v2.5 import path.

## 02_session_state_tools.py

- **[FRAMEWORK]** `session_state` param injection by name is supported (`utils/callables.py:88`). `cache_callables=False` correctly disables per-user caching (`agent.py:646`).
- **[QUALITY]** Clean example demonstrating mode switching. Good contrast with 01's cached behavior.
- **[COMPAT]** No issues.

## 03_team_callable_members.py

- **[FRAMEWORK]** `Team(members=pick_members)` is valid. Team callable resolution in `utils/callables.py:399-436`. `cache_callables=False` on Team at `team.py:625`.
- **[QUALITY]** Good demonstration of dynamic team composition. Shows both single-member and multi-member paths.
- **[COMPAT]** `from agno.team import Team` is correct v2.5 import.

## Framework Files Checked

- `libs/agno/agno/agent/agent.py:352,463,543,646` — cache_callables, callable detection
- `libs/agno/agno/team/team.py:368,513,625` — Team cache_callables
- `libs/agno/agno/utils/callables.py` — is_callable_factory, signature inspection, cache logic
- `libs/agno/agno/run/base.py:16-33` — RunContext with session_state, tools, members fields

---

# REVIEW LOG

Generated: 2026-02-11 UTC (v2.5 three-layer review)

## Framework Issues

[FRAMEWORK] agno/agent/_run.py:130 — Sync dependency resolution can store coroutine objects when a callable factory is inadvertently async. Should validate that resolved values are not coroutines.

## Cookbook Quality

[QUALITY] retries.py — Shows flags well but no deterministic failure trigger makes retry behavior unobservable. Teaching value limited.

[QUALITY] metrics.py — Useful but heavy dependencies (Postgres + finance tool) reduce portability.

[QUALITY] cancel_run.py — Functional but thread-heavy; contains a stale comment referencing old API.

[QUALITY] tool_call_limit.py — The "should fail second tool" expectation is model/provider dependent; fragile test vector.

[QUALITY] agent_serialization.py — Missing null-check after `Agent.load(...)` weakens the teaching example.

[QUALITY] debug.py — Clear and idiomatic. No issues.

[QUALITY] tool_choice.py — Uses outdated forced-tool schema format; should use current tool-choice convention.

[QUALITY] concurrent_execution.py — Reusing one agent concurrently without explicit session_id per task could cause state collision; should mention this.

## Fixes Applied

None — all cookbooks are v2.5 compatible as-is.
