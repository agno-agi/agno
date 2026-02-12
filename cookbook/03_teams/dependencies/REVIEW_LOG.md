# Review Log: dependencies

> Updated: 2026-02-11

## Framework Issues

[FRAMEWORK] libs/agno/agno/team/_run.py — Sync `_resolve_run_dependencies()` doesn't handle async dependency factories (callables returning coroutines). If a user passes an async callable as a dependency value in a sync `team.run()`, it will silently store the coroutine object rather than awaiting it.

[FRAMEWORK] libs/agno/agno/team/_run.py — Dependency resolution failures (exceptions from callable factories) are caught and logged as warnings but not re-raised. The dependency value is silently set to `None`, which can cause subtle downstream bugs when tools or instructions reference the missing dependency.

[FRAMEWORK] libs/agno/agno/team/team.py — No validation that dependency keys used in instruction templates (`{user_profile}`) actually exist in the `dependencies` dict. A typo in the template key silently produces `{user_profile}` as literal text in the instructions.

## Cookbook Quality

[QUALITY] dependencies_in_context.py — Clear template-based injection pattern. Uses `debug_mode=True` which produces verbose output but helps demonstrate the dependency resolution flow.

[QUALITY] dependencies_in_tools.py — Good coverage of two distinct dependency patterns (context injection vs tool-level access). The `analyze_team_performance` tool with `run_context: RunContext` parameter is a clean demonstration of the RunContext dependency access pattern.

[QUALITY] dependencies_to_members.py — Demonstrates runtime dependency passing via `print_response()` kwargs rather than team-level config. This is the most flexible pattern. Uses `show_members_responses=True` which proves dependencies actually propagated to individual members.

## Fixes Applied

None — all cookbooks are compatible with v2.5 API as-is.
