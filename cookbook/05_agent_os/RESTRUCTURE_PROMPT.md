# Implement `cookbook/05_agent_os/` Restructuring

You are restructuring the `cookbook/05_agent_os/` directory of the Agno AI agent framework. The full plan is attached as `RESTRUCTURE_PLAN.md`. Read it completely before starting.

## Context

- **Agno** is a Python AI agent framework. The `cookbook/` directory contains runnable example scripts.
- **AgentOS** examples are **server apps**, not standalone scripts. They use `AgentOS.serve()` and `agent_os.get_app()`.
- The goal is to consolidate ~178 files down to ~161 files by merging sync/async DB pairs, consolidating tracing/dbs duplicates, merging schema files, redistributing root files, and achieving 100% style compliance.
- Every surviving file must comply with the style guide (see Template section below).
- The virtual environment for running cookbooks is at `.venvs/demo/bin/python`.
- The style checker is at `cookbook/scripts/check_cookbook_pattern.py`.

## CRITICAL: Read Each File Before Modifying

**Do NOT apply blanket changes across files using batch scripts or regex-based rewrites.** Every file in this cookbook has unique AgentOS configurations, agent setups, database backends, interface types, middleware, and logic. You must:

1. **Read each file individually** before making any changes to it.
2. **Understand what the file does** — its AgentOS configuration, agent definitions, database setup, interface type, middleware stack, and serve logic.
3. **Preserve the existing logic exactly** — only restructure the layout (add banners, docstring, main gate). Do not change model names, database URLs, agent configurations, middleware settings, or interface parameters that already exist in the file.
4. **For MERGE operations**, read ALL source files first, then combine their unique content thoughtfully. Don't just concatenate.
5. **For REWRITE operations**, read the existing file first to understand the AgentOS config, then rebuild from scratch following the template while keeping the same configuration.

This is a careful, file-by-file task. It will take time. Do not rush it.

## CRITICAL: AgentOS `app` Must Be at Module Level

AgentOS files are fundamentally different from agents/teams/workflows. The `app = agent_os.get_app()` call **MUST** remain at module level (not inside `if __name__`). This is because uvicorn imports the `app` object by module path (e.g., `app="basic:app"`). Moving it inside the main gate will break the server.

## Style Guide Template

Every `.py` file must follow this exact structure:

```python
"""
<Feature Name>
=============================

Demonstrates <what this file teaches> using AgentOS.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Example Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    add_history_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    description="Example AgentOS app",
    agents=[agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="basic:app", reload=True)
```

### Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Setup (DB, config) → Create Agents/Teams/Workflows → Create AgentOS → Run
5. **`app` at module level** — `app = agent_os.get_app()` MUST be in the "Create AgentOS" section, NOT inside the main gate. Uvicorn imports it.
6. **Main gate** — Contains `agent_os.serve(app="module:app", ...)`. The `app=` string must match the filename (e.g., `app="basic:app"` for `basic.py`)
7. **No emoji** — No emoji characters anywhere
8. **Self-contained** — Each file must be independently runnable via `.venvs/demo/bin/python <path>`

## Execution Plan

Execute in this exact order. Each phase must complete before the next starts.

### Phase 1: Create New Directories and Redistribute Root Files

The main structural change is **slimming the root** from 14 files to 3, and creating new directories for redistributed files.

```bash
# Create new directories
mkdir -p cookbook/05_agent_os/schemas
mkdir -p cookbook/05_agent_os/integrations

# Move root files to their new homes
mv cookbook/05_agent_os/agent_with_input_schema.py cookbook/05_agent_os/schemas/
mv cookbook/05_agent_os/agent_with_output_schema.py cookbook/05_agent_os/schemas/
mv cookbook/05_agent_os/team_with_input_schema.py cookbook/05_agent_os/schemas/
mv cookbook/05_agent_os/team_with_output_schema.py cookbook/05_agent_os/schemas/
mv cookbook/05_agent_os/handle_custom_events.py cookbook/05_agent_os/customize/
mv cookbook/05_agent_os/pass_dependencies_to_agent.py cookbook/05_agent_os/customize/
mv cookbook/05_agent_os/update_from_lifespan.py cookbook/05_agent_os/customize/
mv cookbook/05_agent_os/all_interfaces.py cookbook/05_agent_os/interfaces/
mv cookbook/05_agent_os/evals_demo.py cookbook/05_agent_os/background_tasks/
mv cookbook/05_agent_os/guardrails_demo.py cookbook/05_agent_os/middleware/
mv cookbook/05_agent_os/shopify_demo.py cookbook/05_agent_os/integrations/
```

After Phase 1, only 3 files remain at root: `basic.py`, `demo.py`, `agno_agent.py`.

**Important:** Do the moves first, then work with the new paths for all subsequent phases.

### Phase 2: Execute File Dispositions (file by file)

Work through the RESTRUCTURE_PLAN.md Section 3 ("File Disposition Table") directory by directory.

**For each file, you MUST:**
1. Read the file completely
2. Understand its purpose, AgentOS config, agents, DB setup, and interface type
3. Apply the disposition (CUT, MERGE, REWRITE, KEEP+FIX, etc.)
4. Verify the result preserves the original behavior

#### CUT files (do first)
Delete files marked as **CUT**. The main cuts are in `tracing/dbs/` (11 near-identical files being reduced to 3 representative examples).

Files to CUT:
```
cookbook/05_agent_os/tracing/dbs/basic_agent_with_async_mysql.py
cookbook/05_agent_os/tracing/dbs/basic_agent_with_async_postgres.py
cookbook/05_agent_os/tracing/dbs/basic_agent_with_async_sqlite.py
cookbook/05_agent_os/tracing/dbs/basic_agent_with_dynamodb.py
cookbook/05_agent_os/tracing/dbs/basic_agent_with_firestore.py
cookbook/05_agent_os/tracing/dbs/basic_agent_with_gcs_json_db.py
cookbook/05_agent_os/tracing/dbs/basic_agent_with_jsondb.py
cookbook/05_agent_os/tracing/dbs/basic_agent_with_mysql.py
cookbook/05_agent_os/tracing/dbs/basic_agent_with_redis.py
cookbook/05_agent_os/tracing/dbs/basic_agent_with_singlestore.py
cookbook/05_agent_os/tracing/dbs/basic_agent_with_surrealdb.py
```

3 files survive in `tracing/dbs/`: `basic_agent_with_postgresdb.py`, `basic_agent_with_sqlite.py`, `basic_agent_with_mongodb.py`.

#### MERGE files
For files marked **MERGE INTO**:
1. Read ALL source files that will be merged
2. Identify the unique content in each (don't just look at the diff — understand the feature)
3. Combine into the target file, keeping all unique functionality
4. For sync/async variants: use labeled sections (`# --- Sync ---`, `# --- Async ---`) within the `if __name__` block
5. Delete the source files after merging

#### REWRITE files
For files marked **REWRITE**:
1. Read the existing file to understand its AgentOS configuration
2. Rebuild from scratch following the template
3. Keep the exact same AgentOS name, agent definitions, database setup, and instructions
4. Only change the structure/layout to match the style guide

#### KEEP + FIX files
For files marked **KEEP + FIX**:
1. Read the file
2. Add module docstring if missing
3. Move imports above first banner
4. Add section banners (`# ---------------------------------------------------------------------------`)
5. Ensure `app = agent_os.get_app()` is at module level (NOT inside `if __name__`)
6. Add `if __name__ == "__main__":` gate if missing (containing `agent_os.serve(...)`)
7. Remove emoji if present
8. Do NOT change the AgentOS logic, agent configurations, or database setup

#### KEEP + MOVE + FIX / KEEP + RENAME + FIX files
Move or rename the file as specified, then apply the same style fixes as KEEP + FIX.

**Renaming note:** In `dbs/`, many files are being renamed to drop the `_demo` suffix (e.g., `postgres_demo.py` → `postgres.py`, `dynamo_demo.py` → `dynamo.py`). When renaming, update the `app=` string in `agent_os.serve()` to match the new filename.

### Phase 3: Clean Up

After all file operations:

1. Verify that CUT files have been deleted
2. Verify that MERGE source files have been deleted after merging
3. Remove any empty directories that result from file moves

### Phase 4: Create README.md and TEST_LOG.md

For every surviving subdirectory under `cookbook/05_agent_os/`:

**README.md** — Short description of the directory's scope, list of files with one-line descriptions, and prerequisites (API keys, services needed). Many directories already have README.md — update them to reflect any file changes (renames, additions, removals).

**TEST_LOG.md** — Create with this placeholder template:
```markdown
# Test Log: <directory_name>

> Tests not yet run. Run each file and update this log.

### <filename>.py

**Status:** PENDING

**Description:** <what the file does>

---
```

### Phase 5: Validate

Run the structure checker on each subdirectory:
```bash
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/05_agent_os/<subdir>
```

Fix any violations. All files must pass.

## Key Merge Examples

### Example: Merging sync/async DB pair (dbs/postgres)

Before: 2 files
- `dbs/postgres_demo.py` — Uses `PostgresDb`
- `dbs/async_postgres_demo.py` — Uses `AsyncPostgresDb`

After: 1 file (`dbs/postgres.py`):

```python
"""
PostgreSQL Database Backend
=============================

Demonstrates AgentOS with PostgreSQL storage using both sync and async patterns.
"""

import asyncio

from agno.agent import Agent
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

sync_db = PostgresDb(table_name="agent_sessions", db_url=db_url)
async_db = AsyncPostgresDb(table_name="agent_sessions", db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
sync_agent = Agent(
    name="Sync Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    db=sync_db,
    add_history_to_context=True,
    markdown=True,
)

async_agent = Agent(
    name="Async Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    db=async_db,
    add_history_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
# --- Sync ---
agent_os = AgentOS(
    description="Sync PostgreSQL AgentOS",
    agents=[sync_agent],
)
app = agent_os.get_app()

# --- Async ---
# Uncomment below and comment out the sync section to use async:
# agent_os = AgentOS(
#     description="Async PostgreSQL AgentOS",
#     agents=[async_agent],
# )
# app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="postgres:app", reload=True)
```

**Important:** When merging sync/async DB pairs, read BOTH files first. The async variant may use `AsyncPostgresDb` instead of `PostgresDb` — these are different classes from different modules. Don't assume the only difference is the class name.

### Example: Merging schema files (schemas/agent_schemas.py)

Before: 2 root files
- `agent_with_input_schema.py` — Agent with input schema
- `agent_with_output_schema.py` — Agent with output schema

After: 1 file (`schemas/agent_schemas.py`) combining both input and output schema patterns, with separate agents demonstrating each, both added to the same AgentOS.

### Example: Consolidating tracing/dbs

Before: 14 nearly identical files, each with the same HackerNews agent setup, differing only in the DB import line.

After: 3 representative files covering different DB categories:
- `basic_agent_with_postgresdb.py` — Production relational DB
- `basic_agent_with_sqlite.py` — Local development DB
- `basic_agent_with_mongodb.py` — Document DB

Each gets style fixes. The README.md documents all 14 supported DB backends and notes that the pattern is the same — just swap the import.

## Important Notes

1. **Read before writing** — This is the most important rule. Do not apply changes to files you haven't read. Every file has unique AgentOS configuration that must be understood and preserved.
2. **`app` at module level** — The `app = agent_os.get_app()` call MUST stay at module level. Uvicorn imports it by path. Moving it into the main gate WILL break the server.
3. **Preserve AgentOS logic** — When merging or rewriting, keep the exact same AgentOS configuration (agents, teams, workflows, description, middleware, interfaces). Don't invent new behavior.
4. **Use existing imports** — Look at the source files to understand which Agno modules to import. Don't guess API signatures.
5. **Default model** — For new files, use `OpenAIResponses(id="gpt-5.2")` from `agno.models.openai`. Do NOT change model names in existing files.
6. **No `__init__.py` files** — Cookbook directories don't use `__init__.py`.
7. **75 dashes** — The banner separator is exactly `# ---------------------------------------------------------------------------` (75 dashes after `# `).
8. **Read the plan carefully** — The RESTRUCTURE_PLAN.md has detailed rationale for every decision. When in doubt, follow the plan.
9. **`app=` string must match filename** — When renaming files, update the `app=` argument in `agent_os.serve()` to match the new filename. E.g., if `postgres_demo.py` becomes `postgres.py`, then `app="postgres_demo:app"` must become `app="postgres:app"`.
10. **Helper modules** — Some files (`advanced_demo/_agents.py`, `advanced_demo/_teams.py`, `dbs/surreal_db/agents.py`, etc.) are helper modules imported by other files. They don't need a main gate or `agent_os.serve()`, but DO need a docstring and section banners.
11. **Emoji removal** — 11+ files contain emoji. These are concentrated in `workflow/`, `middleware/`, `tracing/`, and `advanced_demo/`. Remove all emoji characters.
12. **Client/server files** — `client/`, `client_a2a/`, `mcp_demo/dynamic_headers/` contain client scripts that are NOT AgentOS servers. They use `AgentOSClient` or `httpx` to connect to servers. These still need style fixes but won't have `agent_os.serve()` — their main gate will have client logic instead.
13. **Database URLs** — Do NOT change database URLs, connection strings, or table names. These are configured for the local dev environment.
