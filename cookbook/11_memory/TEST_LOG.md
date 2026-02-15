# Test Log: 11_memory

**Date:** 2026-02-11
**Environment:** `.venvs/demo/bin/python`
**Model:** gpt-4o, gpt-4o-mini, gpt-5-mini
**Services:** pgvector, sqlite

## Structure Check

**Result:** Checked 15 file(s). Violations: 0
**Details:** Clean

---

## Runtime Results

### 01_agent_with_memory.py

**Status:** PASS
**Time:** ~12s
**Description:** Agent with persistent memory using PostgresDb. Tests both async and sync responses, memory creation and preference updates.
**Output:** Agent created memories for John Doe (name, hiking preference), then updated preference from hiking to soccer.
**Triage:** n/a

---

### 02_agentic_memory.py

**Status:** PASS
**Time:** ~45s
**Description:** Agent with agentic memory (tool-based). Tests memory create, recall, delete via tool calls, and update preferences.
**Output:** Agent used update_user_memory tool to create, clear, and update memories. Paint -> draw preference update worked correctly.
**Triage:** n/a

---

### 03_agents_share_memory.py

**Status:** PASS
**Time:** ~15s
**Description:** Two agents (chat + research) sharing the same PostgresDb memory store. Research agent uses WebSearchTools.
**Output:** Chat agent remembered hobbies, research agent added quantum computing interest. Both agents share the same user memory pool.
**Triage:** n/a

---

### 04_custom_memory_manager.py

**Status:** PASS
**Time:** ~10s
**Description:** Custom MemoryManager with additional_instructions to avoid storing user names. Agent uses the custom manager for memory updates.
**Output:** Memories correctly used "The User" instead of names per custom instructions. Swim -> soccer preference update worked.
**Triage:** n/a

---

### 05_multi_user_multi_session_chat.py

**Status:** PASS
**Time:** ~35s
**Description:** Sequential multi-user, multi-session async chat. 3 users across 4 sessions with isolated memories per user.
**Output:** User 1 (Mark Gonzales): anime, video games. User 2 (John Doe): hiking. User 3 (Jane Smith): gym. All memories isolated correctly.
**Triage:** n/a

---

### 06_multi_user_multi_session_chat_concurrent.py

**Status:** PASS
**Time:** ~20s
**Description:** Concurrent multi-user chat using asyncio.gather. Same 3 users run in parallel.
**Output:** All 3 users completed concurrently. Memories isolated correctly per user despite concurrent access.
**Triage:** n/a

---

### 07_share_memory_and_history_between_agents.py

**Status:** PASS
**Time:** ~15s
**Description:** Two agents with different personas (friendly vs grumpy) sharing conversation history and memory via SqliteDb.
**Output:** Agent 2 knew user's name from agent 1's conversation. Both agents accessed shared session history and memory.
**Triage:** n/a

---

### 08_memory_tools.py

**Status:** PASS
**Time:** ~120s
**Description:** MemoryTools + WebSearchTools integration. Agent stores user info and plans a trip using web search.
**Output:** Agent stored memories via MemoryTools, performed multiple web searches, generated comprehensive travel plan for Lisbon.
**Triage:** regression (fixed in v25-fixes)
**Fix:** Wrapped two separate `asyncio.run()` calls into a single `async def main()`.
**Re-verified:** 2026-02-14 — async refactor confirmed working, memory stored, web searches completed.

---

## Summary

| File | Status | Triage | Notes |
|------|--------|--------|-------|
| `01_agent_with_memory.py` | PASS | n/a | ~12s, async+sync |
| `02_agentic_memory.py` | PASS | n/a | ~45s, tool-based memory |
| `03_agents_share_memory.py` | PASS | n/a | ~15s, shared db |
| `04_custom_memory_manager.py` | PASS | n/a | ~10s, custom instructions |
| `05_multi_user_multi_session_chat.py` | PASS | n/a | ~35s, 3 users/4 sessions |
| `06_multi_user_multi_session_chat_concurrent.py` | PASS | n/a | ~20s, concurrent |
| `07_share_memory_and_history_between_agents.py` | PASS | n/a | ~15s, SQLite |
| `08_memory_tools.py` | PASS | regression (fixed) | Fixed double asyncio.run(), needs 180s timeout |

**Totals:** 8 PASS, 0 FAIL, 0 SKIP, 0 ERROR
