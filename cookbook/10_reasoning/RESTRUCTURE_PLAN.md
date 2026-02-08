# Restructuring Plan: `cookbook/10_reasoning/`

## 1. Executive Summary

### Current State

| Metric | Value |
|--------|-------|
| Directories | 15 (agents, models/10 providers, teams, tools) |
| Total `.py` files (non-`__init__`) | 75 |
| Fully style-compliant | 0 (~0%) |
| Have module docstring | ~23 (~31%) |
| Have section banners | 0 (0%) |
| Have `if __name__` gate | ~11 (~15%) |
| Contain emoji | ~1 (tools/reasoning_tools.py) |
| Subdirectories with README.md | 1 / 15 (root only) |
| Subdirectories with TEST_LOG.md | 0 / 15 |

### Key Problems

1. **Massive duplication between `agents/` and `models/deepseek/`.** 12 files in `agents/` have near-identical copies in `models/deepseek/` — same prompts, same test scenarios, only the reasoning approach differs (`reasoning=True` vs `reasoning_model=DeepSeek(...)`). This is the biggest redundancy.

2. **Zero section banners.** No file uses section banners.

3. **Very few main gates.** Only 15% of files have `if __name__ == "__main__":`. Most files execute directly on import.

4. **Low docstring coverage.** Only 31% have module docstrings.

5. **Emoji in tools/reasoning_tools.py.** Contains brain emoji in docstring.

6. **No subdirectory documentation.** Only root has README.md. No TEST_LOG.md anywhere.

7. **Spelling error.** `models/deepseek/plan_itenerary.py` — should be `plan_itinerary.py`.

### Overall Assessment

The `agents/` and `models/deepseek/` directories show the same reasoning tasks with different approaches. Merging each pair into a single file that shows both `reasoning=True` (built-in COT) and `reasoning_model=DeepSeek(...)` (external reasoner) would eliminate 12 duplicate files while creating more educational examples.

The `tools/` directory has provider-specific reasoning tool files that follow similar patterns but are genuinely different (different models, different tool configs). Keep them.

The `models/` provider directories (anthropic, gemini, openai, groq, etc.) show model-specific reasoning features. Each is unique to its provider. Keep them.

### Proposed Target

| Metric | Current | Target |
|--------|---------|--------|
| Files | 75 | ~63 |
| Style compliance | 0% | 100% |
| README coverage | 1/15 | All directories |
| TEST_LOG coverage | 0/15 | All directories |

---

## 2. Proposed Directory Structure

No structural changes needed. The current layout is logical.

```
cookbook/10_reasoning/
├── agents/                      # Reasoning agent examples (merged with deepseek variants)
├── models/                      # Provider-specific reasoning capabilities
│   ├── anthropic/               # Claude extended thinking
│   ├── azure_ai_foundry/        # Azure DeepSeek reasoning
│   ├── azure_openai/            # Azure OpenAI reasoning
│   ├── deepseek/                # DeepSeek-only examples (2 unique files)
│   ├── gemini/                  # Gemini reasoning
│   ├── groq/                    # Groq fast reasoning
│   ├── ollama/                  # Local reasoning
│   ├── openai/                  # OpenAI reasoning models
│   ├── vertex_ai/               # Vertex AI reasoning
│   └── xai/                     # xAI reasoning
├── teams/                       # Team reasoning patterns
└── tools/                       # Reasoning tools per provider
```

### Changes from Current

| Change | Details |
|--------|---------|
| **MERGE** agents + deepseek pairs | 12 pairs merged into agents/ — each file shows both `reasoning=True` and `reasoning_model=DeepSeek()` |
| **CUT** 12 deepseek duplicates | After merging into agents/, the 12 duplicated deepseek files are removed |
| **KEEP** 2 unique deepseek files | `ethical_dilemma.py` and `plan_itinerary.py` stay (no agents/ equivalent) |

---

## 3. File Disposition Table

### `agents/` (17 → 17, absorbs 12 deepseek variants)

Each file below is merged with its `models/deepseek/` counterpart to show both reasoning approaches.

| File | Disposition | Rationale |
|------|------------|-----------|
| `analyse_treaty_of_versailles.py` | **REWRITE** | Merge with `deepseek/analyse_treaty_of_versailles.py`. Show both `reasoning=True` and `reasoning_model=DeepSeek()`. Add docstring, banners, main gate |
| `fibonacci.py` | **REWRITE** | Merge with `deepseek/fibonacci.py`. Add docstring, banners, main gate |
| `finance_agent.py` | **REWRITE** | Merge with `deepseek/finance_agent.py`. Add docstring, banners, main gate |
| `is_9_11_bigger_than_9_9.py` | **REWRITE** | Merge with `deepseek/9_11_or_9_9.py`. Add docstring, banners, main gate |
| `life_in_500000_years.py` | **REWRITE** | Merge with `deepseek/life_in_500000_years.py`. Add docstring, banners, main gate |
| `logical_puzzle.py` | **REWRITE** | Merge with `deepseek/logical_puzzle.py`. Add docstring, banners, main gate |
| `mathematical_proof.py` | **REWRITE** | Merge with `deepseek/mathematical_proof.py`. Add docstring, banners, main gate |
| `python_101_curriculum.py` | **REWRITE** | Merge with `deepseek/python_101_curriculum.py`. Add docstring, banners, main gate |
| `scientific_research.py` | **REWRITE** | Merge with `deepseek/scientific_research.py`. Add docstring, banners, main gate |
| `ship_of_theseus.py` | **REWRITE** | Merge with `deepseek/ship_of_theseus.py`. Add docstring, banners, main gate |
| `strawberry.py` | **REWRITE** | Merge with `deepseek/strawberry.py`. Add docstring, banners, main gate |
| `trolley_problem.py` | **REWRITE** | Merge with `deepseek/trolley_problem.py`. Add docstring, banners, main gate |
| `capture_reasoning_content_default_COT.py` | **KEEP + FIX** | No deepseek pair. Add banners, main gate |
| `cerebras_llama_default_COT.py` | **KEEP + FIX** | No deepseek pair. Add banners, main gate |
| `default_chain_of_thought.py` | **KEEP + FIX** | No deepseek pair. Add banners, main gate |
| `ibm_watsonx_default_COT.py` | **KEEP + FIX** | No deepseek pair. Add banners, main gate |
| `mistral_reasoning_cot.py` | **KEEP + FIX** | No deepseek pair. Add banners, main gate |

---

### `models/deepseek/` (14 → 2)

| File | Disposition | Rationale |
|------|------------|-----------|
| `analyse_treaty_of_versailles.py` | **MERGE INTO** `agents/` | Duplicate — merged into agents/ counterpart |
| `fibonacci.py` | **MERGE INTO** `agents/` | Duplicate |
| `finance_agent.py` | **MERGE INTO** `agents/` | Duplicate |
| `9_11_or_9_9.py` | **MERGE INTO** `agents/` | Duplicate |
| `life_in_500000_years.py` | **MERGE INTO** `agents/` | Duplicate |
| `logical_puzzle.py` | **MERGE INTO** `agents/` | Duplicate |
| `mathematical_proof.py` | **MERGE INTO** `agents/` | Duplicate |
| `python_101_curriculum.py` | **MERGE INTO** `agents/` | Duplicate |
| `scientific_research.py` | **MERGE INTO** `agents/` | Duplicate |
| `ship_of_theseus.py` | **MERGE INTO** `agents/` | Duplicate |
| `strawberry.py` | **MERGE INTO** `agents/` | Duplicate |
| `trolley_problem.py` | **MERGE INTO** `agents/` | Duplicate |
| `ethical_dilemma.py` | **KEEP + FIX** | Unique: no agents/ counterpart. Add docstring, banners, main gate |
| `plan_itenerary.py` | **KEEP + RENAME + FIX** | Unique. Rename to `plan_itinerary.py` (fix spelling). Add docstring, banners, main gate |

---

### `models/anthropic/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `basic_reasoning.py` | **KEEP + FIX** | Add banners, main gate |
| `basic_reasoning_stream.py` | **KEEP + FIX** | Add banners, main gate |
| `async_reasoning_stream.py` | **KEEP + FIX** | Add banners. Already has main gate |

---

### `models/azure_ai_foundry/` (2 → 2, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `reasoning_model_deepseek.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `reasoning_model_stream_deepseek.py` | **KEEP + FIX** | Add banners. Already has main gate |

---

### `models/azure_openai/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `basic_reasoning_stream.py` | **KEEP + FIX** | Add banners. Already has main gate |
| `o3_mini_with_tools.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `reasoning_model_gpt_4_1.py` | **KEEP + FIX** | Add docstring, banners, main gate |

---

### `models/gemini/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `basic_reasoning.py` | **KEEP + FIX** | Add banners, main gate |
| `basic_reasoning_stream.py` | **KEEP + FIX** | Add banners, main gate |
| `async_reasoning_stream.py` | **KEEP + FIX** | Add banners. Already has main gate |

---

### `models/groq/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `9_11_or_9_9.py` | **KEEP + FIX** | Add docstring, banners, main gate. Note: uses Groq, NOT same as deepseek duplicate |
| `deepseek_plus_claude.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `fast_reasoning.py` | **KEEP + FIX** | Add docstring, banners, main gate |

---

### `models/ollama/` (2 → 2, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `local_reasoning.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `reasoning_model_deepseek.py` | **KEEP + FIX** | Add docstring, banners, main gate |

---

### `models/openai/` (6 → 6, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `o3_mini.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `o3_mini_with_tools.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `reasoning_effort.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `reasoning_model_gpt_4_1.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `reasoning_stream.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `reasoning_summary.py` | **KEEP + FIX** | Add banners, main gate |

---

### `models/vertex_ai/` (1 → 1, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `basic_reasoning_stream.py` | **KEEP + FIX** | Add banners. Already has main gate |

---

### `models/xai/` (1 → 1, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `reasoning_effort.py` | **KEEP + FIX** | Add docstring, banners, main gate |

---

### `teams/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `finance_team_chain_of_thought.py` | **KEEP + FIX** | Add docstring, banners. Already has main gate |
| `knowledge_tool_team.py` | **KEEP + FIX** | Add docstring, banners. Already has main gate |
| `reasoning_finance_team.py` | **KEEP + FIX** | Add docstring, banners. Already has main gate |

---

### `tools/` (17 → 17, no change)

All tools files are unique — different model providers, different tool combinations.

| File | Disposition | Rationale |
|------|------------|-----------|
| `reasoning_tools.py` | **KEEP + FIX** | Remove emoji. Add banners, main gate |
| `openai_reasoning_tools.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `claude_reasoning_tools.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `azure_openai_reasoning_tools.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `capture_reasoning_content_knowledge_tools.py` | **KEEP + FIX** | Add banners, main gate |
| `capture_reasoning_content_reasoning_tools.py` | **KEEP + FIX** | Add banners, main gate |
| `cerebras_llama_reasoning_tools.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `gemini_finance_agent.py` | **KEEP + FIX** | Add banners, main gate |
| `gemini_reasoning_tools.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `groq_llama_finance_agent.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `ibm_watsonx_reasoning_tools.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `knowledge_tools.py` | **KEEP + FIX** | Add banners. Already has main gate |
| `llama_reasoning_tools.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `memory_tools.py` | **KEEP + FIX** | Add banners. Already has main gate |
| `ollama_reasoning_tools.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `vercel_reasoning_tools.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `workflow_tools.py` | **KEEP + FIX** | Add banners. Already has main gate |

---

## 4. New Files Needed

No new files needed.

---

## 5. Missing READMEs and TEST_LOGs

| Directory | README.md | TEST_LOG.md |
|-----------|-----------|-------------|
| `10_reasoning/` (root) | EXISTS | **MISSING** |
| `agents/` | **MISSING** | **MISSING** |
| `models/` | **MISSING** | **MISSING** |
| `models/anthropic/` | **MISSING** | **MISSING** |
| `models/azure_ai_foundry/` | **MISSING** | **MISSING** |
| `models/azure_openai/` | **MISSING** | **MISSING** |
| `models/deepseek/` | **MISSING** | **MISSING** |
| `models/gemini/` | **MISSING** | **MISSING** |
| `models/groq/` | **MISSING** | **MISSING** |
| `models/ollama/` | **MISSING** | **MISSING** |
| `models/openai/` | **MISSING** | **MISSING** |
| `models/vertex_ai/` | **MISSING** | **MISSING** |
| `models/xai/` | **MISSING** | **MISSING** |
| `teams/` | **MISSING** | **MISSING** |
| `tools/` | **MISSING** | **MISSING** |

**Note:** For the `models/` parent directory, create a single README listing all provider subdirectories. Individual provider directories can have lightweight READMEs since they contain few files each.

---

## 6. Recommended Cookbook Template

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

### Template Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Create Agent → Run Agent
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere
7. **Self-contained** — Each file must be independently runnable
8. **Preserve model providers** — Do NOT change model imports or IDs in existing files. Each file demonstrates a specific provider.
