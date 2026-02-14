# Test Log: memory_manager

**Date:** 2026-02-11
**Environment:** `.venvs/demo/bin/python`
**Model:** gpt-4o, gpt-4o-mini, claude-sonnet-4-5-20250929
**Services:** pgvector, sqlite

## Structure Check

**Result:** Checked 5 file(s). Violations: 0
**Details:** Clean

---

## Runtime Results

### 01_standalone_memory.py

**Status:** PASS
**Time:** ~3s
**Description:** Standalone MemoryManager CRUD: add, get, delete, replace user memories via PostgresDb.
**Output:** All operations succeeded. Memories created, listed, deleted, and replaced correctly.
**Triage:** n/a

---

### 02_memory_creation.py

**Status:** PASS
**Time:** ~15s
**Description:** Create user memories from direct text and from message history using MemoryManager with OpenAI model.
**Output:** Memories created from raw text (John Doe) and from message list (Jane Doe) successfully.
**Triage:** n/a

---

### 03_custom_memory_instructions.py

**Status:** PASS
**Time:** ~35s
**Description:** Custom memory capture instructions with two different models. First manager uses OpenAI with academic-only instructions, second uses Claude for default capture.
**Output:** Both memory managers created memories correctly. John Doe and Jane Doe memories stored and retrieved with proper topic tagging.
**Triage:** regression (fixed in v25-fixes)
**Fix:** Changed `claude-3-5-sonnet-latest` to `claude-sonnet-4-5-20250929`.
**Re-verified:** 2026-02-14 — model ID update confirmed working, both OpenAI and Claude memory managers produce correct results.

---

### 04_memory_search.py

**Status:** PASS
**Time:** ~12s
**Description:** Search user memories using `last_n`, `first_n`, and `agentic` retrieval methods.
**Output:** All three retrieval methods returned correct results. Agentic search used model to select relevant memories.
**Triage:** n/a

---

### 05_db_tools_control.py

**Status:** PASS
**Time:** ~20s
**Description:** Agent with agentic memory using SQLite and controlled DB tool flags (add_memories, update_memories). Tests create, query, and update memory flows.
**Output:** Agent created memories, recalled hobbies, and updated preferences (photography -> rock climbing).
**Triage:** n/a

---

## Summary

| File | Status | Triage | Notes |
|------|--------|--------|-------|
| `01_standalone_memory.py` | PASS | n/a | ~3s |
| `02_memory_creation.py` | PASS | n/a | ~15s |
| `03_custom_memory_instructions.py` | PASS | regression (fixed) | Changed claude-3-5-sonnet-latest to claude-sonnet-4-5-20250929 |
| `04_memory_search.py` | PASS | n/a | ~12s |
| `05_db_tools_control.py` | PASS | n/a | ~20s, SQLite |

**Totals:** 5 PASS, 0 FAIL, 0 SKIP, 0 ERROR
