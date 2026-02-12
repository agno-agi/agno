# Review Log — tracing/

## Framework Issues

[FRAMEWORK] openinference-instrumentation-agno (third-party) — Tries to monkey-patch `Agent._run` which was moved to `agent/_run.py` in v2.5. Breaks `setup_tracing()` path. Affects 06_tracing_with_multi_db_scenario.py. The `tracing=True` flag on AgentOS uses a different code path and works fine.

## Cookbook Quality

[QUALITY] dbs/basic_agent_with_sqlite.py:43 — Serve app name says `basic_agent_with_postgresdb:app` but file is the sqlite variant. Should be `basic_agent_with_sqlite:app`.
[QUALITY] 06 vs 07 — These are nearly identical. 06 uses manual `setup_tracing()`, 07 uses `tracing=True` flag. The difference should be more clearly documented.

## Fixes Applied

(none needed — 06 failure is a third-party issue, not fixable in cookbook)
