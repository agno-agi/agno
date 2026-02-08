# Implement `cookbook/92_integrations/` Restructuring

You are restructuring the `cookbook/92_integrations/` directory of the Agno AI agent framework. The full plan is attached as `RESTRUCTURE_PLAN.md`. Read it completely before starting.

## Context

- **Agno** is a Python AI agent framework. The `cookbook/` directory contains runnable example scripts.
- This is a **small section** with 32 existing files (+5 incoming from 11_memory) across 8 directories.
- The goal is to reach 36 files by merging 1 sync/async pair, absorbing 5 SurrealDB files from `11_memory`, deleting 7 `__init__.py` files, fixing a filename typo, achieving 100% style compliance, and adding documentation.
- The virtual environment for running cookbooks is at `.venvs/demo/bin/python`.
- The style checker is at `cookbook/scripts/check_cookbook_pattern.py`.

## CRITICAL: Read Each File Before Modifying

**Do NOT apply blanket changes across files.** Each integration uses specific imports, service configurations, and patterns. You must:

1. **Read each file individually** before making any changes.
2. **Understand what the file does** — its integration target, setup requirements, and feature demonstrated.
3. **Preserve the existing logic exactly** — only restructure the layout (add banners, docstring, main gate).
4. **For the MERGE operation**, read BOTH source files first, then combine thoughtfully.

## CRITICAL: Do NOT Change Integration Logic

Each file uses **specific service configurations and API endpoints**. Do NOT:
- Change environment variable names or values
- Change model imports or model IDs
- Change integration-specific imports (e.g., `from agno.tools.zep import ZepTools`)
- Remove or modify endpoint URLs (only remove emoji from comments)
- Change prompts or task descriptions

## Style Guide Template

```python
"""
<Integration> Integration
=============================

Demonstrates <what this demonstrates>.
"""

import os

from agno.agent import Agent
from agno.models.<provider> import <ProviderClass>

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
os.environ["KEY"] = "value"

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
    agent.print_response("Share a 2 sentence horror story", stream=True)
```

### Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Setup → Create Agent → Run Agent (Setup is needed for most observability files)
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere (replace flag emojis with text: `US`, `EU`, `Local`)
7. **Preserve integration logic** — Do NOT change service configurations, endpoints, or API keys
8. **Self-contained** — Each file must be independently runnable

## Execution Plan

### Phase 1: Delete All `__init__.py` Files (7 files)

```bash
find cookbook/92_integrations -name "__init__.py" -delete
```

### Phase 2: Merge Sync/Async Pair (1 merge)

In `observability/teams/`:
1. Read both `langfuse_via_openinference_team.py` and `langfuse_via_openinference_async_team.py`
2. Use sync file as base
3. Add async team example as labeled section in the main gate
4. Delete `langfuse_via_openinference_async_team.py`

### Phase 3: Rename Typo File

```bash
mv cookbook/92_integrations/observability/workflows/langfuse_via_openinference_workfows.py \
   cookbook/92_integrations/observability/workflows/langfuse_via_openinference_workflows.py
```

### Phase 3b: Receive Incoming SurrealDB Files (5 files from 11_memory)

The `cookbook/11_memory/memory_manager/surrealdb/` directory is being relocated here. These files demonstrate SurrealDB as a MemoryManager backend — an integration, not a core memory feature.

```bash
mkdir -p cookbook/92_integrations/surrealdb
mv cookbook/11_memory/memory_manager/surrealdb/standalone_memory_surreal.py cookbook/92_integrations/surrealdb/
mv cookbook/11_memory/memory_manager/surrealdb/memory_creation.py cookbook/92_integrations/surrealdb/
mv cookbook/11_memory/memory_manager/surrealdb/custom_memory_instructions.py cookbook/92_integrations/surrealdb/
mv cookbook/11_memory/memory_manager/surrealdb/memory_search_surreal.py cookbook/92_integrations/surrealdb/
mv cookbook/11_memory/memory_manager/surrealdb/db_tools_control.py cookbook/92_integrations/surrealdb/
rmdir cookbook/11_memory/memory_manager/surrealdb
```

### Phase 4: Style Fixes on All Remaining Files (36 files)

For all surviving files:
1. Read the file
2. Add module docstring with title + `=====` underline if missing
3. Add section banners (`# ---------------------------------------------------------------------------`, 75 dashes)
4. Add `if __name__ == "__main__":` gate if missing
5. Remove emoji if present (replace flag emojis `🇺🇸` `🇪🇺` `🏠` with `US` `EU` `Local`)
6. Do NOT change integration-specific logic, endpoints, or configurations

**Work through directories in this order:**
1. `a2a/basic_agent/` (3 files)
2. `discord/` (3 files)
3. `memory/` (3 files)
4. `observability/` root (14 files)
5. `observability/teams/` (1 file after merge)
6. `observability/workflows/` (2 files)
7. `surrealdb/` (5 files, incoming from 11_memory)

### Phase 5: Create README.md and TEST_LOG.md

Create for directories that need them:
- **README.md needed:** `memory/`, `observability/teams/`, `observability/workflows/`, `surrealdb/`
- **TEST_LOG.md needed:** All 8 directories

### Phase 6: Validate

```bash
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/92_integrations --recursive
```

## Emoji Removal Guide

All emoji violations are the same pattern — flag emojis in URL comments. Replace like this:

**Before:**
```python
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://us.cloud.langfuse.com/..."  # 🇺🇸 US data region
# os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://cloud.langfuse.com/..."  # 🇪🇺 EU data region
# os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:3000/..."  # 🏠 Local deployment
```

**After:**
```python
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://us.cloud.langfuse.com/..."  # US data region
# os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://cloud.langfuse.com/..."  # EU data region
# os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:3000/..."  # Local deployment
```

Files with emoji:
1. `observability/langfuse_via_openinference.py`
2. `observability/langfuse_via_openinference_response_model.py`
3. `observability/langfuse_via_openlit.py`
4. `observability/logfire_via_openinference.py`
5. `observability/teams/langfuse_via_openinference_team.py` (after merge)
6. `observability/workflows/langfuse_via_openinference_workflows.py` (after rename)

## Important Notes

1. **Read before writing** — Do not apply changes to files you haven't read.
2. **Preserve integration logic** — This is the most important rule. Every file uses specific service configurations.
3. **Preserve prompts** — Do not change test prompts or tasks.
4. **A2A files are special** — `__main__.py` and `basic_agent.py` are server components, not typical agent demos.
5. **Observability setup blocks** — Most observability files have `os.environ` setup blocks. These go in the Setup section.
6. **No `__init__.py` files** — Cookbook directories don't use `__init__.py`.
7. **75 dashes** — `# ---------------------------------------------------------------------------` (75 dashes after `# `).
8. **Fix the typo** — Rename `langfuse_via_openinference_workfows.py` to `langfuse_via_openinference_workflows.py`.
9. **SurrealDB files incoming** — 5 files arrive from `cookbook/11_memory/memory_manager/surrealdb/`. They demonstrate SurrealDB as a MemoryManager backend. Style-fix them alongside the other files.
