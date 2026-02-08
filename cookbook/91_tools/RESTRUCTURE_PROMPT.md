# Implement `cookbook/91_tools/` Restructuring

You are restructuring the `cookbook/91_tools/` directory of the Agno AI agent framework. The full plan is attached as `RESTRUCTURE_PLAN.md`. Read it completely before starting.

## Context

- **Agno** is a Python AI agent framework. The `cookbook/` directory contains runnable example scripts.
- This is the **second-largest cookbook section** at ~197 files across 13 directories.
- The goal is to reduce to ~189 files by merging 7 sync/async pairs, dissolving `async/`, deleting 5 `__init__.py` files, achieving 100% style compliance, and adding documentation.
- The virtual environment for running cookbooks is at `.venvs/demo/bin/python`.
- The style checker is at `cookbook/scripts/check_cookbook_pattern.py`.

## CRITICAL: Read Each File Before Modifying

**Do NOT apply blanket changes across files.** Each tool file uses specific imports, tool classes, and patterns. You must:

1. **Read each file individually** before making any changes.
2. **Understand what the file does** — its tool class, imports, and feature demonstrated.
3. **Preserve the existing logic exactly** — only restructure the layout (add banners, docstring, main gate).
4. **For MERGE operations**, read ALL source files first, then combine thoughtfully.

## CRITICAL: Do NOT Change Tool Imports or Logic

Each file uses **specific tool classes and configurations**. Do NOT:
- Change tool imports (e.g., `from agno.tools.hackernews import HackerNewsTools`)
- Change model imports or model IDs
- Replace one tool with another
- Change prompts or task descriptions
- Remove or modify custom function definitions

## Merge Pattern — Sync/Async Into One

The only merge pattern in this section collapses sync/async variants of the same feature into a single file. The async file adds `asyncio.run(agent.aprint_response(...))` as an additional section in the main gate.

### Before: 2 files

`tool_hook.py`:
```python
agent.print_response("...")
```

`tool_hook_async.py`:
```python
asyncio.run(agent.aprint_response("..."))
```

### After: 1 file

```python
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("...")

    # --- Async ---
    import asyncio

    asyncio.run(agent.aprint_response("..."))
```

## Style Guide Template

```python
"""
<Tool Name> Tools
=============================

Demonstrates agent usage with <Tool Name>.
"""

from agno.agent import Agent
from agno.tools.<module> import <ToolClass>

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    tools=[<ToolClass>()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("<prompt>", stream=True)
```

### Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Setup (if needed) → Create Agent → Run Agent
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere
7. **Preserve tool imports** — Do NOT change tool classes, model imports, or model IDs
8. **Preserve custom functions** — Many files define helper functions used as tools. Keep them exactly.
9. **Self-contained** — Each file must be independently runnable

## Execution Plan

### Phase 1: Delete All `__init__.py` Files (5 files)

```bash
find cookbook/91_tools -name "__init__.py" -delete
```

### Phase 2: Merge Sync/Async Pairs (7 merges, delete 7 files)

#### tool_hooks/ — 4 merges

For each pair:
1. Read both files
2. Use sync file as base
3. Add async variant as labeled section in the main gate
4. Delete the async file

| Sync File | Async File (delete after merge) |
|-----------|--------------------------------|
| `tool_hook.py` | `tool_hook_async.py` |
| `pre_and_post_hooks.py` | `async_pre_and_post_hooks.py` |
| `tool_hook_in_toolkit.py` | `tool_hook_in_toolkit_async.py` |
| `tool_hooks_in_toolkit_nested.py` | `tool_hooks_in_toolkit_nested_async.py` |

#### tool_decorator/ — 1 merge

| Sync File | Async File (delete after merge) |
|-----------|--------------------------------|
| `tool_decorator.py` | `tool_decorator_async.py` |

**Note:** `async_tool_decorator.py` is a DIFFERENT file (demonstrates async-only @tool decorator). Do NOT merge or delete it.

#### Root — 2 merges

| Sync File | Async File (delete after merge) |
|-----------|--------------------------------|
| `custom_tools.py` | `custom_async_tools.py` |
| `zep_tools.py` | `zep_async_tools.py` |

### Phase 3: Dissolve async/ Directory (delete 2 files + directory)

The `async/groq-demo.py` and `async/openai-demo.py` demonstrate async tool execution, which is now shown in every merged file above. Delete both files and the `async/` directory.

### Phase 4: Style Fixes on All Remaining Files (~189 files)

For all surviving files:
1. Read the file
2. Add module docstring with title + `=====` underline if missing (reformat if present)
3. Add section banners (`# ---------------------------------------------------------------------------`, 75 dashes)
4. Add `if __name__ == "__main__":` gate if missing
5. Remove emoji if present (3 files: `mcp/filesystem.py`, `mcp/groq_mcp.py`, `other/human_in_the_loop.py`)
6. Do NOT change tool imports, model imports, prompts, or custom functions

**Work through directories in this order:**
1. Root tool files (alphabetical, ~118 files)
2. `exceptions/` (3 files)
3. `mcp/` root (28 files)
4. `mcp/` subdirectories (10 files across 5 subdirs)
5. `models/` (6 files)
6. `other/` (10 files)
7. `tool_decorator/` (7 files after merge)
8. `tool_hooks/` (6 files after merge)

### Phase 5: Create README.md and TEST_LOG.md

Create for every directory that needs them. See RESTRUCTURE_PLAN.md Section 5 for the status table.

Directories needing README.md: `exceptions/`, `mcp/dynamic_headers/`, `mcp/local_server/`, `models/`, `other/`, `tool_decorator/`, `tool_hooks/`

All surviving directories need TEST_LOG.md.

### Phase 6: Validate

```bash
# Run on entire section
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/91_tools --recursive

# Or per subdirectory
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/91_tools/tool_hooks
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/91_tools/mcp --recursive
```

## Important Notes

1. **Read before writing** — Do not apply changes to files you haven't read.
2. **Preserve tool imports** — This is the most important rule. Every file uses specific tool classes.
3. **Preserve custom functions** — Many root files define functions used as tools (e.g., `get_top_hackernews_stories`). Keep them exactly.
4. **Preserve prompts** — Do not change test prompts or tasks.
5. **MCP files are async by nature** — Most MCP files use `async with MCPTools(...)`. Keep this pattern.
6. **Server files** — `mcp/*/server.py` files are servers, not agent demos. They still need style fixes but the pattern differs.
7. **No `__init__.py` files** — Cookbook directories don't use `__init__.py`.
8. **75 dashes** — `# ---------------------------------------------------------------------------` (75 dashes after `# `).
9. **Emoji removal** — Only 3 files: `mcp/filesystem.py`, `mcp/groq_mcp.py`, `other/human_in_the_loop.py`.
10. **`async/` directory dissolves completely** — Do not redistribute, just delete.
