# Restructuring Plan: `cookbook/91_tools/`

## 1. Executive Summary

### Current State

| Metric | Value |
|--------|-------|
| Directories | 13 (including mcp subdirs) |
| Total `.py` files (non-`__init__`) | ~197 |
| Root-level tool files | 118 |
| `__init__.py` files (to remove) | 5 |
| Fully style-compliant | 0 (~0%) |
| Have module docstring | ~124 (~63%) |
| Have section banners | ~4 (~2%) |
| Have `if __name__` gate | ~60 (~30%) |
| Contain emoji | 3 files |
| Directories with README.md | 5 / 13 |
| Directories with TEST_LOG.md | 0 / 13 |

### Key Problems

1. **Flat root directory with 118 files.** Each file is a unique tool demo (one per tool), so no merges needed here, but all need style fixes.

2. **Low style compliance.** Only ~2% have section banners, ~30% have main gates, ~63% have docstrings.

3. **8 sync/async pairs across subdirectories.** `tool_hooks/` and `tool_decorator/` each have sync/async duplicates that can be merged.

4. **5 unnecessary `__init__.py` files.** Cookbook directories should not have `__init__.py`.

5. **3 emoji violations.** In `mcp/filesystem.py`, `mcp/groq_mcp.py`, and `other/human_in_the_loop.py`.

6. **No TEST_LOG.md anywhere.** Zero directories have test logs.

7. **Missing READMEs.** 8 directories lack README.md.

### Overall Assessment

The second-largest cookbook section at ~197 files. Well-organized: the root directory has one file per tool (118 unique tool demos), and subdirectories group advanced patterns (MCP, hooks, decorators, exceptions). The main work is style standardization — nearly every file needs docstring formatting, section banners, and main gates added. Merges are limited to 8 sync/async pairs in `tool_hooks/` and `tool_decorator/`.

### Proposed Target

| Metric | Current | Target |
|--------|---------|--------|
| Files (non-`__init__`) | ~197 | ~189 |
| `__init__.py` files | 5 | 0 |
| Style compliance | ~0% | 100% |
| README coverage | 5/13 | All directories |
| TEST_LOG coverage | 0/13 | All directories |

---

## 2. Proposed Directory Structure

Keep all existing directories. The structure is already well-organized. No reorganization needed.

```
cookbook/91_tools/
├── <118 tool files>           # One file per tool (agentql, airflow, apify, ...)
├── async/                     # Async execution patterns (dissolve → merge into root)
├── exceptions/                # Exception handling patterns (retry, stop)
├── mcp/                       # MCP (Model Context Protocol) integrations
│   ├── dynamic_headers/       # Dynamic header client/server
│   ├── local_server/          # Local MCP server
│   ├── mcp_toolbox_demo/      # Database toolbox demo app
│   ├── sse_transport/         # SSE transport client/server
│   └── streamable_http_transport/ # HTTP streaming transport
├── models/                    # Model-specific tool features
├── other/                     # Advanced patterns (caching, human-in-loop, include/exclude)
├── tool_decorator/            # @tool decorator patterns
└── tool_hooks/                # Pre/post execution hooks
```

### Directory Descriptions

| Directory | Scope | Files |
|-----------|-------|-------|
| **Root** | One-file-per-tool demos | 118 |
| **async/** | Async execution demos (dissolve into root) | 2 |
| **exceptions/** | RetryAgentRun, StopAgentRun | 3 |
| **mcp/** | MCP server integrations (28 files + 4 subdirs) | ~40 |
| **models/** | Model-specific tool features (Gemini, Azure, etc.) | 6 |
| **other/** | Advanced tool patterns | 10 |
| **tool_decorator/** | @tool decorator usage | 8 |
| **tool_hooks/** | Pre/post hook patterns | 10 |

---

## 3. File Disposition Table

### Phase 1: Delete `__init__.py` Files (5 files)

| File | Action |
|------|--------|
| `91_tools/__init__.py` | DELETE |
| `async/__init__.py` | DELETE |
| `mcp/__init__.py` | DELETE |
| `models/__init__.py` | DELETE |
| `other/__init__.py` | DELETE |

### Phase 2: Merge Sync/Async Pairs

#### tool_hooks/ — 4 pairs → 4 files (delete 4)

| Sync File | Async File | Merged File | Action |
|-----------|------------|-------------|--------|
| `tool_hook.py` | `tool_hook_async.py` | `tool_hook.py` | MERGE: add async variant to main gate |
| `pre_and_post_hooks.py` | `async_pre_and_post_hooks.py` | `pre_and_post_hooks.py` | MERGE: add async variant to main gate |
| `tool_hook_in_toolkit.py` | `tool_hook_in_toolkit_async.py` | `tool_hook_in_toolkit.py` | MERGE: add async variant to main gate |
| `tool_hooks_in_toolkit_nested.py` | `tool_hooks_in_toolkit_nested_async.py` | `tool_hooks_in_toolkit_nested.py` | MERGE: add async variant to main gate |

Remaining unique files in tool_hooks/ (no merge needed):
- `tool_hook_in_toolkit_with_state.py` — KEEP+FIX
- `tool_hook_in_toolkit_with_state_nested.py` — KEEP+FIX

#### tool_decorator/ — 1 pair → 1 file (delete 1)

| Sync File | Async File | Merged File | Action |
|-----------|------------|-------------|--------|
| `tool_decorator.py` | `tool_decorator_async.py` | `tool_decorator.py` | MERGE: add async variant to main gate |

Remaining unique files in tool_decorator/ (no merge needed):
- `async_tool_decorator.py` — KEEP+FIX (demonstrates async-only @tool decorator, different from sync)
- `cache_tool_calls.py` — KEEP+FIX
- `stop_after_tool_call.py` — KEEP+FIX
- `tool_decorator_on_class_method.py` — KEEP+FIX
- `tool_decorator_with_hook.py` — KEEP+FIX
- `tool_decorator_with_instructions.py` — KEEP+FIX

#### Root — 2 pairs → 2 files (delete 2)

| Sync File | Async File | Merged File | Action |
|-----------|------------|-------------|--------|
| `custom_tools.py` | `custom_async_tools.py` | `custom_tools.py` | MERGE: add async examples to main gate |
| `zep_tools.py` | `zep_async_tools.py` | `zep_tools.py` | MERGE: add async examples to main gate |

#### async/ — Dissolve (delete 2, redistribute content)

| File | Action |
|------|--------|
| `async/groq-demo.py` | CUT — nearly identical to openai-demo.py, both just demo async execution |
| `async/openai-demo.py` | CUT — generic async pattern already shown in other files |

The `async/` directory demonstrates a pattern (async tool execution) that is already shown in every merge above. These two files add no unique value.

### Phase 3: Style Fixes on All Remaining Files (~189 files)

All surviving files need:
1. Module docstring with title + `=====` underline (add if missing, reformat if present)
2. Section banners (`# ---------------------------------------------------------------------------`)
3. `if __name__ == "__main__":` gate (add if missing)
4. Remove emoji (3 files)

### Phase 4: Emoji Removal (3 files)

| File | Emoji | Location |
|------|-------|----------|
| `mcp/filesystem.py` | `📁` | Module docstring |
| `mcp/groq_mcp.py` | `📁` | Module docstring |
| `other/human_in_the_loop.py` | `🤝` | Module docstring |

### Phase 5: Root Tool Files (118 files — all KEEP+FIX)

All root-level tool files are unique (one per tool) and need only style fixes. Partial listing:

| File | Demonstrates |
|------|-------------|
| `agentql_tools.py` | AgentQL web scraping |
| `airflow_tools.py` | Apache Airflow integration |
| `apify_tools.py` | Apify web scraping |
| `arxiv_tools.py` | ArXiv paper search |
| `aws_lambda_tools.py` | AWS Lambda invocation |
| `aws_ses_tools.py` | AWS SES email |
| `baidusearch_tools.py` | Baidu search |
| `bitbucket_tools.py` | Bitbucket integration |
| `brandfetch_tools.py` | Brand info fetching |
| `bravesearch_tools.py` | Brave search |
| `brightdata_tools.py` | Bright Data scraping |
| `browserbase_tools.py` | Browserbase automation |
| `calcom_tools.py` | Cal.com scheduling |
| `calculator_tools.py` | Calculator toolkit |
| `cartesia_tools.py` | Cartesia TTS |
| `clickup_tools.py` | ClickUp project management |
| `composio_tools.py` | Composio integration |
| `confluence_tools.py` | Confluence wiki |
| `crawl4ai_tools.py` | Crawl4AI scraping |
| `csv_tools.py` | CSV file operations |
| `custom_api_tools.py` | Custom API wrapping |
| `custom_tool_events.py` | Tool event handling |
| `dalle_tools.py` | DALL-E image generation |
| `daytona_tools.py` | Daytona dev environments |
| `desi_vocal_tools.py` | DesiVocal TTS |
| `discord_tools.py` | Discord integration |
| `docker_tools.py` | Docker operations |
| `duckdb_tools.py` | DuckDB analytics |
| `duckduckgo_tools.py` | DuckDuckGo search |
| `e2b_tools.py` | E2B code execution |
| `elevenlabs_tools.py` | ElevenLabs TTS |
| `email_tools.py` | Email sending |
| ... | *(remaining 85+ tool files, all unique)* |

### Phase 6: Subdirectory Files

#### exceptions/ (3 files — all KEEP+FIX)

| File | Demonstrates |
|------|-------------|
| `retry_tool_call.py` | RetryAgentRun exception |
| `retry_tool_call_from_post_hook.py` | Retry from post-hook |
| `stop_agent_exception.py` | StopAgentRun exception |

#### models/ (6 files — all KEEP+FIX)

| File | Demonstrates |
|------|-------------|
| `azure_openai_tools.py` | Azure OpenAI tool usage |
| `gemini_image_generation.py` | Gemini image generation tools |
| `gemini_video_generation.py` | Gemini video generation tools |
| `morph.py` | Morph model demo |
| `nebius_tools.py` | Nebius tools |
| `openai_tools.py` | OpenAI transcription + image tools |

#### other/ (10 files — all KEEP+FIX)

| File | Demonstrates |
|------|-------------|
| `add_tool_after_initialization.py` | Dynamic tool addition |
| `cache_tool_calls.py` | Tool result caching |
| `complex_input_types.py` | Complex type handling |
| `human_in_the_loop.py` | User confirmation pattern |
| `include_exclude_tools.py` | Tool filtering |
| `include_exclude_tools_custom_toolkit.py` | Custom toolkit filtering |
| `session_state_tool.py` | Session state access |
| `stop_after_tool_call.py` | Stop after tool execution |
| `stop_after_tool_call_dual_inheritance.py` | Dual inheritance pattern |
| `stop_after_tool_call_in_toolkit.py` | Stop in toolkit |

#### mcp/ (28 root + 10 in subdirs — all KEEP+FIX)

All MCP files are unique integrations or transport demos. No merges needed. Key files:

| File | Demonstrates |
|------|-------------|
| `agno_mcp.py` | Basic MCP pattern |
| `filesystem.py` | MCP filesystem server (remove emoji) |
| `github.py` | GitHub MCP |
| `groq_mcp.py` | Groq + MCP (remove emoji) |
| `multiple_servers.py` | Multiple MCP servers |
| `parallel.py` | Parallel MCP execution |
| `sequential_thinking.py` | Sequential thinking |
| `dynamic_headers/client.py` | Dynamic header client |
| `dynamic_headers/server.py` | Dynamic header server |
| `local_server/client.py` | Local MCP client |
| `local_server/server.py` | Local MCP server |
| `mcp_toolbox_demo/agent.py` | Hotel management agent |
| `sse_transport/client.py` | SSE client |
| `sse_transport/server.py` | SSE server |
| `streamable_http_transport/client.py` | HTTP streaming client |
| `streamable_http_transport/server.py` | HTTP streaming server |

---

## 4. Reduction Summary

| Category | Files Removed | Method |
|----------|--------------|--------|
| `__init__.py` deletion | 5 | Delete |
| Sync/async merges (tool_hooks) | 4 | Merge into sync file |
| Sync/async merge (tool_decorator) | 1 | Merge into sync file |
| Sync/async merges (root) | 2 | Merge into sync file |
| async/ directory dissolution | 2 | Cut (redundant content) |
| **Total removed** | **14** | |
| **Final file count** | **~189** | (from ~197 + 5 __init__.py) |

---

## 5. Missing Documentation

### README.md Status

| Directory | Has README.md | Action |
|-----------|:------------:|--------|
| `91_tools/` | YES | Update |
| `async/` | NO | N/A (dissolving) |
| `exceptions/` | NO | CREATE |
| `mcp/` | YES | Keep |
| `mcp/dynamic_headers/` | NO | CREATE |
| `mcp/local_server/` | NO | CREATE |
| `mcp/mcp_toolbox_demo/` | YES | Keep |
| `mcp/sse_transport/` | YES | Keep |
| `mcp/streamable_http_transport/` | YES | Keep |
| `models/` | NO | CREATE |
| `other/` | NO | CREATE |
| `tool_decorator/` | NO | CREATE |
| `tool_hooks/` | NO | CREATE |

### TEST_LOG.md Status

All 13 directories need TEST_LOG.md created. (async/ excluded since it's being dissolved.)

---

## 6. Recommended Template

### Standard Tool Demo (root files)

```python
"""
<ToolName> Tools
=============================

Demonstrates agent usage with <ToolName> for <what it does>.
"""

from agno.agent import Agent
from agno.tools.<tool_module> import <ToolClass>

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

### Merged Sync/Async File (tool_hooks, tool_decorator)

```python
"""
<Feature Name>
=============================

Demonstrates <what this feature does>.
"""

from agno.agent import Agent
from agno.tools.<tool_module> import <ToolClass>

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
def my_hook(context):
    ...

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    tools=[<ToolClass>()],
    tool_hooks=[my_hook],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("<prompt>")

    # --- Async ---
    import asyncio

    asyncio.run(agent.aprint_response("<prompt>"))
```

### MCP Integration

```python
"""
<MCP Service> via MCP
=============================

Demonstrates using <MCP Service> through the Model Context Protocol.
"""

import asyncio

from agno.agent import Agent
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
async def run():
    async with MCPTools(...) as mcp_tools:
        agent = Agent(tools=[mcp_tools], markdown=True)
        await agent.aprint_response("<prompt>")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(run())
```

---

## 7. Validation

```bash
# Run per subdirectory
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/91_tools --recursive

# Or per subdirectory
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/91_tools/mcp --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/91_tools/tool_hooks
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/91_tools/tool_decorator
```
