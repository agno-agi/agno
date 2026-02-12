# Review Log: 11_memory

**Date:** 2026-02-11
**Reviewer:** Claude Opus 4.6 + Codex GPT-5.3
**Scope:** Three-layer review (framework, quality, compatibility)

---

## Framework Issues (Source-Verified)

### REAL BUG: clear_memory() global wipe (not user-scoped)
**Location:** `agno/memory/manager.py:1392` (sync) + `1526` (async)
**Verdict:** REAL BUG — confirmed via source
**Evidence:** `db.clear_memories()` executes `table.delete()` (postgres.py:1590) with NO WHERE clause — deletes ALL rows in the memories table. In multi-tenant scenarios, any user triggering this tool deletes everyone's memories. The sync version (line 1392) and async version (line 1526) both call the same unscoped `clear_memories()`.
**Practical impact:** HIGH — data loss for all users when any single user triggers the clear_memory tool.

### REAL BUG: async update_memory missing user_id
**Location:** `agno/memory/manager.py:1478-1486`
**Verdict:** REAL BUG — confirmed via source comparison
**Evidence:** Sync `update_memory` (line 1357-1363) includes `user_id=user_id` in the UserMemory constructor. Async `update_memory` (line 1480-1485) omits it — the UserMemory has no `user_id`, `agent_id`, or `team_id`. This means the upserted memory loses its user association, potentially causing cross-user data modification.
**Practical impact:** HIGH — async agents lose user scoping on memory updates.

### REAL BUG: async delete_memory missing user_id
**Location:** `agno/memory/manager.py:1510-1511`
**Verdict:** REAL BUG — confirmed via source comparison
**Evidence:** Sync `delete_memory` (line 1379) calls `db.delete_user_memory(memory_id=memory_id, user_id=user_id)`. Async `delete_memory` (line 1511) calls `await db.delete_user_memory(memory_id=memory_id)` — missing `user_id`. Could delete a different user's memory if memory IDs are reused or guessable.
**Practical impact:** MEDIUM — async agents may delete wrong user's memories.

### REAL BUG: sync _upsert/_delete_db_memory with async DB
**Location:** `agno/memory/manager.py:554-559` and `565-574`
**Verdict:** REAL BUG — confirmed via source
**Evidence:** `_upsert_db_memory()` and `_delete_db_memory()` are sync-only with no `isinstance(self.db, AsyncBaseDb)` guard. `create_user_memories()` has the guard (line 380), but `add_user_memory()` (line 234) and `replace_user_memory()` (line 265) call the unguarded sync helper — silently returning unawaited coroutines on async DBs.
**Practical impact:** MEDIUM — MemoryManager with AsyncBaseDb silently drops memories.

### CODE QUALITY: strategy interface has no token budget guard
**Location:** `agno/memory/strategies/base.py:16` + `summarize.py:23`
**Verdict:** CODE QUALITY ISSUE (not a bug)
**Evidence:** The strategy interface passes entire memory list without a max-memories or token limit. However, it provides `count_tokens()` for subclasses to use — enforcement is delegated to implementations. No crash or data loss; just a theoretical risk of large context.

### CODE QUALITY: _get_last_n_memories ascending order
**Location:** `agno/memory/manager.py:723`
**Verdict:** CODE QUALITY ISSUE (not a bug)
**Evidence:** `sorted(..., key=lambda m: m.updated_at)` sorts ascending, then `[-limit:]` takes the last N. This correctly returns the N most recent memories in chronological (oldest→newest) order — a valid convention for context injection. Not a correctness bug.

### CODE QUALITY: sync-only CRUD surface
**Location:** `agno/memory/manager.py:190`
**Verdict:** CODE QUALITY ISSUE (not a bug)
**Evidence:** Methods like `get_user_memory`, `add_user_memory`, `search_user_memories` are sync-only. However, `aread_from_db()` and `acreate_user_memories()` exist for the main paths. The missing async variants on secondary CRUD methods are a completeness gap, not a correctness bug.

---

## Cookbook Quality

[QUALITY] `01_agent_with_memory.py:12` — uses internal import `from agno.agent.agent import Agent` instead of public `from agno.agent import Agent`
[QUALITY] `02_agentic_memory.py:9` — same internal import inconsistency
[QUALITY] `03_agents_share_memory.py:8` — same internal import inconsistency
[QUALITY] `04_custom_memory_manager.py:9` — same internal import inconsistency
[QUALITY] `05_multi_user_multi_session_chat.py:11` — same internal import inconsistency
[QUALITY] `06_multi_user_multi_session_chat_concurrent.py:11` — same internal import inconsistency
[QUALITY] `memory_manager/05_db_tools_control.py:11` — imports MemoryManager from internal path `agno.memory.manager` instead of `agno.memory`
[QUALITY] `optimize_memories/02_custom_memory_strategy.py:13` — imports UserMemory from `agno.db.schemas` instead of `agno.memory`
[QUALITY] `07_share_memory_and_history_between_agents.py:13` — imports OpenAIChat via internal submodule `agno.models.openai.chat` instead of `agno.models.openai`

---

## Fixes Applied (Prior Session)

[COMPAT] `08_memory_tools.py` — double `asyncio.run()` wrapped into single `async def main()` to avoid event loop closed error
[COMPAT] `memory_manager/03_custom_memory_instructions.py` — claude model ID updated to current version

---

## Test Summary

All 15 files tested and PASS (see TEST_LOG.md and subdirectory TEST_LOG.md files).

| Category | PASS | FAIL | SKIP |
|----------|------|------|------|
| Root (01-08) | 8 | 0 | 0 |
| memory_manager (01-05) | 5 | 0 | 0 |
| optimize_memories (01-02) | 2 | 0 | 0 |
| **Total** | **15** | **0** | **0** |
