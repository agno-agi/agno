# Implement `cookbook/93_components/` Restructuring

You are restructuring the `cookbook/93_components/` directory of the Agno AI agent framework. The full plan is attached as `RESTRUCTURE_PLAN.md`. Read it completely before starting.

## Context

- **Agno** is a Python AI agent framework. The `cookbook/` directory contains runnable example scripts.
- This is the **smallest cookbook section** with only 14 files across 2 directories.
- The goal is to delete 2 `__init__.py` files, achieve 100% style compliance, fix 3 incorrect/missing docstrings, and add documentation.
- No merges needed — all files are unique.
- The virtual environment for running cookbooks is at `.venvs/demo/bin/python`.
- The style checker is at `cookbook/scripts/check_cookbook_pattern.py`.

## CRITICAL: Read Each File Before Modifying

**Do NOT apply blanket changes across files.** Each file uses specific storage configurations, model classes, and patterns. You must:

1. **Read each file individually** before making any changes.
2. **Understand what the file does** — its storage backend, model, and feature demonstrated.
3. **Preserve the existing logic exactly** — only restructure the layout (add banners, docstring, main gate).

## CRITICAL: Do NOT Change Component Logic

Each file uses **specific database configurations, model classes, and Registry patterns**. Do NOT:
- Change database connection strings or storage configurations
- Change model imports or model IDs
- Change Registry registrations or AgentOS configurations
- Remove or modify workflow step definitions
- Change prompts or task descriptions

## Style Guide Template

```python
"""
<Title>
=============================

Demonstrates <what this demonstrates>.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://..."

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(...)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.save()
```

### Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Setup → Create Agent/Workflow → Run Agent/Workflow (or Save/Load)
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere (none present in this section)
7. **Preserve component logic** — Do NOT change DB configs, models, Registry, or workflow steps
8. **Self-contained** — Each file must be independently runnable

## Execution Plan

### Phase 1: Delete All `__init__.py` Files (2 files)

```bash
find cookbook/93_components -name "__init__.py" -delete
```

### Phase 2: Fix Incorrect Docstrings (3 files)

1. **`get_team.py`** — Change "save a team" to "load a team from the database by ID"
2. **`get_workflow.py`** — Change "get an agent" to "load a workflow from the database by ID"
3. **`save_workflow.py`** — Add missing module docstring

### Phase 3: Style Fixes on All Files (14 files)

For all files:
1. Read the file
2. Add/reformat module docstring with title + `=====` underline
3. Add section banners (`# ---------------------------------------------------------------------------`, 75 dashes)
4. Add `if __name__ == "__main__":` gate if missing (7 files need this)
5. Do NOT change component logic, DB configs, or model IDs

**Files needing main gate added (7 files):**
- `get_agent.py`
- `get_team.py`
- `get_workflow.py`
- `registry.py`
- `save_agent.py`
- `save_team.py`
- `save_workflow.py`

**Files that already have main gates (7 files):**
- `agent_os_registry.py`
- `demo.py`
- `workflows/save_conditional_steps.py`
- `workflows/save_custom_steps.py`
- `workflows/save_loop_steps.py`
- `workflows/save_parallel_steps.py`
- `workflows/save_router_steps.py`

**Work through files in this order:**
1. Root files (9 files, alphabetical)
2. workflows/ files (5 files, alphabetical)

### Phase 4: Fix README.md

Update the existing `cookbook/93_components/README.md` to fix path references from `cookbook/16_components/` to `cookbook/93_components/`.

### Phase 5: Create Missing Documentation

- **README.md needed:** `workflows/`
- **TEST_LOG.md needed:** Both `93_components/` and `workflows/`

### Phase 6: Validate

```bash
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/93_components --recursive
```

## Important Notes

1. **Read before writing** — Do not apply changes to files you haven't read.
2. **Preserve component logic** — This is the most important rule. Every file uses specific DB and Registry configurations.
3. **Save/get pairs are intentional** — `save_agent.py` and `get_agent.py` demonstrate separate workflows. Do NOT merge them.
4. **Workflow files use Registry** — The `workflows/` files register custom functions (executors, conditions, selectors) in the Registry for deserialization. Preserve these registrations exactly.
5. **No `__init__.py` files** — Cookbook directories don't use `__init__.py`.
6. **75 dashes** — `# ---------------------------------------------------------------------------` (75 dashes after `# `).
7. **Fix the README path** — Change `cookbook/16_components/` references to `cookbook/93_components/`.
8. **Fix the 3 docstrings** — `get_team.py`, `get_workflow.py` have wrong descriptions; `save_workflow.py` is missing one entirely.
