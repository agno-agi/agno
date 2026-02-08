# Restructuring Plan: `cookbook/92_integrations/`

## 1. Executive Summary

### Current State

| Metric | Value |
|--------|-------|
| Directories | 8 (including nested subdirs; +1 for incoming surrealdb/) |
| Total `.py` files (non-`__init__`) | 32 (+5 incoming from 11_memory) |
| `__init__.py` files (to remove) | 7 |
| Fully style-compliant | 0 (0%) |
| Have module docstring | ~19 (~59%) |
| Have section banners | 0 (0%) |
| Have `if __name__` gate | ~11 (~34%) |
| Contain emoji | 7 files |
| Directories with README.md | 4 / 7 |
| Directories with TEST_LOG.md | 0 / 7 |

### Key Problems

1. **Zero section banners.** No file has the required `# ---------------------------------------------------------------------------` style banners.

2. **65% missing main gates.** 21 of 32 files lack `if __name__ == "__main__":` gates.

3. **7 emoji violations.** Flag emojis (US, EU, house) in Langfuse and Logfire endpoint comments across observability files.

4. **7 unnecessary `__init__.py` files.** Cookbook directories should not have `__init__.py`.

5. **1 sync/async pair to merge.** The observability/teams/ directory has sync and async variants of the same Langfuse team tracing example.

6. **No TEST_LOG.md anywhere.** Zero directories have test logs.

7. **Typo in filename.** `observability/workflows/langfuse_via_openinference_workfows.py` — "workfows" should be "workflows".

8. **Incoming SurrealDB files.** 5 SurrealDB memory-manager examples are being relocated here from `cookbook/11_memory/memory_manager/surrealdb/`. They demonstrate SurrealDB as a MemoryManager backend — an integration, not a core memory feature.

### Overall Assessment

A small, well-scoped section with 32 files (+5 incoming) across 5 integration categories: A2A (agent-to-agent), Discord bots, memory services, observability platforms, and SurrealDB. The observability subdirectory is the largest at ~18 files. Most work is style standardization — nearly every file needs banners, main gates, and docstring formatting. Only 1 merge is needed. The emoji violations are all the same pattern (flag emojis for data region comments).

### Proposed Target

| Metric | Current | Target |
|--------|---------|--------|
| Files (non-`__init__`) | 32 (+5 incoming) | 36 |
| `__init__.py` files | 7 | 0 |
| Style compliance | 0% | 100% |
| README coverage | 4/7 | All directories |
| TEST_LOG coverage | 0/7 | All directories |

---

## 2. Proposed Directory Structure

Keep all existing directories. The structure is already well-organized.

```
cookbook/92_integrations/
├── a2a/                       # Agent-to-Agent protocol
│   └── basic_agent/           # Basic A2A example (server + client)
├── discord/                   # Discord bot integrations
├── memory/                    # External memory services (Mem0, Memori, Zep)
├── observability/             # Tracing and monitoring platforms
│   ├── teams/                 # Multi-agent team tracing
│   └── workflows/             # Workflow tracing
└── surrealdb/                 # SurrealDB as MemoryManager backend (incoming from 11_memory)
```

### Directory Descriptions

| Directory | Scope | Files |
|-----------|-------|-------|
| **a2a/basic_agent/** | A2A server, executor, and client | 3 |
| **discord/** | Discord bot patterns (basic, media, memory) | 3 |
| **memory/** | Mem0, Memori, Zep integrations | 3 |
| **observability/** | 14 observability platform integrations | 14 |
| **observability/teams/** | Team tracing (Langfuse) | 2 → 1 |
| **observability/workflows/** | Workflow tracing (Phoenix, Langfuse) | 2 |
| **surrealdb/** | SurrealDB MemoryManager backend (incoming) | 5 |

---

## 3. File Disposition Table

### Phase 1: Delete `__init__.py` Files (7 files)

| File | Action |
|------|--------|
| `92_integrations/__init__.py` | DELETE |
| `a2a/__init__.py` | DELETE |
| `a2a/basic_agent/__init__.py` | DELETE |
| `discord/__init__.py` | DELETE |
| `memory/__init__.py` | DELETE |
| `observability/__init__.py` | DELETE |
| `observability/teams/__init__.py` | DELETE |

### Phase 2: Merge Sync/Async Pair (1 merge)

#### observability/teams/ — 1 pair → 1 file

| Sync File | Async File | Merged File | Action |
|-----------|------------|-------------|--------|
| `langfuse_via_openinference_team.py` | `langfuse_via_openinference_async_team.py` | `langfuse_via_openinference_team.py` | MERGE: add async team example to main gate |

### Phase 3: Rename Typo File (1 rename)

| Current Name | New Name | Reason |
|-------------|----------|--------|
| `observability/workflows/langfuse_via_openinference_workfows.py` | `observability/workflows/langfuse_via_openinference_workflows.py` | Fix typo: "workfows" → "workflows" |

### Phase 4: Style Fixes on All Files (31 files)

#### a2a/basic_agent/ (3 files — all KEEP+FIX)

| File | Docstring | Main Gate | Emoji | Demonstrates |
|------|:---------:|:---------:|:-----:|-------------|
| `__main__.py` | ADD | HAS | None | A2A server bootstrap |
| `basic_agent.py` | ADD | ADD | None | AgentExecutor implementation |
| `client.py` | ADD | HAS | None | A2A client usage |

#### discord/ (3 files — all KEEP+FIX)

| File | Docstring | Main Gate | Emoji | Demonstrates |
|------|:---------:|:---------:|:-----:|-------------|
| `basic.py` | ADD | HAS | None | Simple Discord bot |
| `agent_with_media.py` | ADD | HAS | None | Gemini media processing bot |
| `agent_with_user_memory.py` | ADD | HAS | None | Memory-enabled Discord bot |

#### memory/ (3 files — all KEEP+FIX)

| File | Docstring | Main Gate | Emoji | Demonstrates |
|------|:---------:|:---------:|:-----:|-------------|
| `mem0_integration.py` | ADD | ADD | None | Mem0 memory service |
| `memori_integration.py` | ADD | HAS | None | Memori integration |
| `zep_integration.py` | ADD | ADD | None | Zep memory tools |

#### observability/ root (14 files — all KEEP+FIX)

| File | Docstring | Main Gate | Emoji | Demonstrates |
|------|:---------:|:---------:|:-----:|-------------|
| `agent_ops.py` | HAS | ADD | None | AgentOps integration |
| `arize_phoenix_moving_traces_to_different_projects.py` | HAS | ADD | None | Phoenix project routing |
| `arize_phoenix_via_openinference.py` | HAS | ADD | None | Phoenix cloud via OpenTelemetry |
| `arize_phoenix_via_openinference_local.py` | HAS | ADD | None | Phoenix local instance |
| `atla_op.py` | HAS | ADD | None | Atla observability |
| `langfuse_via_openinference.py` | HAS | ADD | REMOVE | Langfuse via OpenTelemetry |
| `langfuse_via_openinference_response_model.py` | HAS | ADD | REMOVE | Langfuse with structured output |
| `langfuse_via_openlit.py` | HAS | ADD | REMOVE | Langfuse via OpenLIT SDK |
| `langsmith_via_openinference.py` | HAS | ADD | None | LangSmith integration |
| `langtrace_op.py` | HAS | ADD | None | Langtrace SDK |
| `langwatch_op.py` | HAS | ADD | None | LangWatch integration |
| `logfire_via_openinference.py` | HAS | ADD | REMOVE | Pydantic Logfire integration |
| `maxim_ops.py` | HAS | HAS | None | Maxim logging |
| `opik_via_openinference.py` | HAS | HAS | None | Opik integration |
| `trace_to_database.py` | HAS | ADD | None | SQLite trace storage |
| `traceloop_op.py` | HAS | ADD | None | Traceloop integration |
| `weave_op.py` | HAS | ADD | None | W&B Weave logging |

#### observability/teams/ (1 file after merge — KEEP+FIX)

| File | Docstring | Main Gate | Emoji | Demonstrates |
|------|:---------:|:---------:|:-----:|-------------|
| `langfuse_via_openinference_team.py` | ADD | HAS | REMOVE | Multi-agent team tracing |

#### observability/workflows/ (2 files — all KEEP+FIX)

| File | Docstring | Main Gate | Emoji | Demonstrates |
|------|:---------:|:---------:|:-----:|-------------|
| `arize_phoenix_via_openinference_workflow.py` | HAS | HAS | None | Phoenix workflow tracing |
| `langfuse_via_openinference_workflows.py` | HAS | HAS | REMOVE | Langfuse workflow tracing |

### Phase 4b: Incoming SurrealDB Files (5 files from 11_memory — all KEEP+FIX)

These files arrive from `cookbook/11_memory/memory_manager/surrealdb/` and need style fixes:

| Source File | New Location | Demonstrates |
|-------------|-------------|-------------|
| `standalone_memory_surreal.py` | `surrealdb/standalone_memory_surreal.py` | CRUD memory operations with SurrealDB |
| `memory_creation.py` | `surrealdb/memory_creation.py` | Memory from messages with SurrealDB |
| `custom_memory_instructions.py` | `surrealdb/custom_memory_instructions.py` | Custom capture instructions with SurrealDB |
| `memory_search_surreal.py` | `surrealdb/memory_search_surreal.py` | Memory retrieval with SurrealDB |
| `db_tools_control.py` | `surrealdb/db_tools_control.py` | Fine-grained operation control with SurrealDB |

All files need: module docstring reformat, section banners, `if __name__ == "__main__":` gate.

### Phase 5: Emoji Removal (7 files → 6 after merge)

All emoji violations are flag indicators in endpoint URL comments. Replace with text labels.

| File | Emoji | Replace With |
|------|-------|-------------|
| `observability/langfuse_via_openinference.py` | `🇺🇸` `🇪🇺` `🏠` | `US` `EU` `Local` |
| `observability/langfuse_via_openinference_response_model.py` | `🇺🇸` `🇪🇺` `🏠` | `US` `EU` `Local` |
| `observability/langfuse_via_openlit.py` | `🇺🇸` `🇪🇺` `🏠` | `US` `EU` `Local` |
| `observability/logfire_via_openinference.py` | `🇺🇸` `🇪🇺` `🏠` | `US` `EU` `Local` |
| `observability/teams/langfuse_via_openinference_async_team.py` | `🇺🇸` `🇪🇺` `🏠` | (merged into team.py) |
| `observability/teams/langfuse_via_openinference_team.py` | `🇺🇸` `🇪🇺` `🏠` | `US` `EU` `Local` |
| `observability/workflows/langfuse_via_openinference_workfows.py` | `🇺🇸` `🇪🇺` `🏠` | `US` `EU` `Local` |

---

## 4. Reduction Summary

| Category | Files Changed | Method |
|----------|--------------|--------|
| `__init__.py` deletion | -7 | Delete |
| Sync/async merge (teams/) | -1 | Merge into sync file |
| Incoming SurrealDB files | +5 | Move from 11_memory |
| **Net change** | **-3** | |
| **Final file count** | **36** | (32 - 1 + 5 = 36, plus 7 __init__.py removed) |

---

## 5. Missing Documentation

### README.md Status

| Directory | Has README.md | Action |
|-----------|:------------:|--------|
| `92_integrations/` | YES | Update |
| `a2a/` | YES | Keep |
| `a2a/basic_agent/` | YES | Keep |
| `discord/` | YES | Keep |
| `memory/` | NO | CREATE |
| `observability/` | YES | Keep |
| `observability/teams/` | NO | CREATE |
| `observability/workflows/` | NO | CREATE |
| `surrealdb/` | NO | CREATE |

### TEST_LOG.md Status

All 8 directories need TEST_LOG.md created (including incoming surrealdb/).

---

## 6. Recommended Template

### Observability Integration

```python
"""
<Platform> Integration
=============================

Demonstrates agent tracing with <Platform> via <method>.
"""

import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://..."
os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = "..."

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("Share a 2 sentence horror story", stream=True)
```

### Memory Integration

```python
"""
<Service> Memory Integration
=============================

Demonstrates using <Service> for agent memory.
"""

from agno.agent import Agent

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# ... service-specific setup ...

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(...)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("...", stream=True)
```

---

## 7. Validation

```bash
# Run on entire section
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/92_integrations --recursive
```
