# Implement `cookbook/04_workflows/` Restructuring

You are restructuring the `cookbook/04_workflows/` directory of the Agno AI agent framework. The full plan is attached as `RESTRUCTURE_PLAN.md`. Read it completely before starting.

## Context

- **Agno** is a Python AI agent framework. The `cookbook/` directory contains runnable example scripts.
- The goal is to consolidate ~126 files down to ~72 files by flattening sync/async/stream directory splits, merging redundant variants, cutting trivial files, and adding new examples.
- Every surviving file must comply with the style guide (see Template section below).
- The virtual environment for running cookbooks is at `.venvs/demo/bin/python`.
- The style checker is at `cookbook/scripts/check_cookbook_pattern.py`.

## CRITICAL: Read Each File Before Modifying

**Do NOT apply blanket changes across files using batch scripts or regex-based rewrites.** Every file in this cookbook has unique workflow configurations, step definitions, agent setups, condition evaluators, selectors, and logic. You must:

1. **Read each file individually** before making any changes to it.
2. **Understand what the file does** — its workflow configuration, step definitions, agents, conditions, selectors, session state usage, and run logic.
3. **Preserve the existing logic exactly** — only restructure the layout (add banners, docstring, main gate). Do not change model names, step configurations, condition evaluators, or workflow parameters that already exist in the file.
4. **For MERGE operations**, read ALL source files first, then combine their unique content thoughtfully. Don't just concatenate.
5. **For REWRITE operations**, read the existing file first to understand the workflow/step config, then rebuild from scratch following the template while keeping the same configuration.

This is a careful, file-by-file task. It will take time. Do not rush it.

## Style Guide Template

Every `.py` file must follow this exact structure:

```python
"""
<Feature Name>
=============================

Demonstrates <what this file teaches> using Agno Workflows.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.workflow import Workflow
from agno.workflow.step import Step

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=["Research the topic thoroughly."],
)

writer = Agent(
    name="Writer",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=["Write a clear summary."],
)

# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
research_step = Step(agent=researcher, name="Research")
write_step = Step(agent=writer, name="Write")

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Research Pipeline",
    steps=[research_step, write_step],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Sync execution
    workflow.print_response("Explain quantum computing", stream=True)

    # Async execution (when demonstrating both patterns)
    # import asyncio
    # asyncio.run(workflow.aprint_response("Explain quantum computing", stream=True))
```

### Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Create Agents (if needed) → Define Steps → Create Workflow → Run Workflow
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere
7. **Sync + async together** — When merging sync/async variants, show both in the same file using labeled sections within the `if __name__` block
8. **Self-contained** — Each file must be independently runnable

## Execution Plan

Execute in this exact order. Each phase must complete before the next starts.

### Phase 1: Create New Directory Structure

The main structural change is **flattening**: removing all `sync/` and `async/` subdirectories, and renaming directories to drop leading `_0N_` prefixes.

```
# New top-level directories (rename from _0N_ prefixed originals)
mv cookbook/04_workflows/_01_basic_workflows cookbook/04_workflows/01_basic_workflows
mv cookbook/04_workflows/_02_workflows_conditional_execution cookbook/04_workflows/02_conditional_execution
mv cookbook/04_workflows/_03_workflows_loop_execution cookbook/04_workflows/03_loop_execution
mv cookbook/04_workflows/_04_workflows_parallel_execution cookbook/04_workflows/04_parallel_execution
mv cookbook/04_workflows/_05_workflows_conditional_branching cookbook/04_workflows/05_conditional_branching
mv cookbook/04_workflows/_06_advanced_concepts cookbook/04_workflows/06_advanced_concepts
mv cookbook/04_workflows/_07_cel_expressions cookbook/04_workflows/07_cel_expressions

# Rename nested directories under 01_basic_workflows
mv 01_basic_workflows/_01_sequence_of_steps 01_basic_workflows/01_sequence_of_steps
mv 01_basic_workflows/_02_step_with_function 01_basic_workflows/02_step_with_function
mv 01_basic_workflows/_03_function_instead_of_steps 01_basic_workflows/03_function_workflows

# Rename nested directories under 06_advanced_concepts (drop _0N_ prefixes, shorten names)
mv 06_advanced_concepts/_01_structured_io_at_each_level 06_advanced_concepts/structured_io
mv 06_advanced_concepts/_02_early_stopping 06_advanced_concepts/early_stopping
mv 06_advanced_concepts/_03_access_previous_step_outputs 06_advanced_concepts/previous_step_outputs
mv 06_advanced_concepts/_04_shared_session_state 06_advanced_concepts/session_state
mv 06_advanced_concepts/_05_background_execution 06_advanced_concepts/background_execution
mv 06_advanced_concepts/_06_guardrails 06_advanced_concepts/guardrails
mv 06_advanced_concepts/_07_workflow_history 06_advanced_concepts/history
mv 06_advanced_concepts/_08_workflow_agent 06_advanced_concepts/workflow_agent
mv 06_advanced_concepts/_09_long_running_workflows 06_advanced_concepts/long_running

# Create new directories
mkdir -p cookbook/04_workflows/06_advanced_concepts/run_control
mkdir -p cookbook/04_workflows/06_advanced_concepts/tools
```

**Important:** Do the renames first, then work with the new paths for the rest of the phases.

### Phase 2: Execute File Dispositions (file by file)

Work through the RESTRUCTURE_PLAN.md Section 3 ("File Disposition Table") directory by directory.

**For each file, you MUST:**
1. Read the file completely
2. Understand its purpose, workflow/step config, agents, conditions, and selectors
3. Apply the disposition (CUT, MERGE, REWRITE, KEEP+FIX, etc.)
4. Verify the result preserves the original behavior

#### The sync/async/stream flattening pattern

This is the dominant restructuring operation. Most directories have this structure:
```
directory/
  sync/
    file.py
    file_stream.py
  async/
    file.py
    file_stream.py
```

For each such set:
1. Read ALL variants (sync base, async base, sync stream, async stream)
2. Use the sync base as the foundation
3. Add streaming as a section within the `if __name__` block
4. Add async as a section within the `if __name__` block
5. Write the unified file to the parent directory (not inside sync/ or async/)
6. Delete all source files and the empty sync/ and async/ subdirectories

#### CUT files
Delete files marked as **CUT**. Do this first per directory.

#### MERGE files
For files marked **MERGE INTO**:
1. Read ALL source files that will be merged
2. Identify the unique content in each (don't just look at the diff — understand the feature)
3. Combine into the target file, keeping all unique functionality
4. For sync/async variants: use labeled sections (`# --- Sync ---`, `# --- Async ---`) within the `if __name__` block
5. Delete the source files after merging

#### REWRITE files
For files marked **REWRITE**:
1. Read the existing file to understand its workflow/step configuration
2. Rebuild from scratch following the template
3. Keep the exact same workflow name, step definitions, agents, conditions, selectors, and instructions
4. Only change the structure/layout to match the style guide

#### KEEP + FIX files
For files marked **KEEP + FIX**:
1. Read the file
2. Add module docstring if missing
3. Move imports above first banner
4. Add section banners (`# ---------------------------------------------------------------------------`)
5. Add `if __name__ == "__main__":` gate if missing
6. Remove emoji if present
7. Do NOT change the workflow/step logic or configuration

#### KEEP + MOVE + FIX / KEEP + RENAME + FIX files
Move or rename the file as specified, then apply the same style fixes as KEEP + FIX.

### Phase 3: Create New Files

Create the 4 new files listed in RESTRUCTURE_PLAN.md Section 4. For each:

1. Follow the style guide template exactly
2. Use the feature descriptions in the plan to write meaningful examples
3. Look at the Agno source code in `libs/agno/agno/` to understand the APIs:
   - `libs/agno/agno/workflow/workflow.py` for Workflow class features
   - `libs/agno/agno/workflow/step.py` for Step class features
   - `libs/agno/agno/agent/agent.py` for Agent class features
4. Each file must be independently runnable
5. Use `OpenAIResponses(id="gpt-5.2")` as the default model

### Phase 4: Clean Up Empty Directories

After all file operations, remove empty `sync/` and `async/` subdirectories throughout:
```
# Under 01_basic_workflows/
rmdir 01_basic_workflows/01_sequence_of_steps/sync
rmdir 01_basic_workflows/01_sequence_of_steps/async
rmdir 01_basic_workflows/02_step_with_function/sync
rmdir 01_basic_workflows/02_step_with_function/async
rmdir 01_basic_workflows/03_function_workflows/sync
rmdir 01_basic_workflows/03_function_workflows/async

# Under main dirs
rmdir 02_conditional_execution/sync
rmdir 02_conditional_execution/async
rmdir 03_loop_execution/sync
rmdir 03_loop_execution/async
rmdir 04_parallel_execution/sync
rmdir 04_parallel_execution/async
rmdir 05_conditional_branching/sync
rmdir 05_conditional_branching/async

# Under 06_advanced_concepts
rmdir 06_advanced_concepts/workflow_agent/sync
rmdir 06_advanced_concepts/workflow_agent/async

# Dissolved directory
rm -rf 06_advanced_concepts/_10_other   # should be empty after redistribution
```

Also remove any leftover old-name directories if the renames left empties.

### Phase 5: Create README.md and TEST_LOG.md

For every surviving subdirectory under `cookbook/04_workflows/`:

**README.md** — Short description of the directory's scope, list of files with one-line descriptions, and prerequisites (API keys, services needed).

**TEST_LOG.md** — Create with this placeholder template:
```markdown
# Test Log: <directory_name>

> Tests not yet run. Run each file and update this log.

### <filename>.py

**Status:** PENDING

**Description:** <what the file does>

---
```

### Phase 6: Validate

Run the structure checker on each subdirectory:
```bash
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/04_workflows/<subdir>
```

Fix any violations. All files must pass.

## Key Merge Examples

### Example: Flattening sync/async/stream (sequence of steps)

Before: 4 files in separate subdirectories
- `sync/sequence_of_steps.py`
- `sync/sequence_of_steps_stream.py`
- `async/sequence_of_steps.py`
- `async/sequence_of_steps_stream.py`

After: 1 file in parent directory (`01_sequence_of_steps/sequence_of_steps.py`):

```python
"""
Sequence of Steps
=============================

Demonstrates sequential step execution using Agno Workflows.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.workflow import Workflow
from agno.workflow.step import Step

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=["Research the topic thoroughly."],
)

writer = Agent(
    name="Writer",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=["Write a clear summary."],
)

# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
research_step = Step(agent=researcher, name="Research")
write_step = Step(agent=writer, name="Write")

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Research Pipeline",
    steps=[research_step, write_step],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    workflow.print_response("Explain quantum computing")

    # --- Sync Streaming ---
    workflow.print_response("Explain quantum computing", stream=True)

    # --- Async ---
    asyncio.run(workflow.aprint_response("Explain quantum computing"))

    # --- Async Streaming ---
    asyncio.run(workflow.aprint_response("Explain quantum computing", stream=True))
```

### Example: Dissolving _10_other/ (redistribution)

Before: 7 files in `_06_advanced_concepts/_10_other/`

After: Files redistributed to where they belong:
- `workflow_tools.py` → `06_advanced_concepts/tools/workflow_tools.py`
- `stream_executor_events.py` → `06_advanced_concepts/run_control/executor_events.py`
- `workflow_cancel_a_run.py` → `06_advanced_concepts/run_control/cancel_run.py`
- `workflow_metrics_on_run_response.py` → `06_advanced_concepts/run_control/metrics.py`
- `store_events_and_events_to_skip_in_a_workflow.py` → `06_advanced_concepts/run_control/event_storage.py`
- `rename_workflow_session.py` → `06_advanced_concepts/session_state/rename_session.py`
- `workflow_with_image_input.py` → `06_advanced_concepts/structured_io/image_input.py`

Each moved file gets style fixes (docstring, banners, main gate) but preserves its original workflow logic.

### Example: Merging numbered variants (structured_io functions)

Before: 3 files (`structured_io_at_each_level_function.py`, `_1.py`, `_2.py`)

After: 1 file (`06_advanced_concepts/structured_io/structured_io_function.py`) with all unique variants as labeled sections within the `if __name__` block.

## Important Notes

1. **Read before writing** — This is the most important rule. Do not apply changes to files you haven't read. Every file has unique content that must be understood and preserved.
2. **Preserve workflow/step logic** — When merging or rewriting, keep the exact same workflow configurations (steps, agents, conditions, selectors, session_state usage). Don't invent new behavior.
3. **Use existing imports** — Look at the source files to understand which Agno modules to import. Don't guess API signatures.
4. **Default model** — For new files, use `OpenAIResponses(id="gpt-5.2")` from `agno.models.openai`.
5. **No `__init__.py` files** — Cookbook directories don't use `__init__.py`.
6. **75 dashes** — The banner separator is exactly `# ---------------------------------------------------------------------------` (75 dashes after `# `).
7. **Read the plan carefully** — The RESTRUCTURE_PLAN.md has detailed rationale for every decision. When in doubt, follow the plan.
8. **Directory renames** — All directories are being renamed (dropping `_0N_` prefixes, shortening names). Do the renames in Phase 1, then use the new paths for all subsequent work.
9. **sync/async flattening** — This is the dominant operation. Files move from `sync/` and `async/` subdirectories into their parent. The `sync/` and `async/` directories are deleted after all files are processed.
10. **_10_other/ dissolution** — Files from `_06_advanced_concepts/_10_other/` are redistributed to `run_control/`, `session_state/`, `structured_io/`, and `tools/`. Track these cross-directory moves carefully.
11. **CEL expressions** — The 14 files in `07_cel_expressions/` are all unique and only need style fixes (banners, docstring). Do not change the CEL expression logic.
