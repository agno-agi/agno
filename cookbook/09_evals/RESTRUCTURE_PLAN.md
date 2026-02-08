# Restructuring Plan: `cookbook/09_evals/`

## 1. Executive Summary

### Current State

| Metric | Value |
|--------|-------|
| Directories | 9 (accuracy, agent_as_judge, performance, performance/comparison, reliability + 3 nested) |
| Total `.py` files (non-`__init__`) | 41 |
| Fully style-compliant | 0 (~0%) |
| Have module docstring | 29 (~71%) |
| Have section banners | 0 (0%) |
| Have `if __name__` gate | 25 (~61%) |
| Contain emoji | 0 (0%) |
| Subdirectories with README.md | 1 / 9 (root only) |
| Subdirectories with TEST_LOG.md | 0 / 9 |

### Key Problems

1. **Zero section banner compliance.** No file uses section banners.

2. **Sync/async pairs could be merged.** Several directories have sync+async variants that are near-identical:
   - `accuracy_basic.py` / `accuracy_async.py`
   - `agent_as_judge_basic.py` / `agent_as_judge_async.py`
   - `agent_as_judge_post_hook.py` / `agent_as_judge_post_hook_async.py`

3. **Missing main gates.** 39% of files lack `if __name__ == "__main__":`, concentrated in accuracy/ and agent_as_judge/.

4. **Missing docstrings.** 12 files lack docstrings, concentrated in accuracy/ (5 files) and reliability/ (3 files).

5. **No subdirectory documentation.** Only root has README.md. No TEST_LOG.md anywhere.

### Overall Assessment

Well-organized by eval type (accuracy, agent_as_judge, performance, reliability). The main redundancy is sync/async pairs. The `performance/comparison/` subdirectory (6 framework benchmarks) is unique and valuable. Primary work is style compliance and merging 3 async pairs.

### Proposed Target

| Metric | Current | Target |
|--------|---------|--------|
| Files | 41 | 38 |
| Style compliance | 0% | 100% |
| README coverage | 1/9 | All directories |
| TEST_LOG coverage | 0/9 | All directories |

---

## 2. Proposed Directory Structure

No structural changes. Directory layout is already clean.

```
cookbook/09_evals/
├── accuracy/                    # Answer accuracy evaluation
├── agent_as_judge/              # LLM-as-judge evaluation
├── performance/                 # Execution performance benchmarks
│   └── comparison/              # Framework comparison benchmarks
└── reliability/                 # Tool calling reliability
    ├── single_tool_calls/       # Single tool invocation tests
    ├── multiple_tool_calls/     # Multi-tool invocation tests
    └── team/                    # Team-level reliability tests
```

---

## 3. File Disposition Table

### `accuracy/` (8 → 7)

| File | Disposition | Rationale |
|------|------------|-----------|
| `accuracy_basic.py` | **REWRITE** | Add docstring, banners, main gate. Merge with async variant |
| `accuracy_async.py` | **MERGE INTO** `accuracy_basic.py` | Async variant — same eval, just uses `arun()`. Add as async section in main gate |
| `accuracy_9_11_bigger_or_9_99.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `accuracy_team.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `accuracy_with_given_answer.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `accuracy_with_tools.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `db_logging.py` | **KEEP + FIX** | Add banners, main gate |
| `evaluator_agent.py` | **KEEP + FIX** | Add banners, main gate |

---

### `agent_as_judge/` (12 → 10)

| File | Disposition | Rationale |
|------|------------|-----------|
| `agent_as_judge_basic.py` | **REWRITE** | Merge with async variant. Add banners, main gate |
| `agent_as_judge_async.py` | **MERGE INTO** `agent_as_judge_basic.py` | Async variant — same eval |
| `agent_as_judge_post_hook.py` | **REWRITE** | Merge with async variant. Add banners, main gate |
| `agent_as_judge_post_hook_async.py` | **MERGE INTO** `agent_as_judge_post_hook.py` | Async variant |
| `agent_as_judge_batch.py` | **KEEP + FIX** | Add banners, main gate |
| `agent_as_judge_binary.py` | **KEEP + FIX** | Add banners, main gate |
| `agent_as_judge_custom_evaluator.py` | **KEEP + FIX** | Add banners, main gate |
| `agent_as_judge_team.py` | **KEEP + FIX** | Add banners, main gate |
| `agent_as_judge_team_post_hook.py` | **KEEP + FIX** | Add banners, main gate |
| `agent_as_judge_with_guidelines.py` | **KEEP + FIX** | Add banners, main gate |
| `agent_as_judge_with_tools.py` | **KEEP + FIX** | Add banners, main gate |

---

### `performance/` (11 → 11, no change)

All files are unique benchmarks measuring different aspects. No merges.

| File | Disposition | Rationale |
|------|------------|-----------|
| `async_function.py` | **KEEP + FIX** | Add banners. Already has main gate |
| `db_logging.py` | **KEEP + FIX** | Add banners. Already has main gate |
| `instantiate_agent.py` | **KEEP + FIX** | Add banners. Already has main gate |
| `instantiate_agent_with_tool.py` | **KEEP + FIX** | Add banners. Already has main gate |
| `instantiate_team.py` | **KEEP + FIX** | Add banners. Already has main gate |
| `response_with_memory_updates.py` | **KEEP + FIX** | Add banners. Already has main gate |
| `response_with_storage.py` | **KEEP + FIX** | Add banners. Already has main gate |
| `simple_response.py` | **KEEP + FIX** | Add docstring, banners. Already has main gate |
| `team_response_with_memory_and_reasoning.py` | **KEEP + FIX** | Add docstring, banners. Already has main gate |
| `team_response_with_memory_multi_user.py` | **KEEP + FIX** | Add docstring, banners. Already has main gate |
| `team_response_with_memory_simple.py` | **KEEP + FIX** | Add docstring, banners. Already has main gate |

---

### `performance/comparison/` (6 → 6, no change)

Each file benchmarks a different framework. All unique and valuable.

| File | Disposition | Rationale |
|------|------------|-----------|
| `autogen_instantiation.py` | **KEEP + FIX** | Add banners. Already has main gate |
| `crewai_instantiation.py` | **KEEP + FIX** | Add banners. Already has main gate |
| `langgraph_instantiation.py` | **KEEP + FIX** | Add banners. Already has main gate |
| `openai_agents_instantiation.py` | **KEEP + FIX** | Add banners. Already has main gate |
| `pydantic_ai_instantiation.py` | **KEEP + FIX** | Add banners. Already has main gate |
| `smolagents_instantiation.py` | **KEEP + FIX** | Add banners. Already has main gate |

---

### `reliability/` (5 → 5, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `db_logging.py` | **KEEP + FIX** | Add banners, main gate |
| `reliability_async.py` | **KEEP + FIX** | Add banners. Already has main gate |
| `single_tool_calls/calculator.py` | **KEEP + FIX** | Add docstring, banners. Already has main gate |
| `multiple_tool_calls/calculator.py` | **KEEP + FIX** | Add docstring, banners. Already has main gate |
| `team/ai_news.py` | **KEEP + FIX** | Add docstring, banners. Already has main gate |

---

## 4. New Files Needed

No new files needed.

---

## 5. Missing READMEs and TEST_LOGs

| Directory | README.md | TEST_LOG.md |
|-----------|-----------|-------------|
| `09_evals/` (root) | EXISTS | **MISSING** |
| `accuracy/` | **MISSING** | **MISSING** |
| `agent_as_judge/` | **MISSING** | **MISSING** |
| `performance/` | **MISSING** | **MISSING** |
| `performance/comparison/` | **MISSING** | **MISSING** |
| `reliability/` | **MISSING** | **MISSING** |
| `reliability/single_tool_calls/` | **MISSING** | **MISSING** |
| `reliability/multiple_tool_calls/` | **MISSING** | **MISSING** |
| `reliability/team/` | **MISSING** | **MISSING** |

---

## 6. Recommended Cookbook Template

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

### Template Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Create Agent → Create Evaluation → Run Evaluation
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere
7. **Self-contained** — Each file must be independently runnable

### Notes for Comparison Files

The `performance/comparison/` files benchmark non-Agno frameworks. These may not follow the standard Agno template (no Agent, no Agno imports). Apply banners and main gate, but preserve the framework-specific imports and setup.
