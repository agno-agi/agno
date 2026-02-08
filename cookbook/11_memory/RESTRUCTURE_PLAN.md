# Restructuring Plan: `cookbook/11_memory/`

## 1. Executive Summary

### Current State

| Metric | Value |
|--------|-------|
| Directories | 3 (root, memory_manager, optimize_memories) |
| Total `.py` files (non-`__init__`) | 20 (including 5 SurrealDB files to relocate) |
| Fully style-compliant | 0 (~0%) |
| Have module docstring | 18 (~90%) |
| Have section banners | 0 (0%) |
| Have `if __name__` gate | 4 (20%) |
| Contain emoji | 0 (0%) |
| Subdirectories with README.md | 2 / 4 |
| Subdirectories with TEST_LOG.md | 0 / 4 |

### Key Problems

1. **SurrealDB misplacement.** `memory_manager/surrealdb/` contains 5 files demonstrating SurrealDB as a MemoryManager backend. These are integration examples, not core memory features — they belong in `cookbook/92_integrations/surrealdb/`.

2. **No section banners.** Zero files use any form of section banner.

3. **No main gate on most files.** Only 4/20 files (20%) have `if __name__ == "__main__":`.

4. **No TEST_LOG.md anywhere.** Zero directories have test logs.

5. **Missing docstrings.** 2 files lack docstrings: `07_share_memory_and_history_between_agents.py` and `memory_manager/01_standalone_memory.py`.

### Overall Assessment

Small, well-organized section. The SurrealDB examples are integration demos and should be relocated to `cookbook/92_integrations/surrealdb/`. Otherwise, this is a style compliance task.

### Proposed Target

| Metric | Current | Target |
|--------|---------|--------|
| Files | 20 | 15 |
| Style compliance | 0% | 100% |
| README coverage | 2/4 | All surviving directories |
| TEST_LOG coverage | 0/4 | All surviving directories |

---

## 2. Proposed Directory Structure

Move the SurrealDB subdirectory to `cookbook/92_integrations/surrealdb/`. Keep memory_manager/ files as PostgreSQL-only.

```
cookbook/11_memory/
├── 01_agent_with_memory.py                  # Basic memory persistence
├── 02_agentic_memory.py                     # Agent-driven memory updates
├── 03_agents_share_memory.py                # Shared memory across agents
├── 04_custom_memory_manager.py              # Custom MemoryManager implementation
├── 05_multi_user_multi_session_chat.py      # Multi-user sessions
├── 06_multi_user_multi_session_chat_concurrent.py  # Concurrent multi-user
├── 07_share_memory_and_history_between_agents.py   # Memory + history sharing
├── 08_memory_tools.py                       # Memory tools integration
├── memory_manager/                          # Direct MemoryManager API (PostgreSQL)
│   ├── 01_standalone_memory.py              # CRUD operations
│   ├── 02_memory_creation.py                # Memory from messages
│   ├── 03_custom_memory_instructions.py     # Custom capture instructions
│   ├── 04_memory_search.py                  # Memory retrieval
│   └── 05_db_tools_control.py               # Fine-grained operation control
└── optimize_memories/                       # Memory optimization strategies
    ├── 01_memory_summarize_strategy.py      # Summarize strategy
    └── 02_custom_memory_strategy.py         # Custom strategy
```

### Changes from Current

| Change | Details |
|--------|---------|
| **MOVE** `memory_manager/surrealdb/` | Move 5 SurrealDB files to `cookbook/92_integrations/surrealdb/`. Remove subdirectory from 11_memory |

---

## 3. File Disposition Table

### Root Level (8 → 8, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `01_agent_with_memory.py` | **KEEP + FIX** | Add banners, main gate |
| `02_agentic_memory.py` | **KEEP + FIX** | Add banners, main gate |
| `03_agents_share_memory.py` | **KEEP + FIX** | Add banners, main gate |
| `04_custom_memory_manager.py` | **KEEP + FIX** | Add banners, main gate |
| `05_multi_user_multi_session_chat.py` | **KEEP + FIX** | Add banners. Already has main gate |
| `06_multi_user_multi_session_chat_concurrent.py` | **KEEP + FIX** | Add banners. Already has main gate |
| `07_share_memory_and_history_between_agents.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `08_memory_tools.py` | **KEEP + FIX** | Add banners. Already has main gate |

---

### `memory_manager/` (10 → 5, relocate SurrealDB)

| File | Disposition | Rationale |
|------|------------|-----------|
| `01_standalone_memory.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `02_memory_creation.py` | **KEEP + FIX** | Add banners, main gate |
| `03_custom_memory_instructions.py` | **KEEP + FIX** | Add banners, main gate |
| `04_memory_search.py` | **KEEP + FIX** | Add banners, main gate |
| `05_db_tools_control.py` | **KEEP + FIX** | Add banners, main gate |
| `surrealdb/standalone_memory_surreal.py` | **MOVE TO** `92_integrations/surrealdb/` | SurrealDB is an integration, not a core memory feature |
| `surrealdb/memory_creation.py` | **MOVE TO** `92_integrations/surrealdb/` | Same |
| `surrealdb/custom_memory_instructions.py` | **MOVE TO** `92_integrations/surrealdb/` | Same |
| `surrealdb/memory_search_surreal.py` | **MOVE TO** `92_integrations/surrealdb/` | Same |
| `surrealdb/db_tools_control.py` | **MOVE TO** `92_integrations/surrealdb/` | Same |

After moving, delete the `memory_manager/surrealdb/` directory. The moved files will be style-fixed as part of `cookbook/92_integrations/` restructuring.

---

### `optimize_memories/` (2 → 2, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `01_memory_summarize_strategy.py` | **KEEP + FIX** | Add banners, main gate |
| `02_custom_memory_strategy.py` | **KEEP + FIX** | Add banners. Already has main gate |

---

## 4. New Files Needed

No new files needed.

---

## 5. Missing READMEs and TEST_LOGs

| Directory | README.md | TEST_LOG.md |
|-----------|-----------|-------------|
| `11_memory/` (root) | EXISTS (update) | **MISSING** |
| `memory_manager/` | EXISTS (update after SurrealDB move) | **MISSING** |
| `optimize_memories/` | **MISSING** | **MISSING** |

---

## 6. Recommended Cookbook Template

```python
"""
<Feature Name>
=============================

Demonstrates <what this file teaches> using Agno memory.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory.manager import MemoryManager
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    update_memory_on_run=True,
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("My name is John and I live in NYC")
    memories = agent.get_user_memories()
    print(f"Memories: {memories}")
```

### Template Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Setup (DB) → Create Agent/MemoryManager → Run
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere
7. **Self-contained** — Each file must be independently runnable
