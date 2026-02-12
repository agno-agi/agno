# Review Log: session

> Reviewed: 2026-02-11 (v2.5 audit)

## Framework Issues

[FRAMEWORK] team/_session.py:521 — Sync `delete_session()` calls `team.db.delete_session(...)` without passing `session_type`, could delete wrong session type if IDs collide.

[FRAMEWORK] db/sqlite/sqlite.py:738 — `get_session()` does not filter by `session_type`, unlike PostgresDb. Agent/team/workflow sessions with same ID could collide.

[FRAMEWORK] db/sqlite/async_sqlite.py:573 — Same `session_type` filtering inconsistency as sync SqliteDb.

[FRAMEWORK] db/in_memory/in_memory_db.py:132 — `get_session()` also ignores `session_type`; inconsistent with PostgresDb.

[FRAMEWORK] db/in_memory/in_memory_db.py:44,48 — `get_latest_schema_version` and `upsert_schema_version` signatures incompatible with BaseDb.

[FRAMEWORK] db/sqlite/async_sqlite.py:512,540 — Async `delete_session()` and `delete_sessions()` swallow exceptions silently (log only), inconsistent with sync variants that propagate.

## Cookbook Quality

[QUALITY] session_summary.py — Combines sync+async DB setups in one file; async part uses sync PostgresDb which fails at `aget_session_summary`.

[QUALITY] session_options.py — Over-broad for one file; try/except blocks mask real failures.

[QUALITY] share_session_with_agent.py — Teaching intent may be misleading under v2.5's single session table (agent vs team session_type).

## Fixes Applied

None needed — all 6 files are LIKELY OK for v2.5.
1 file SKIP (search_session_history.py: missing aiosqlite).
1 file partial FAIL (session_summary.py: sync PASS, async FAIL due to greenlet/session not found).
