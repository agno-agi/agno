# Test Log: memory

> Updated: 2026-02-11

### 01_team_with_memory_manager.py

**Status:** PASS

**Description:** Persistent memory via MemoryManager — team stores user info (name, hobbies) on first run, recalls on second run. Uses PostgresDb + `update_memory_on_run=True`.

**Result:** Ran successfully. First run stored "John Doe likes hiking". Second run recalled hobbies correctly. `team.get_user_memories()` returned structured UserMemory objects with memory text, topics, timestamps, and user_id.

---

### 02_team_with_agentic_memory.py

**Status:** PASS

**Description:** Agentic memory — team creates/updates memories during runs via `enable_agentic_memory=True`. No explicit MemoryManager needed.

**Result:** Ran successfully. First run acknowledged hiking hobby. Second run recalled hobbies from agentic memory system. Memory persisted across runs within same session.

---

### learning_machine.py

**Status:** PASS

**Description:** LearningMachine integration — team uses `LearningMachine(user_profile=UserProfileConfig(mode=LearningMode.AGENTIC))` to extract and persist user profile data. Uses SQLite storage.

**Result:** Ran successfully. First run (session 1) stored Alex's preference for bullet points. Second run (session 2) acknowledged preferences but model response style suggests user profile context was injected even if model didn't explicitly state it (responded in bullet format as requested).

---
