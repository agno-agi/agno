# Implement `cookbook/03_teams/` Restructuring

You are restructuring the `cookbook/03_teams/` directory of the Agno AI agent framework. The full plan is attached as `RESTRUCTURE_PLAN.md`. Read it completely before starting.

## Context

- **Agno** is a Python AI agent framework. The `cookbook/` directory contains runnable example scripts.
- The goal is to consolidate ~101 files down to ~74 files by merging redundant sync/async variants, cutting trivial files, and adding new examples for undocumented features.
- Every surviving file must comply with the style guide (see Template section below).
- The virtual environment for running cookbooks is at `.venvs/demo/bin/python`.
- The style checker is at `cookbook/scripts/check_cookbook_pattern.py`.

## CRITICAL: Read Each File Before Modifying

**Do NOT apply blanket changes across files using batch scripts or regex-based rewrites.** Every file in this cookbook has unique agent/team configurations, tools, instructions, and logic. You must:

1. **Read each file individually** before making any changes to it.
2. **Understand what the file does** — its agent configuration, team setup, tools, instructions, and run logic.
3. **Preserve the existing logic exactly** — only restructure the layout (add banners, docstring, main gate). Do not change model names, tool configurations, instructions, or agent parameters that already exist in the file.
4. **For MERGE operations**, read ALL source files first, then combine their unique content thoughtfully. Don't just concatenate.
5. **For REWRITE operations**, read the existing file first to understand the agent/team config, then rebuild from scratch following the template while keeping the same configuration.

This is a careful, file-by-file task. It will take time. Do not rush it.

## Style Guide Template

Every `.py` file must follow this exact structure:

```python
"""
<Feature Name>
=============================

Demonstrates <what this file teaches> using Agno Teams.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Research and gather information",
)

writer = Agent(
    name="Writer",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Write clear summaries",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Research Team",
    members=[researcher, writer],
    model=OpenAIResponses(id="gpt-5.2"),
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    team.print_response("What are the latest trends in AI?", stream=True)

    # Async usage (when demonstrating both patterns)
    # import asyncio
    # asyncio.run(team.aprint_response("What are the latest trends in AI?", stream=True))
```

### Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Setup (if needed) → Create Members → Create Team → Run Team
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere
7. **Sync + async together** — When merging sync/async variants, show both in the same file using labeled sections within the `if __name__` block
8. **Self-contained** — Each file must be independently runnable

## Execution Plan

Execute in this exact order. Each phase must complete before the next starts.

### Phase 1: Create New Directory Structure

```
mkdir -p cookbook/03_teams/01_quickstart
mkdir -p cookbook/03_teams/run_control
```

Note: `basic_flows/` is being renamed to `01_quickstart/`. Move all files from `basic_flows/` to `01_quickstart/` first, then remove `basic_flows/`.

### Phase 2: Execute File Dispositions (file by file)

Work through the RESTRUCTURE_PLAN.md Section 3 ("File Disposition Table") directory by directory.

**For each file, you MUST:**
1. Read the file completely
2. Understand its purpose, agent/team config, tools, and instructions
3. Apply the disposition (CUT, MERGE, REWRITE, KEEP+FIX, etc.)
4. Verify the result preserves the original behavior

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
1. Read the existing file to understand its team/agent configuration
2. Rebuild from scratch following the template
3. Keep the exact same team name, member agents, models, tools, and instructions
4. Only change the structure/layout to match the style guide

#### KEEP + FIX files
For files marked **KEEP + FIX**:
1. Read the file
2. Add module docstring if missing
3. Move imports above first banner
4. Add section banners (`# ---------------------------------------------------------------------------`)
5. Add `if __name__ == "__main__":` gate if missing
6. Remove emoji if present
7. Do NOT change the team/agent logic or configuration

#### KEEP + MOVE + FIX / KEEP + RENAME + FIX files
Move or rename the file as specified, then apply the same style fixes as KEEP + FIX.

### Phase 3: Create New Files

Create the 5 new files listed in RESTRUCTURE_PLAN.md Section 4. For each:

1. Follow the style guide template exactly
2. Use the feature descriptions in the plan to write meaningful examples
3. Look at the Agno source code in `libs/agno/agno/` to understand the APIs:
   - `libs/agno/agno/team/team.py` for Team class features (modes, members, etc.)
   - `libs/agno/agno/team/team_enums.py` for TeamMode (coordinate, route, collaborate, tasks, broadcast)
   - `libs/agno/agno/learn/` for LearningMachine
   - `libs/agno/agno/agent/agent.py` for Agent class features
4. Each file must be independently runnable
5. Use `OpenAIResponses(id="gpt-5.2")` as the default model

### Phase 4: Clean Up Empty Directories

After all file operations, remove empty directories:
```
rmdir cookbook/03_teams/basic_flows       # renamed to 01_quickstart
rmdir cookbook/03_teams/async_flows       # should be empty
rmdir cookbook/03_teams/other             # should be empty
```

### Phase 5: Create README.md and TEST_LOG.md

For every surviving subdirectory under `cookbook/03_teams/`:

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
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/03_teams/<subdir>
```

Fix any violations. All files must pass.

## Key Merge Examples

### Example: Merging sync/async team variants (streaming/)

Before: 4 files (`01_team_streaming.py`, `02_events.py`, `03_async_team_streaming.py`, `04_async_team_events.py`)

After: 2 files (`team_streaming.py`, `team_events.py`), each with sync + async:

```python
"""
Team Response Streaming
=============================

Demonstrates real-time response streaming with Agno Teams.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Research topics thoroughly",
)

writer = Agent(
    name="Writer",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Write clear summaries",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Research Team",
    members=[researcher, writer],
    model=OpenAIResponses(id="gpt-5.2"),
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync Streaming ---
    team.print_response("Explain quantum computing", stream=True)

    # --- Async Streaming ---
    asyncio.run(team.aprint_response("Explain quantum computing", stream=True))
```

### Example: Dissolving other/ (input formats → structured_input_output/)

Before: 3 separate files in `other/` (`input_as_dict.py`, `input_as_list.py`, `input_as_messages_list.py`)

After: 1 file in `structured_input_output/input_formats.py` showing all patterns:

```python
"""
Team Input Formats
=============================

Demonstrates different input formats accepted by Agno Teams.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Research topics",
)

team = Team(
    name="Research Team",
    members=[researcher],
    model=OpenAIResponses(id="gpt-5.2"),
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Dict input ---
    team.print_response({"role": "user", "content": "Explain AI"}, stream=True)

    # --- List input ---
    team.print_response(["What is machine learning?", "Keep it brief."], stream=True)

    # --- Messages list input ---
    team.print_response(
        [{"role": "user", "content": "What is deep learning?"}], stream=True
    )
```

## Important Notes

1. **Read before writing** — This is the most important rule. Do not apply changes to files you haven't read. Every file has unique content that must be understood and preserved.
2. **Preserve team/agent logic** — When merging or rewriting, keep the exact same team configurations (members, model, tools, instructions, mode). Don't invent new behavior.
3. **Use existing imports** — Look at the source files to understand which Agno modules to import. Don't guess API signatures.
4. **Default model** — For new files, use `OpenAIResponses(id="gpt-5.2")` from `agno.models.openai`.
5. **No `__init__.py` files** — Cookbook directories don't use `__init__.py`.
6. **75 dashes** — The banner separator is exactly `# ---------------------------------------------------------------------------` (75 dashes after `# `).
7. **Read the plan carefully** — The RESTRUCTURE_PLAN.md has detailed rationale for every decision. When in doubt, follow the plan.
8. **Cross-directory moves** — Some files move between directories (e.g., `other/few_shot_learning.py` → `context_management/`, `other/input_as_*.py` → `structured_input_output/`, `other/team_cancel_a_run.py` → `run_control/`). Track these carefully.
9. **basic_flows → 01_quickstart** — The `basic_flows/` directory is being renamed to `01_quickstart/`. Move all files first, then remove the old directory.
