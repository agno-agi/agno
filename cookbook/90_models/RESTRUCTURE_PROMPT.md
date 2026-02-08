# Implement `cookbook/90_models/` Restructuring

You are restructuring the `cookbook/90_models/` directory of the Agno AI agent framework. The full plan is attached as `RESTRUCTURE_PLAN.md`. Read it completely before starting.

## Context

- **Agno** is a Python AI agent framework. The `cookbook/` directory contains runnable example scripts.
- This is the **largest cookbook section** at 643 files across 44 provider directories (63 total dirs including subdirectories).
- The goal is to reduce to ~450 files by merging sync/stream/async variants, deleting 56 `__init__.py` files, achieving 100% style compliance, and adding documentation.
- The virtual environment for running cookbooks is at `.venvs/demo/bin/python`.
- The style checker is at `cookbook/scripts/check_cookbook_pattern.py`.

## CRITICAL: Read Each File Before Modifying

**Do NOT apply blanket changes across files.** Every provider uses a specific model class, model ID, and import path. You must:

1. **Read each file individually** before making any changes.
2. **Understand what the file does** — its model provider, model ID, and feature demonstrated.
3. **Preserve the existing logic exactly** — only restructure the layout (add banners, docstring, main gate).
4. **For MERGE operations**, read ALL source files first, then combine thoughtfully.

## CRITICAL: Do NOT Change Model Providers

Each provider directory uses a **specific model class and model ID**. Do NOT:
- Change model imports (e.g., `from agno.models.fireworks import Fireworks`)
- Change model IDs (e.g., `accounts/fireworks/models/llama-v3p1-405b-instruct`)
- Replace one provider with another
- Add `OpenAIResponses` to files that use a different provider

## CRITICAL: One Merge Pattern — Four Variants Into One

The only merge pattern in this section collapses sync/stream/async/async+stream variants of the same feature into a single file. The differences are trivial:

- `basic.py`: `agent.print_response("...")`
- `basic_stream.py`: `agent.print_response("...", stream=True)`
- `async_basic.py`: `asyncio.run(agent.aprint_response("..."))`
- `async_basic_stream.py`: `asyncio.run(agent.aprint_response("...", stream=True))`

All four become a single `basic.py` with labeled sections in the main gate.

## CRITICAL: Providers With Sub-APIs

Several providers have subdirectories for different APIs. These are **genuinely different model classes** and must stay separate:

- `openai/chat/` (OpenAIChat) vs `openai/responses/` (OpenAIResponses)
- `ollama/chat/` (OllamaChat) vs `ollama/responses/` (OllamaResponses)
- `openrouter/chat/` vs `openrouter/responses/`
- `meta/llama/` (Llama API) vs `meta/llama_openai/` (OpenAI-compatible)
- `aws/bedrock/` vs `aws/claude/`
- `azure/ai_foundry/` vs `azure/openai/`

Apply the standard merge pattern **within** each subdirectory independently.

## Style Guide Template

```python
"""
<Provider> Basic Usage
=============================

Demonstrates basic agent usage with <Provider>.
"""

from agno.agent import Agent
from agno.models.<provider> import <ProviderClass>

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=<ProviderClass>(id="<model-id>"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a 2 sentence horror story")

    # --- Sync + Streaming ---
    agent.print_response("Share a 2 sentence horror story", stream=True)

    # --- Async ---
    import asyncio

    asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))

    # --- Async + Streaming ---
    asyncio.run(
        agent.aprint_response("Share a 2 sentence horror story", stream=True)
    )
```

### Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Create Agent → Run Agent (most model examples don't need a Setup section)
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere
7. **All variants in one file** — Sync, stream, async, async+stream shown as labeled sections in the main gate
8. **Preserve model providers** — Do NOT change model imports or model IDs
9. **Self-contained** — Each file must be independently runnable

## Execution Plan

### Phase 1: Delete All `__init__.py` Files (56 files)

```bash
find cookbook/90_models -name "__init__.py" -delete
```

### Phase 2: Merge Standard Quadruplets (per provider)

For each provider directory, apply the standard merges:

**Merge Group A** — Basic quadruplet → `basic.py`:
1. Read `basic.py`, `basic_stream.py`, `async_basic.py`, `async_basic_stream.py`
2. Use `basic.py` as base
3. Add stream/async/async+stream as labeled sections in the main gate
4. Delete `basic_stream.py`, `async_basic.py`, `async_basic_stream.py`

**Merge Group B** — Tool-use quadruplet → `tool_use.py`:
1. Read `tool_use.py`, `tool_use_stream.py`, `async_tool_use.py`, `async_tool_use_stream.py`
2. Same merge pattern
3. Delete stream/async variants

**Merge Group C** — Structured output pair → `structured_output.py`:
1. Read `structured_output.py`, `structured_output_stream.py`
2. Merge stream into base
3. Delete `structured_output_stream.py`

**Merge Group D** — Thinking pair → `thinking.py` (anthropic, vertexai/claude):
1. Read `thinking.py`, `thinking_stream.py`
2. Merge stream into base
3. Delete `thinking_stream.py`

Work through providers in alphabetical order. Not all providers have all groups — only merge files that exist.

### Phase 3: Handle Special Provider Merges

See RESTRUCTURE_PLAN.md Section 3 for per-provider special cases:
- `google/gemini/`: Also merge image_generation, image_editing, search, url_context stream pairs
- `dashscope/`: Also merge async_image_agent → image_agent
- `langdb/`: Merge agent_stream → agent
- `anthropic/skills/`: Delete `__init__.py` and `file_download_helper.py`

### Phase 4: Style Fixes on All Remaining Files (~450 files)

For all surviving files:
1. Read the file
2. Add module docstring if missing
3. Add section banners
4. Add `if __name__ == "__main__":` gate if missing
5. Remove emoji if present (see RESTRUCTURE_PLAN.md emoji table)
6. Do NOT change model providers, model IDs, or prompts

### Phase 5: Create README.md and TEST_LOG.md

For every directory and subdirectory. See RESTRUCTURE_PLAN.md Section 5 for the full list (~63 directories).

### Phase 6: Validate

```bash
# Run per provider directory
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/90_models/<provider>
```

## Key Merge Example

### Before: 4 files for basic usage (fireworks/)

`basic.py`:
```python
from agno.agent import Agent, RunOutput  # noqa
from agno.models.fireworks import Fireworks

agent = Agent(
    model=Fireworks(id="accounts/fireworks/models/llama-v3p1-405b-instruct"),
    markdown=True,
)
agent.print_response("Share a 2 sentence horror story")
```

`basic_stream.py`: Same but `stream=True`
`async_basic.py`: Same but `asyncio.run(agent.aprint_response(...))`
`async_basic_stream.py`: Same but async + stream

### After: 1 file

```python
"""
Fireworks Basic Usage
=============================

Demonstrates basic agent usage with Fireworks.
"""

from agno.agent import Agent
from agno.models.fireworks import Fireworks

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Fireworks(id="accounts/fireworks/models/llama-v3p1-405b-instruct"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a 2 sentence horror story")

    # --- Sync + Streaming ---
    agent.print_response("Share a 2 sentence horror story", stream=True)

    # --- Async ---
    import asyncio

    asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))

    # --- Async + Streaming ---
    asyncio.run(
        agent.aprint_response("Share a 2 sentence horror story", stream=True)
    )
```

## Important Notes

1. **Read before writing** — Do not apply changes to files you haven't read.
2. **Preserve model providers** — This is the most important rule. Every file uses a specific provider class and model ID.
3. **Preserve prompts** — Do not change test prompts or tasks.
4. **Preserve tool imports** — Tool-use files import specific tool classes. Keep them.
5. **Preserve unique files** — `db.py`, `knowledge.py`, `memory.py`, `retry.py`, image/audio/video/PDF input files, and provider-specific features are all unique. Do NOT merge them.
6. **Sub-API directories stay separate** — `openai/chat/` and `openai/responses/` use different model classes.
7. **No `__init__.py` files** — Cookbook directories don't use `__init__.py`.
8. **75 dashes** — `# ---------------------------------------------------------------------------` (75 dashes after `# `).
9. **Emoji removal** — Check all files but especially: `clients/`, `google/gemini/`, `xai/`, `anthropic/`, `openai/`, `vllm/`.
10. **Read the plan carefully** — The RESTRUCTURE_PLAN.md has per-provider reduction targets and special notes.
