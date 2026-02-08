# Restructuring Plan: `cookbook/93_components/`

## 1. Executive Summary

### Current State

| Metric | Value |
|--------|-------|
| Directories | 2 (root + workflows/) |
| Total `.py` files (non-`__init__`) | 14 |
| `__init__.py` files (to remove) | 2 |
| Fully style-compliant | 0 (0%) |
| Have module docstring | 13 (~93%) |
| Have section banners | 0 (0%) |
| Have `if __name__` gate | 7 (50%) |
| Contain emoji | 0 |
| Directories with README.md | 1 / 2 |
| Directories with TEST_LOG.md | 0 / 2 |

### Key Problems

1. **Zero section banners.** No file has the required `# ---------------------------------------------------------------------------` style banners.

2. **50% missing main gates.** 7 of 14 files lack `if __name__ == "__main__":` gates — all the root-level save/get/registry files run code at module level.

3. **2 incorrect docstrings.** `get_team.py` says "save a team" instead of "get a team". `get_workflow.py` says "get an agent" instead of "get a workflow".

4. **1 missing docstring.** `save_workflow.py` has no module docstring.

5. **2 unnecessary `__init__.py` files.** Cookbook directories should not have `__init__.py`.

6. **No TEST_LOG.md.** Neither directory has test logs.

7. **README.md path error.** The existing README.md references `cookbook/16_components/` instead of `cookbook/93_components/`.

### Overall Assessment

The smallest cookbook section at 14 files. All files demonstrate agent/team/workflow serialization (save to DB, load from DB) and the Registry pattern for non-serializable components. The `workflows/` subdirectory has 5 files showing different workflow step types (conditional, custom, loop, parallel, router). No merges needed — every file is unique. The main work is style standardization and fixing incorrect docstrings.

### Proposed Target

| Metric | Current | Target |
|--------|---------|--------|
| Files (non-`__init__`) | 14 | 14 |
| `__init__.py` files | 2 | 0 |
| Style compliance | 0% | 100% |
| README coverage | 1/2 | All directories |
| TEST_LOG coverage | 0/2 | All directories |

---

## 2. Proposed Directory Structure

Keep the current structure. No reorganization needed.

```
cookbook/93_components/
├── agent_os_registry.py       # AgentOS with Registry
├── demo.py                    # AgentOS demo with all features
├── get_agent.py               # Load agent from DB
├── get_team.py                # Load team from DB
├── get_workflow.py            # Load workflow from DB
├── registry.py                # Registry for non-serializable components
├── save_agent.py              # Save agent to DB
├── save_team.py               # Save team to DB
├── save_workflow.py           # Save workflow to DB
└── workflows/                 # Workflow step type examples
    ├── save_conditional_steps.py  # Conditional workflow steps
    ├── save_custom_steps.py       # Custom executor steps
    ├── save_loop_steps.py         # Loop workflow steps
    ├── save_parallel_steps.py     # Parallel workflow steps
    └── save_router_steps.py       # Router workflow steps
```

---

## 3. File Disposition Table

### Phase 1: Delete `__init__.py` Files (2 files)

| File | Action |
|------|--------|
| `93_components/__init__.py` | DELETE |
| `workflows/__init__.py` | DELETE |

### Phase 2: No Merges Needed

All 14 files are unique. The save/get pairs are intentional — they demonstrate separate save and load workflows.

### Phase 3: Style Fixes on All Files (14 files)

#### Root Files (9 files — all KEEP+FIX)

| File | Docstring | Main Gate | Notes | Demonstrates |
|------|:---------:|:---------:|-------|-------------|
| `agent_os_registry.py` | REFORMAT | HAS | | AgentOS with Registry serving app |
| `demo.py` | REFORMAT | HAS | | Full AgentOS demo with all features |
| `get_agent.py` | REFORMAT | ADD | | Load agent from DB by ID |
| `get_team.py` | FIX | ADD | Wrong docstring ("save a team") | Load team from DB by ID |
| `get_workflow.py` | FIX | ADD | Wrong docstring ("get an agent") | Load workflow from DB by ID |
| `registry.py` | REFORMAT | ADD | | Registry for non-serializable components |
| `save_agent.py` | REFORMAT | ADD | | Save agent to DB with versioning |
| `save_team.py` | REFORMAT | ADD | | Save team with member agents to DB |
| `save_workflow.py` | ADD | ADD | Missing docstring entirely | Save workflow with steps to DB |

#### workflows/ Files (5 files — all KEEP+FIX)

| File | Docstring | Main Gate | Demonstrates |
|------|:---------:|:---------:|-------------|
| `save_conditional_steps.py` | REFORMAT | HAS | Conditional workflow steps with Condition evaluator |
| `save_custom_steps.py` | REFORMAT | HAS | Custom executor functions in workflow |
| `save_loop_steps.py` | REFORMAT | HAS | Loop steps with end_condition function |
| `save_parallel_steps.py` | REFORMAT | HAS | Parallel execution steps |
| `save_router_steps.py` | REFORMAT | HAS | Router steps with selector function |

### Docstring Fixes

**`get_team.py`** — Current: "This cookbook demonstrates how to save a team..." → Fix: "This cookbook demonstrates how to load a team from the database by ID."

**`get_workflow.py`** — Current: "This cookbook demonstrates how to get an agent..." → Fix: "This cookbook demonstrates how to load a workflow from the database by ID."

**`save_workflow.py`** — Currently missing. Add docstring about saving a workflow to the database.

---

## 4. Reduction Summary

| Category | Files Removed | Method |
|----------|--------------|--------|
| `__init__.py` deletion | 2 | Delete |
| **Total removed** | **2** | |
| **Final file count** | **14** | (unchanged, only __init__.py removed) |

---

## 5. Missing Documentation

### README.md Status

| Directory | Has README.md | Action |
|-----------|:------------:|--------|
| `93_components/` | YES | UPDATE (fix path references) |
| `workflows/` | NO | CREATE |

### TEST_LOG.md Status

Both directories need TEST_LOG.md created.

### README.md Fixes

The existing README.md references `cookbook/16_components/` in examples. Update all path references to `cookbook/93_components/`.

---

## 6. Recommended Template

### Save Pattern

```python
"""
Save <Entity> to Database
=============================

Demonstrates creating and saving <an entity> to the database with versioning.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.postgres import PostgresStorage

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://..."
storage = PostgresStorage(table_name="...", db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    storage=storage,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.save()
    print(f"Saved agent: {agent.agent_id}")
```

### Get Pattern

```python
"""
Load <Entity> from Database
=============================

Demonstrates loading <an entity> from the database by ID and running it.
"""

from agno.agent import Agent
from agno.storage.postgres import PostgresStorage

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://..."
storage = PostgresStorage(table_name="...", db_url=db_url)

# ---------------------------------------------------------------------------
# Load and Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent = Agent.from_storage(agent_id="...", storage=storage)
    agent.print_response("...", stream=True)
```

### Workflow Save Pattern

```python
"""
Save <StepType> Workflow Steps
=============================

Demonstrates creating a workflow with <step type> steps, saving it
to the database, and loading it back with Registry.

1. Creates workflow with <step type> steps
2. Saves to database
3. Loads from database using Registry
4. Runs the loaded workflow
"""

from agno.agent import Agent
from agno.workflow import Workflow

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# ... step-specific setup ...

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(...)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    workflow.save()
    # ... load and run ...
```

---

## 7. Validation

```bash
# Run on entire section
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/93_components --recursive
```
