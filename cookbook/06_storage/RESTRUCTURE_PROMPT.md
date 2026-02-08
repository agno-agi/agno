# Implement `cookbook/06_storage/` Restructuring

You are restructuring the `cookbook/06_storage/` directory of the Agno AI agent framework. The full plan is attached as `RESTRUCTURE_PLAN.md`. Read it completely before starting.

## Context

- **Agno** is a Python AI agent framework. The `cookbook/` directory contains runnable example scripts.
- Storage scripts configure a database backend, create an agent/team/workflow, and run it.
- The goal is to achieve 100% style compliance on all 45 files and add TEST_LOG.md to all 18 directories.
- **No file merges, cuts, or moves.** Async subdirectories are kept separate because they use genuinely different database classes (`AsyncPostgresDb`, `AsyncSqliteDb`, etc.) with different connection schemes.
- Every file must comply with the style guide (see Template section below).
- The virtual environment for running cookbooks is at `.venvs/demo/bin/python`.
- The style checker is at `cookbook/scripts/check_cookbook_pattern.py`.

## CRITICAL: Read Each File Before Modifying

**Do NOT apply blanket changes across files using batch scripts or regex-based rewrites.** Every file configures a specific database backend with unique connection parameters, agent configurations, and DB class imports. You must:

1. **Read each file individually** before making any changes to it.
2. **Understand what the file does** — its database backend, connection URL, agent/team/workflow setup, and any special patterns.
3. **Preserve the existing logic exactly** — only restructure the layout (add banners, docstring, main gate). Do not change database URLs, model names, agent configurations, or connection parameters.

This is a careful, file-by-file task. It will take time. Do not rush it.

## CRITICAL: Preserve Database-Specific Details

- **SurrealDB uses Claude model** (not OpenAI) — preserve `Claude(id="claude-sonnet-4-5-20250929")` exactly.
- **PostgreSQL async uses different URL scheme**: `postgresql+psycopg_async://` vs `postgresql+psycopg://`.
- **MySQL async workflow** (`async_mysql_for_workflow.py`) uses a unique function-based pattern with `WorkflowExecutionInput`, `ResearchTopic` schema, and `blog_workflow` function — NOT a typical workflow.
- **Docker setup commands** in docstrings must be preserved exactly.
- **Do NOT change database URLs, connection strings, or table names.**

## Style Guide Template

Every `.py` file must follow this exact structure:

```python
"""
<DB Name> Storage for <Entity>
=============================

Demonstrates using <DB Name> as the session storage backend for an Agno <Entity>.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    tools=[WebSearchTools()],
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("How many people live in Canada?")
    agent.print_response("What is their national anthem called?")
```

### Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates. Preserve existing Docker setup instructions in docstrings.
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Setup (DB connection) → Create Agent/Team/Workflow → Run
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere
7. **Self-contained** — Each file must be independently runnable

## Execution Plan

Execute in this exact order. Each phase must complete before the next starts.

### Phase 1: Style Fixes (all 45 files)

Work through the RESTRUCTURE_PLAN.md Section 3 ("File Disposition Table") directory by directory. Every file is **KEEP + FIX**.

**For each file, you MUST:**
1. Read the file completely
2. Understand its purpose, DB backend, connection setup, and agent/team/workflow configuration
3. Apply style fixes:
   - Add module docstring if missing (preserve existing Docker instructions)
   - Move imports above first banner
   - Add section banners (`# ---------------------------------------------------------------------------`)
   - Add `if __name__ == "__main__":` gate if missing
   - Do NOT change the DB logic, agent configuration, model names, or connection parameters

**Processing order:** Root files → dynamodb → examples → firestore → gcs → in_memory → json_db → mongo → mongo/async_mongo → mysql → mysql/async_mysql → postgres → postgres/async_postgres → redis → singlestore → sqlite → sqlite/async_sqlite → surrealdb

### Phase 2: Create README.md and TEST_LOG.md

For every directory under `cookbook/06_storage/`:

**README.md** — Most directories already have README.md. Add README.md to the 4 async subdirectories that are missing them (`async_mongo/`, `async_mysql/`, `async_postgres/`, `async_sqlite/`).

**TEST_LOG.md** — Create for ALL 18 directories with this placeholder template:
```markdown
# Test Log: <directory_name>

> Tests not yet run. Run each file and update this log.

### <filename>.py

**Status:** PENDING

**Description:** <what the file does>

---
```

### Phase 3: Validate

Run the structure checker on each subdirectory:
```bash
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/06_storage/<subdir>
```

Fix any violations. All files must pass.

## Important Notes

1. **Read before writing** — Do not apply changes to files you haven't read. Every file has unique DB configuration.
2. **Preserve DB logic** — Do not change database classes, connection URLs, table names, or credentials.
3. **Preserve model names** — SurrealDB files use `Claude`, not `OpenAIResponses`. Do NOT change model names.
4. **No merges** — Async subdirectories stay as separate directories with separate files.
5. **Templated content is by design** — Team files across all backends use the identical HackerNews Team example. This is intentional (showing each backend works the same way). Preserve it.
6. **No `__init__.py` files** — Cookbook directories don't use `__init__.py`.
7. **75 dashes** — The banner separator is exactly `# ---------------------------------------------------------------------------` (75 dashes after `# `).
8. **Read the plan carefully** — The RESTRUCTURE_PLAN.md has detailed rationale for every decision. When in doubt, follow the plan.
9. **Docker instructions** — Many files have Docker setup commands in their docstrings (e.g., `docker run --rm ...` for MongoDB, Redis, SurrealDB). These must be preserved exactly in the module docstring.
