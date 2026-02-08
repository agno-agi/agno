# Implement `cookbook/02_agents/` Restructuring

You are restructuring the `cookbook/02_agents/` directory of the Agno AI agent framework. The full plan is attached as `RESTRUCTURE_PLAN.md`. Read it completely before starting.

## Context

- **Agno** is a Python AI agent framework. The `cookbook/` directory contains runnable example scripts.
- The goal is to consolidate ~164 files down to ~79 files by merging redundant sync/async/stream variants, cutting trivial files, and adding new examples for undocumented features.
- Every surviving file must comply with the style guide (see Template section below).
- The virtual environment for running cookbooks is at `.venvs/demo/bin/python`.
- The style checker is at `cookbook/scripts/check_cookbook_pattern.py`.

## Style Guide Template

Every `.py` file must follow this exact structure:

```python
"""
<Feature Name>
=============================

Demonstrates <what this file teaches> using Agno's <specific API/feature>.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
agent_db = SqliteDb(db_file="tmp/agents.db")

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a helpful assistant.\
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Example Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=instructions,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What is the capital of France?", stream=True)

    # Async usage (when demonstrating both patterns)
    # import asyncio
    # asyncio.run(agent.aprint_response("What is the capital of France?", stream=True))
```

### Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Setup → Instructions (if applicable) → Create → Run
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere
7. **Sync + async together** — When merging sync/async variants, show both in the same file using labeled sections within the `if __name__` block
8. **Self-contained** — Each file must be independently runnable

## Execution Plan

Execute in this exact order. Each phase must complete before the next starts.

### Phase 1: Create New Directory Structure

```
mkdir -p cookbook/02_agents/01_quickstart
mkdir -p cookbook/02_agents/learning
mkdir -p cookbook/02_agents/reasoning
mkdir -p cookbook/02_agents/run_control
```

Rename:
```
mv cookbook/02_agents/custom_logging cookbook/02_agents/logging
```

### Phase 2: Execute File Dispositions

Work through the RESTRUCTURE_PLAN.md Section 3 ("File Disposition Table") directory by directory. For each directory:

#### CUT files
Delete files marked as **CUT**. Do this first per directory so they don't confuse the merge step.

#### MERGE files
For files marked **MERGE INTO**, read the source files and combine their unique content into the target file. The merge strategy:
- Keep ALL unique functionality from each source file
- Combine sync/async/stream variants into sections within the same `if __name__` block, labeled with comments like `# --- Sync usage ---` and `# --- Async usage ---`
- Use the longest/most complete variant as the base, then add sections for other variants
- Delete the source files after merging

#### REWRITE files
Files marked **REWRITE** need to be rebuilt from scratch following the template. Use the existing file content as reference for the agent configuration and logic, but restructure to match the style guide.

#### KEEP + FIX files
Files marked **KEEP + FIX** need style remediation:
- Add module docstring if missing
- Add section banners (`# ---------------------------------------------------------------------------`)
- Add `if __name__ == "__main__":` gate if missing
- Remove emoji if present
- Do NOT change the agent logic or configuration

#### KEEP + MOVE + FIX / KEEP + RENAME + FIX files
Move or rename the file as specified, then apply the same style fixes as KEEP + FIX.

#### RELOCATE files
Move these files to a staging area. Create `cookbook/02_agents/_relocated/` and move them there with a note about their intended destination (`cookbook/integrations/`). Do not delete them — they'll be moved in a later cross-section restructuring pass.

The specific relocations:
- `agentic_search/agentic_rag_infinity_reranker.py` → `_relocated/`
- `agentic_search/lightrag/agentic_rag_with_lightrag.py` → `_relocated/`
- `rag/local_rag_langchain_qdrant.py` → `_relocated/`

### Phase 3: Create New Files

Create the 11 new files listed in RESTRUCTURE_PLAN.md Section 4. For each:

1. Follow the style guide template exactly
2. Use the feature descriptions in the plan to write meaningful examples
3. Look at the Agno source code in `libs/agno/agno/` to understand the APIs:
   - `libs/agno/agno/learn/` for LearningMachine
   - `libs/agno/agno/agent/agent.py` for Agent class features (serialization, tool_choice, etc.)
   - `libs/agno/agno/guardrails/base.py` for BaseGuardrail
   - `libs/agno/agno/exceptions.py` for InputCheckError, OutputCheckError, CheckTrigger
   - `libs/agno/agno/utils/hooks.py` for hook patterns
4. Each file must be independently runnable
5. Use `OpenAIResponses(id="gpt-5.2")` as the default model (matching template convention)

### Phase 4: Clean Up Empty Directories

After all file operations, remove empty directories:
```
rmdir cookbook/02_agents/agentic_search/lightrag  # if empty
rmdir cookbook/02_agents/agentic_search            # if empty
rmdir cookbook/02_agents/async                      # should be empty
rmdir cookbook/02_agents/other                      # should be empty
rmdir cookbook/02_agents/custom_logging             # was renamed
```

### Phase 5: Create README.md and TEST_LOG.md

For every surviving subdirectory under `cookbook/02_agents/`:

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
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/02_agents/<subdir>
```

Fix any violations. All files must pass.

## Key Merge Examples

### Example: Merging sync/async/stream variants (caching/)

Before: 4 files (`cache_model_response.py`, `async_cache_model_response.py`, `cache_model_response_stream.py`, `async_cache_model_response_stream.py`)

After: 1 file (`cache_model_response.py`) with structure:

```python
"""
Model Response Caching
=============================

Demonstrates caching model responses to avoid redundant API calls
using Agno's `cache_model_responses` parameter.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Caching Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    cache_model_responses=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Tell me a joke")
    # Second call should hit cache
    agent.print_response("Tell me a joke")

    # --- Streaming ---
    agent.print_response("Tell me a joke", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("Tell me a joke"))

    # --- Async Streaming ---
    asyncio.run(agent.aprint_response("Tell me a joke", stream=True))
```

### Example: Merging parameter variants (context_management/)

Before: 4 files (`datetime_instructions.py`, `location_instructions.py`, `dynamic_instructions.py`, `instructions_via_function.py`)

After: 1 file (`instructions.py`) showing all instruction patterns as separate agent instances:

```python
"""
Agent Instructions
=============================

Demonstrates different ways to configure agent instructions in Agno.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run.context import RunContext

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

# Pattern 1: Datetime in context
datetime_agent = Agent(
    name="Datetime Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=["Always mention the current date."],
    add_datetime_to_context=True,
)

# Pattern 2: Location in context
location_agent = Agent(
    name="Location Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=["Reference the user's location when relevant."],
    add_location_to_context=True,
)

# Pattern 3: Dynamic instructions via function
def get_instructions(context: RunContext) -> str:
    return f"Session {context.session_id}: Be helpful."

dynamic_agent = Agent(
    name="Dynamic Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=get_instructions,
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("--- Datetime Instructions ---")
    datetime_agent.print_response("What day is it?", stream=True)

    print("\n--- Dynamic Instructions ---")
    dynamic_agent.print_response("Hello!", stream=True)
```

## Important Notes

1. **Preserve agent logic** — When merging or rewriting, keep the exact same agent configurations (model, tools, instructions). Don't invent new behavior.
2. **Use existing imports** — Look at the source files to understand which Agno modules to import. Don't guess API signatures.
3. **Default model** — For new files, use `OpenAIResponses(id="gpt-5.2")` from `agno.models.openai`. Use `Gemini(id="gemini-3-flash-preview")` from `agno.models.google` only when a file specifically needs a Google model.
4. **No `__init__.py` files** — Cookbook directories don't use `__init__.py`.
5. **75 dashes** — The banner separator is exactly `# ---------------------------------------------------------------------------` (75 dashes after `# `).
6. **Read the plan carefully** — The RESTRUCTURE_PLAN.md has detailed rationale for every decision. When in doubt, follow the plan.
7. **Cross-references** — Some files move between directories (e.g., `state/last_n_session_messages.py` → `session/`, `input_and_output/instructions.py` → `context_management/`). Track these carefully.
