# Implement `cookbook/11_memory/` Restructuring

You are restructuring the `cookbook/11_memory/` directory of the Agno AI agent framework. The full plan is attached as `RESTRUCTURE_PLAN.md`. Read it completely before starting.

## Context

- **Agno** is a Python AI agent framework. The `cookbook/` directory contains runnable example scripts.
- Memory scripts demonstrate memory persistence, sharing, and management using Agno's `MemoryManager` API.
- The goal is to consolidate 20 files down to 15 by moving 5 SurrealDB files to `cookbook/92_integrations/surrealdb/`, achieving 100% style compliance, and adding documentation.
- The virtual environment for running cookbooks is at `.venvs/demo/bin/python`.
- The style checker is at `cookbook/scripts/check_cookbook_pattern.py`.

## CRITICAL: Read Each File Before Modifying

**Do NOT apply blanket changes across files.** Every file has unique memory configurations, test sequences, and agent setups. You must:

1. **Read each file individually** before making any changes.
2. **Understand what the file does** — its memory configuration, DB setup, agent definitions, and test sequence.
3. **Preserve the existing logic exactly** — only restructure the layout (add banners, docstring, main gate).
4. **For MERGE operations**, read ALL source files first, then combine thoughtfully.

## CRITICAL: SurrealDB Files Move to Integrations

The `memory_manager/surrealdb/` directory does NOT belong in the memory section. These files demonstrate SurrealDB as a database integration, not a core memory feature. Move all 5 SurrealDB files to `cookbook/92_integrations/surrealdb/`. Do NOT merge them into the parent memory_manager files.

## Style Guide Template

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

### Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Setup (DB) → Create Agent/MemoryManager → Run
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere
7. **Self-contained** — Each file must be independently runnable

## Execution Plan

### Phase 1: Move 5 SurrealDB Files to Integrations

Move all files from `memory_manager/surrealdb/` to `cookbook/92_integrations/surrealdb/`:

```bash
mkdir -p cookbook/92_integrations/surrealdb
mv cookbook/11_memory/memory_manager/surrealdb/standalone_memory_surreal.py cookbook/92_integrations/surrealdb/
mv cookbook/11_memory/memory_manager/surrealdb/memory_creation.py cookbook/92_integrations/surrealdb/
mv cookbook/11_memory/memory_manager/surrealdb/custom_memory_instructions.py cookbook/92_integrations/surrealdb/
mv cookbook/11_memory/memory_manager/surrealdb/memory_search_surreal.py cookbook/92_integrations/surrealdb/
mv cookbook/11_memory/memory_manager/surrealdb/db_tools_control.py cookbook/92_integrations/surrealdb/
rmdir cookbook/11_memory/memory_manager/surrealdb
```

The moved files will be style-fixed as part of the `cookbook/92_integrations/` restructuring. Do NOT style-fix them here.

### Phase 2: Style Fixes (all 15 surviving files)

Work through the RESTRUCTURE_PLAN.md Section 3 directory by directory. For each file:
1. Read the file
2. Add module docstring if missing
3. Add section banners
4. Add `if __name__ == "__main__":` gate if missing
5. Do NOT change memory configurations or test sequences

### Phase 3: Create README.md and TEST_LOG.md

Update existing READMEs to reflect SurrealDB merge. Create TEST_LOG.md for all directories:

```markdown
# Test Log: <directory_name>

> Tests not yet run. Run each file and update this log.

### <filename>.py

**Status:** PENDING

**Description:** <what the file does>

---
```

### Phase 4: Validate

```bash
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/11_memory
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/11_memory/memory_manager
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/11_memory/optimize_memories
```

## Important Notes

1. **Read before writing** — Do not apply changes to files you haven't read.
2. **Preserve memory configs** — Do not change `update_memory_on_run`, `add_history_to_context`, memory strategies, or test message sequences.
3. **Preserve DB connection details** — Do not change PostgreSQL URLs.
4. **MemoryManager files are different** — Files in `memory_manager/` use the MemoryManager API directly (not through Agent). They have different patterns from root-level files.
5. **SurrealDB goes to integrations** — Do NOT merge SurrealDB files into memory_manager. Move them to `cookbook/92_integrations/surrealdb/`.
5. **No `__init__.py` files** — Cookbook directories don't use `__init__.py`.
6. **75 dashes** — `# ---------------------------------------------------------------------------` (75 dashes after `# `).
7. **Read the plan carefully** — Follow the RESTRUCTURE_PLAN.md for every decision.
