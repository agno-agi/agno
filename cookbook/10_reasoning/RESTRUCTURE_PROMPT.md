# Implement `cookbook/10_reasoning/` Restructuring

You are restructuring the `cookbook/10_reasoning/` directory of the Agno AI agent framework. The full plan is attached as `RESTRUCTURE_PLAN.md`. Read it completely before starting.

## Context

- **Agno** is a Python AI agent framework. The `cookbook/` directory contains runnable example scripts.
- Reasoning scripts demonstrate different reasoning approaches: built-in chain-of-thought (`reasoning=True`), external reasoning models (`reasoning_model=DeepSeek(...)`), and provider-specific reasoning features.
- The goal is to consolidate 75 files down to ~63 by merging 12 `agents/` + `models/deepseek/` duplicate pairs, achieving 100% style compliance, and adding documentation.
- The virtual environment for running cookbooks is at `.venvs/demo/bin/python`.
- The style checker is at `cookbook/scripts/check_cookbook_pattern.py`.

## CRITICAL: Read Each File Before Modifying

**Do NOT apply blanket changes across files.** Every file demonstrates a specific reasoning approach with a specific model provider. You must:

1. **Read each file individually** before making any changes.
2. **Understand what the file demonstrates** — its model provider, reasoning configuration, and test prompt.
3. **Preserve the existing logic exactly** — only restructure the layout (add banners, docstring, main gate).
4. **For MERGE operations**, read ALL source files first, then combine thoughtfully.

## CRITICAL: Do NOT Change Model Providers

Each file in `models/` and `tools/` demonstrates a **specific model provider** (Claude, Gemini, Groq, Ollama, OpenAI, etc.). Do NOT:
- Change model imports or model IDs
- Replace one provider with another
- Add `OpenAIResponses` to files that use a different provider
- Change `reasoning_model`, `reasoning_effort`, or `show_full_reasoning` parameters

## Style Guide Template

```python
"""
<Reasoning Feature>
=============================

Demonstrates <what this file teaches> using Agno reasoning.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    reasoning=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "How many 'r' are in 'strawberry'?",
        stream=True,
        show_full_reasoning=True,
    )
```

### Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Create Agent → Run Agent
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere
7. **Preserve model providers** — Do NOT change model imports or IDs in existing files
8. **Self-contained** — Each file must be independently runnable

## Execution Plan

### Phase 1: Merge 12 agents/ + deepseek/ Pairs

For each of the 12 pairs listed below:
1. Read both the `agents/` file and its `models/deepseek/` counterpart
2. Understand the shared prompt/task
3. Merge into the `agents/` file showing both reasoning approaches
4. Delete the `models/deepseek/` source file

| agents/ file | deepseek/ file |
|-------------|----------------|
| `analyse_treaty_of_versailles.py` | `analyse_treaty_of_versailles.py` |
| `fibonacci.py` | `fibonacci.py` |
| `finance_agent.py` | `finance_agent.py` |
| `is_9_11_bigger_than_9_9.py` | `9_11_or_9_9.py` |
| `life_in_500000_years.py` | `life_in_500000_years.py` |
| `logical_puzzle.py` | `logical_puzzle.py` |
| `mathematical_proof.py` | `mathematical_proof.py` |
| `python_101_curriculum.py` | `python_101_curriculum.py` |
| `scientific_research.py` | `scientific_research.py` |
| `ship_of_theseus.py` | `ship_of_theseus.py` |
| `strawberry.py` | `strawberry.py` |
| `trolley_problem.py` | `trolley_problem.py` |

**Merge pattern:**

```python
"""
Strawberry Letter Count
=============================

Demonstrates reasoning approaches for letter counting tasks.
"""

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
# Built-in chain-of-thought reasoning
cot_agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    reasoning=True,
    markdown=True,
)

# External reasoning model (DeepSeek)
deepseek_agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    reasoning_model=DeepSeek(id="deepseek-reasoner"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    prompt = "How many 'r' are in 'strawberry'?"

    # --- Built-in COT ---
    print("=== Built-in Chain of Thought ===")
    cot_agent.print_response(prompt, stream=True, show_full_reasoning=True)

    # --- DeepSeek Reasoning ---
    print("\n=== DeepSeek Reasoning Model ===")
    deepseek_agent.print_response(prompt, stream=True, show_full_reasoning=True)
```

### Phase 2: Handle Unique DeepSeek Files

2 files in `models/deepseek/` have NO counterpart in `agents/`:
- `ethical_dilemma.py` → **KEEP + FIX** (add docstring, banners, main gate)
- `plan_itenerary.py` → **KEEP + RENAME + FIX** → rename to `plan_itinerary.py` (fix spelling), add style fixes

### Phase 3: Style Fixes on All Remaining Files (~51 files)

Work through the RESTRUCTURE_PLAN.md Section 3 directory by directory. For each file:
1. Read the file
2. Add module docstring if missing
3. Add section banners
4. Add `if __name__ == "__main__":` gate if missing
5. Remove emoji from `tools/reasoning_tools.py`
6. Do NOT change model providers, reasoning parameters, or prompts

### Phase 4: Create README.md and TEST_LOG.md

For every directory under `cookbook/10_reasoning/`. See RESTRUCTURE_PLAN.md Section 5 for the full list (15 directories).

For `models/`, create a parent README listing all provider subdirectories.

### Phase 5: Validate

```bash
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/10_reasoning/<subdir>
```

## Important Notes

1. **Read before writing** — Do not apply changes to files you haven't read.
2. **Preserve model providers** — This is the most important rule for this section. Every file uses a specific provider.
3. **Preserve reasoning parameters** — `reasoning=True`, `reasoning_model=...`, `reasoning_effort=...`, `show_full_reasoning=True`.
4. **Preserve prompts** — Do not change the test prompts/tasks in existing files.
5. **Emoji removal** — `tools/reasoning_tools.py` contains a brain emoji in its docstring. Remove it.
6. **Spelling fix** — `plan_itenerary.py` → `plan_itinerary.py`.
7. **No `__init__.py` files** — Cookbook directories don't use `__init__.py`.
8. **75 dashes** — `# ---------------------------------------------------------------------------` (75 dashes after `# `).
9. **Read the plan carefully** — The RESTRUCTURE_PLAN.md identifies which files have deepseek pairs and which are standalone.
10. **tools/ are all unique** — The 17 files in `tools/` each use a different model provider. Do not merge any of them.
