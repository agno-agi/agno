# REVIEW LOG — caching

Generated: 2026-02-11 UTC (v2.5 three-layer review)

## Summary

1 file reviewed. No fixes required.

## cache_model_response.py

- **[FRAMEWORK]** `OpenAIChat(cache_response=True)` is correct. `cache_response` is on base `Model` class (`models/base.py:150`), inherited by all providers.
- **[QUALITY]** Minor: `response.metrics.duration` accessed without null guard. In practice `metrics` is always populated after a successful `run()`, so this is safe.
- **[COMPAT]** No deprecated imports. `OpenAIChat` is the correct class for chat completions API.

## Framework Files Checked

- `libs/agno/agno/models/base.py:150` — `cache_response` field
- `libs/agno/agno/models/base.py:629-1713` — Cache logic in sync/async run paths

---

# REVIEW LOG

Generated: 2026-02-11 UTC (v2.5 three-layer review)

## Framework Issues

[FRAMEWORK] agno/db/sqlite/sqlite.py:161 — `from_dict()` omits newer v2.5 table fields (`learnings_table`, `schedules_table`, `schedule_runs_table`), so deserialized SqliteDb instances may lose table configuration.

[FRAMEWORK] agno/db/sqlite/sqlite.py:101 — ID seed expression precedence: `db_url or db_file or str(db_engine.url) if db_engine else "sqlite:///agno.db"` — the `if db_engine` clause only guards `str(db_engine.url)`, not the entire chain. When all three are None and db_engine is also None, this evaluates correctly by accident but the intent is unclear.

[FRAMEWORK] agno/learn/machine.py:164 — `_resolve_store()` accepts any truthy non-supported type and silently passes, making misconfiguration hard to debug.

## Cookbook Quality

[QUALITY] learning_machine.py — The "What do you remember about me?" prompt in session 2 is a good cross-session test, but the cookbook doesn't demonstrate the AGENTIC mode's background extraction (only explicit tool call). The agent used `update_profile` tool call, which would also work in ALWAYS mode.

## Fixes Applied

None — cookbook is v2.5 compatible as-is.
