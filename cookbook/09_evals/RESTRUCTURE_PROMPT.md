# Implement `cookbook/09_evals/` Restructuring

You are restructuring the `cookbook/09_evals/` directory of the Agno AI agent framework. The full plan is attached as `RESTRUCTURE_PLAN.md`. Read it completely before starting.

## Context

- **Agno** is a Python AI agent framework. The `cookbook/` directory contains runnable example scripts.
- Eval scripts create agents, set up evaluations (accuracy, agent-as-judge, reliability, performance), and run them.
- The goal is to consolidate 41 files down to 38 by merging 3 sync/async pairs, achieving 100% style compliance, and adding documentation to all directories.
- The virtual environment for running cookbooks is at `.venvs/demo/bin/python`.
- The style checker is at `cookbook/scripts/check_cookbook_pattern.py`.

## CRITICAL: Read Each File Before Modifying

**Do NOT apply blanket changes across files using batch scripts or regex-based rewrites.** Every file has unique evaluation configurations, expected outputs, scoring criteria, and agent setups. You must:

1. **Read each file individually** before making any changes.
2. **Understand what the eval does** — its agent setup, evaluation type, expected outputs, and scoring.
3. **Preserve the existing logic exactly** — only restructure the layout (add banners, docstring, main gate).
4. **For MERGE operations**, read ALL source files first, then combine their unique content thoughtfully.

## CRITICAL: Comparison Files Are Non-Standard

The `performance/comparison/` directory contains 6 files that benchmark **non-Agno frameworks** (autogen, crewai, langgraph, openai_agents, pydantic_ai, smolagents). These files:
- Do NOT import Agno
- Do NOT follow the standard Agno template
- Have framework-specific imports and setup

Apply banners and main gate to these files, but **preserve their framework-specific imports and logic**. Do not add Agno imports or change them to use Agno patterns.

## Style Guide Template

Every `.py` file must follow this exact structure:

```python
"""
<Eval Type> Evaluation
=============================

Demonstrates <what this eval measures> using Agno evals.
"""

from agno.agent import Agent
from agno.eval.accuracy import AccuracyEval
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
)

# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
evaluation = AccuracyEval(
    agent=agent,
    input="What is 2+2?",
    expected_output="4",
    num_iterations=3,
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    result = evaluation.run(print_results=True)
    result.assert_passed()
```

### Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Create Agent → Create Evaluation → Run Evaluation
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere
7. **Self-contained** — Each file must be independently runnable

## Execution Plan

### Phase 1: Merge 3 Sync/Async Pairs

**Pair 1:** `accuracy/accuracy_basic.py` + `accuracy/accuracy_async.py`
- Read both files
- Use sync as base, add async section in main gate
- Delete `accuracy_async.py`

**Pair 2:** `agent_as_judge/agent_as_judge_basic.py` + `agent_as_judge/agent_as_judge_async.py`
- Read both files
- Use sync as base, add async section in main gate
- Delete `agent_as_judge_async.py`

**Pair 3:** `agent_as_judge/agent_as_judge_post_hook.py` + `agent_as_judge/agent_as_judge_post_hook_async.py`
- Read both files
- Use sync as base, add async section in main gate
- Delete `agent_as_judge_post_hook_async.py`

### Phase 2: Style Fixes (all 38 surviving files)

Work through the RESTRUCTURE_PLAN.md Section 3 directory by directory. For each file marked **KEEP + FIX**:
1. Read the file
2. Add module docstring if missing
3. Add section banners
4. Add `if __name__ == "__main__":` gate if missing
5. Do NOT change eval configurations, expected outputs, or scoring criteria

### Phase 3: Create README.md and TEST_LOG.md

For every directory under `cookbook/09_evals/`:

**README.md** — Short description, file list with one-line descriptions.

**TEST_LOG.md** — Placeholder template:
```markdown
# Test Log: <directory_name>

> Tests not yet run. Run each file and update this log.

### <filename>.py

**Status:** PENDING

**Description:** <what the file does>

---
```

### Phase 4: Validate

Run the structure checker on each subdirectory:
```bash
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/09_evals/<subdir>
```

Fix any violations. All files must pass.

## Key Merge Example

### Merging accuracy_basic.py + accuracy_async.py

```python
"""
Basic Accuracy Evaluation
=============================

Demonstrates basic accuracy evaluation using Agno evals.
"""

import asyncio

from agno.agent import Agent
from agno.eval.accuracy import AccuracyEval
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
)

# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
evaluation = AccuracyEval(
    agent=agent,
    input="What is 2+2?",
    expected_output="4",
    num_iterations=3,
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    result = evaluation.run(print_results=True)
    result.assert_passed()

    # --- Async ---
    async_result = asyncio.run(evaluation.arun(print_results=True))
    async_result.assert_passed()
```

## Important Notes

1. **Read before writing** — Do not apply changes to files you haven't read.
2. **Preserve eval logic** — Do not change evaluation parameters (num_iterations, expected_output, scoring criteria).
3. **Comparison files are special** — The 6 files in `performance/comparison/` benchmark non-Agno frameworks. Apply style fixes but preserve their framework-specific code.
4. **Use existing imports** — Look at the source files to understand which Agno eval modules to import.
5. **No `__init__.py` files** — Cookbook directories don't use `__init__.py`.
6. **75 dashes** — The banner separator is exactly `# ---------------------------------------------------------------------------` (75 dashes after `# `).
7. **Read the plan carefully** — The RESTRUCTURE_PLAN.md has detailed rationale for every decision.
