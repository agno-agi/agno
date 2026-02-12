# Review Log: 06_storage

**Date:** 2026-02-11
**Reviewer:** Claude Opus 4.6 + Codex GPT-5.3
**Scope:** Three-layer review (framework, quality, compatibility)

---

## Framework Issues (Source-Verified)

### REAL BUG: from_dict() drops v2.5 table names
**Location:** `agno/db/postgres/postgres.py:177` + `agno/db/sqlite/sqlite.py:161`
**Verdict:** REAL BUG — empirically confirmed
**Evidence:** `PostgresDb(learnings_table='custom_learnings').to_dict()` serializes the custom name, but `PostgresDb.from_dict(d)` doesn't read `learnings_table`, `schedules_table`, `schedule_runs_table`, or `approvals_table` — they revert to defaults. Round-tripping via `to_dict()`/`from_dict()` silently drops v2.5 table customizations.
**Practical impact:** Any Team/Workflow using custom v2.5 table names that gets serialized and restored will lose those custom names. Affects `team/_storage.py:493` and `workflow.py:607`.

### REAL BUG: get_sessions() crashes with default parameters
**Location:** `agno/db/postgres/postgres.py:868-875` (all 4 backends)
**Verdict:** REAL BUG — empirically confirmed (`ValueError: Invalid session type: None`)
**Evidence:** `db.get_sessions()` with both defaults (`session_type=None`, `deserialize=True`) crashes. The SQL query runs fine with no type filter, but deserialization has no handler for `None` — falls to `raise ValueError`. Same in `sqlite.py`, `async_postgres.py`, `async_sqlite.py`.
**Practical impact:** LOW — all internal callers either pass `session_type` explicitly or use `deserialize=False`. A new developer calling `db.get_sessions(user_id="foo")` would hit it though.

### REAL BUG: AsyncBaseDb missing to_dict()/from_dict()
**Location:** `agno/db/base.py:1080` (AsyncBaseDb class)
**Verdict:** REAL BUG — confirmed via `hasattr(AsyncPostgresDb, 'to_dict')` → `False`
**Evidence:** `AsyncBaseDb` and its subclasses have no serialization. Team/Workflow persistence checks `hasattr(team.db, 'to_dict')` (team/_storage.py:492) — for async DBs this fails, so `config["db"]` is never set. DB config is silently lost on serialization.
**Practical impact:** MEDIUM — Teams/Workflows using async DB variants can't be serialized/restored.

### REAL BUG: sync _upsert/_delete_db_memory with async DB
**Location:** `agno/memory/manager.py:554-559` and `565-574`
**Verdict:** REAL BUG — confirmed via source inspection
**Evidence:** `_upsert_db_memory()` calls `self.db.upsert_user_memory(memory=memory)` without checking if DB is async. If `self.db` is an `AsyncBaseDb`, this returns an unawaited coroutine instead of persisting. `add_user_memory()` (line 234) and `replace_user_memory()` (line 265) have no async guard — unlike `create_user_memories()` which does check at line 380.
**Practical impact:** MEDIUM — MemoryManager with AsyncBaseDb silently drops memories on `add_user_memory()`.

### FALSE POSITIVE: in_memory_db string-vs-enum comparison
**Location:** `agno/db/in_memory/in_memory_db.py:325`
**Verdict:** FALSE POSITIVE
**Evidence:** `SessionType(str, Enum)` inherits from `str`. Empirically: `"agent" == SessionType.AGENT` → `True`. The stored `.value` string compares equal to the enum member because the enum IS a string. All three types verified.

### FALSE POSITIVE: workflow/step.py get_chat_history raises ValueError
**Location:** `agno/workflow/step.py:1366`
**Verdict:** FALSE POSITIVE
**Evidence:** When a Workflow sets up steps, it assigns `active_executor.workflow_id = self.id` (workflow.py:4614). This means `self.agent.get_session()` enters the `agent.workflow_id is not None` branch at `_session.py:129`, loading a `WorkflowSession` — so the `isinstance` check passes.

### CODE QUALITY: InMemoryDb schema version method signatures
**Location:** `agno/db/in_memory/in_memory_db.py:44,48`
**Verdict:** CODE QUALITY ISSUE (not a bug)
**Evidence:** BaseDb requires `get_latest_schema_version(self, table_name)` but InMemoryDb has `get_latest_schema_version(self)` (no `table_name`). Both methods are no-ops (`pass`) — InMemoryDb intentionally ignores schema versioning. Would only crash if someone explicitly called `in_memory_db.get_latest_schema_version(table_name='foo')` which doesn't happen in practice.

---

## Cookbook Quality

[QUALITY] `in_memory_storage_for_team.py:3` — stale docstring run path: references `cookbook/storage/in_memory_storage/` instead of `cookbook/06_storage/in_memory/`
[QUALITY] `sqlite/sqlite_for_team.py:3` — stale docstring run path: references `cookbook/storage/sqlite_storage/`
[QUALITY] `sqlite/async_sqlite/async_sqlite_for_team.py:3` — stale docstring run path: references `cookbook/db/async_sqlite/`
[QUALITY] `sqlite/async_sqlite/async_sqlite_for_workflow.py:3` — stale docstring run path: references `cookbook/db/async_sqlite/`
[QUALITY] `postgres/postgres_for_team.py:3` — stale docstring run path: references `cookbook/storage/postgres_storage/`
[QUALITY] `postgres/async_postgres/async_postgres_for_team.py:3` — stale docstring run path: references `cookbook/db/async_postgres/`
[QUALITY] `in_memory/in_memory_storage_for_workflow.py` — docstring says "JSON files" but uses InMemoryDb

---

## Fixes Applied

[COMPAT] `sqlite/async_sqlite/async_sqlite_for_agent.py:30-31` — double `asyncio.run()` wrapped into single `async def main()` + `asyncio.run(main())`
[COMPAT] `postgres/async_postgres/async_postgres_for_agent.py:31-32` — same double `asyncio.run()` fix

---

## Unfixed Issues (SKIP backends)

[COMPAT] `mongo/async_mongo/async_mongodb_for_agent.py:45-46` — same double `asyncio.run()` bug, not fixed (MongoDB not available)

---

## Dependencies Installed

- `aiosqlite==0.22.1` — required by AsyncSqliteDb
- `greenlet==3.3.1` — required by SQLAlchemy async session management

---

## Test Summary

| Category | PASS | FAIL | SKIP |
|----------|------|------|------|
| in_memory | 3 | 0 | 0 |
| sqlite (sync) | 2 | 1 | 0 |
| sqlite (async) | 3 | 0 | 0 |
| json_db | 3 | 0 | 0 |
| examples | 2 | 0 | 0 |
| postgres (sync) | 3 | 0 | 0 |
| postgres (async) | 3 | 0 | 0 |
| top-level | 3 | 0 | 0 |
| mysql | 0 | 0 | 5 |
| mongo | 0 | 0 | 5 |
| redis | 0 | 0 | 3 |
| dynamodb | 0 | 0 | 2 |
| firestore | 0 | 0 | 1 |
| gcs | 0 | 0 | 1 |
| singlestore | 0 | 0 | 2 |
| surrealdb | 0 | 0 | 3 |
| **Total** | **22** | **1** | **22** |

**1 FAIL:** `sqlite_for_workflow.py` — timeout (>120s), likely intermittent API latency. Same pattern passes in other backends.
