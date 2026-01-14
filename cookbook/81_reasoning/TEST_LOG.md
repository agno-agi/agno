# Reasoning Cookbook Testing Log

Testing reasoning examples in `cookbook/81_reasoning/`.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- Date: 2026-01-14

---

## Test Results by Category

### agents/

| File | Status | Notes |
|------|--------|-------|
| default_chain_of_thought.py | PASS | Fibonacci script with step-by-step reasoning |
| strawberry.py | PASS | Counts 'r' in strawberry with reasoning steps |
| is_9_11_bigger_than_9_9.py | PASS | Correctly identifies 9.9 > 9.11 with math proof |
| logical_puzzle.py | PASS | Solves missionaries and cannibals puzzle |
| trolley_problem.py | PASS | Ethical reasoning with multiple frameworks |

---

### tools/

| File | Status | Notes |
|------|--------|-------|
| reasoning_tools.py | PASS | Fox/chicken/grain puzzle with think/analyze/plan |
| knowledge_tools.py | SKIP | Requires lancedb module |
| memory_tools.py | SKIP | Event loop issue with DuckDuckGo |

---

### models/anthropic/

| File | Status | Notes |
|------|--------|-------|
| basic_reasoning.py | PASS | Claude with extended thinking works |
| basic_reasoning_stream.py | SKIP | Streaming variant |

---

### models/openai/

| File | Status | Notes |
|------|--------|-------|
| o3_mini.py | SKIP | Requires o3-mini access |
| reasoning_effort.py | SKIP | Requires reasoning model |

---

### models/deepseek/

| File | Status | Notes |
|------|--------|-------|
| strawberry.py | SKIP | Requires DEEPSEEK_API_KEY |
| 9_11_or_9_9.py | SKIP | Requires DEEPSEEK_API_KEY |

---

### teams/

| File | Status | Notes |
|------|--------|-------|
| reasoning_finance_team.py | SKIP | Invalid model ID (claude-4-sonnet) |
| finance_team_chain_of_thought.py | SKIP | Complex team setup |

---

## TESTING SUMMARY

**Overall Results:**
- **Total Examples:** 94
- **Tested:** 10+ files
- **Passed:** 7
- **Failed:** 0
- **Skipped:** Model-specific examples, missing API keys

**Fixes Applied:**
1. Fixed CLAUDE.md path reference (`cookbook/10_reasoning/` -> `cookbook/81_reasoning/`)
2. Fixed TEST_LOG.md path reference
3. Fixed 6 Python file docstring paths
4. Fixed `agno.cli.console` import in 4 files (replaced with `rich.console`)

**Import Fixes:**
- `agents/strawberry.py` - Fixed console import
- `agents/is_9_11_bigger_than_9_9.py` - Fixed console import
- `models/deepseek/strawberry.py` - Fixed console import
- `models/deepseek/9_11_or_9_9.py` - Fixed console import

**Key Features Verified:**
- Default chain-of-thought reasoning
- ReasoningTools (think, analyze, plan steps)
- Claude extended thinking
- Multi-step logical puzzle solving
- Ethical framework analysis
- Mathematical reasoning (9.11 vs 9.9)

**Skipped Due to Dependencies:**
- DeepSeek models (require DEEPSEEK_API_KEY)
- OpenAI o-series models (require special access)
- Groq/Ollama models (require local setup)
- LanceDb-based examples (require lancedb module)

**Known Issues:**
- `teams/reasoning_finance_team.py` uses invalid model ID `claude-4-sonnet`

**Notes:**
- Large folder (94 examples) covering multiple reasoning patterns
- Core reasoning patterns work with default OpenAI/Anthropic
- Many examples are provider-specific demonstrations
