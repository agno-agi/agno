# Restructuring Plan: `cookbook/06_storage/`

## 1. Executive Summary

### Current State

| Metric | Value |
|--------|-------|
| Directories | 18 (including 4 async subdirectories) |
| Total `.py` files (non-`__init__`) | 45 |
| Fully style-compliant | 0 (~0%) |
| Have module docstring | ~36 (~80%) |
| Have section banners | 0 (0%) |
| Have `if __name__` gate | ~12 (~27%) |
| Contain emoji | 0 (0%) |
| Subdirectories with README.md | 14 / 18 |
| Subdirectories with TEST_LOG.md | 0 / 18 |

### Key Problems

1. **Zero section banner compliance.** No file uses the `# ---------------------------------------------------------------------------` format.

2. **Async subdirectory sprawl.** Four backends (postgres, sqlite, mongo, mysql) have separate `async_*` subdirectories that duplicate their sync counterparts with minimal differences (DB class import and `asyncio.run()` wrapper).

3. **No main gate on most files.** Only 12/45 files (27%) have `if __name__ == "__main__":`. Workflow files consistently have it; agent and team files almost never do.

4. **Highly templated content across backends.** Team files across all backends use the identical HackerNews Team example (same agents, same `Article` schema, same prompt) — only the DB import differs. Same for workflow files (Content Creation Workflow). This is by design (showing each backend works the same way) but worth noting.

5. **No TEST_LOG.md anywhere.** Zero directories have test logs.

6. **Missing docstrings on root files.** The 3 root concept files (`01_persistent_session_storage.py`, `02_session_summary.py`, `03_chat_history.py`) and `examples/multi_user_multi_session.py` lack docstrings.

### Overall Assessment

Storage has a clean, well-organized structure. Each database backend gets its own directory with agent/team/workflow examples. The main structural issue is the 4 async subdirectories that should be flattened into their parents. Otherwise, this is primarily a style compliance task.

### Proposed Target

| Metric | Current | Target |
|--------|---------|--------|
| Files | 45 | ~35 |
| Style compliance | 0% | 100% |
| README coverage | 14/18 | All surviving directories |
| TEST_LOG coverage | 0/18 | All surviving directories |

---

## 2. Proposed Directory Structure

Flatten all async subdirectories into their parent directories.

```
cookbook/06_storage/
├── 01_persistent_session_storage.py   # Persistent sessions with PostgresDb
├── 02_session_summary.py              # Session summary manager
├── 03_chat_history.py                 # Chat history retrieval
├── dynamodb/                          # DynamoDB backend (2 files)
├── examples/                          # Advanced patterns (multi-user, table selection)
├── firestore/                         # Firestore backend (1 file)
├── gcs/                               # GCS JSON backend (1 file)
├── in_memory/                         # In-memory backend (3 files)
├── json_db/                           # JSON file backend (3 files)
├── mongo/                             # MongoDB backend (3 files, merged from 5)
├── mysql/                             # MySQL backend (3 files, merged from 5)
├── postgres/                          # PostgreSQL backend (3 files, merged from 6)
├── redis/                             # Redis backend (3 files)
├── singlestore/                       # SingleStore backend (2 files)
├── sqlite/                            # SQLite backend (3 files, merged from 6)
└── surrealdb/                         # SurrealDB backend (3 files)
```

### Changes from Current

| Change | Details |
|--------|---------|
| **FLATTEN** `postgres/async_postgres/` | Merge 3 async files into 3 sync files. Remove subdirectory |
| **FLATTEN** `sqlite/async_sqlite/` | Merge 3 async files into 3 sync files. Remove subdirectory |
| **FLATTEN** `mongo/async_mongo/` | Merge 3 async files into 2 sync files + 1 new workflow file. Remove subdirectory |
| **FLATTEN** `mysql/async_mysql/` | Merge 3 async files into 2 sync files + 1 new workflow file. Remove subdirectory |

---

## 3. File Disposition Table

### Root Level (3 files, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `01_persistent_session_storage.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `02_session_summary.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `03_chat_history.py` | **KEEP + FIX** | Add docstring, banners, main gate |

---

### `dynamodb/` (2 → 2, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `dynamo_for_agent.py` | **KEEP + FIX** | Add banners, main gate |
| `dynamo_for_team.py` | **KEEP + FIX** | Add banners, main gate |

---

### `examples/` (2 → 2, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `multi_user_multi_session.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `selecting_tables.py` | **KEEP + FIX** | Add banners, main gate |

---

### `firestore/` (1 → 1, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `firestore_for_agent.py` | **KEEP + FIX** | Add banners, main gate |

---

### `gcs/` (1 → 1, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `gcs_json_for_agent.py` | **KEEP + FIX** | Add banners, main gate. Preserve 2-agent continuation pattern |

---

### `in_memory/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `in_memory_storage_for_agent.py` | **KEEP + FIX** | Add banners, main gate |
| `in_memory_storage_for_team.py` | **KEEP + FIX** | Add banners, main gate |
| `in_memory_storage_for_workflow.py` | **KEEP + FIX** | Add banners. Already has main gate |

---

### `json_db/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `json_for_agent.py` | **KEEP + FIX** | Add banners, main gate |
| `json_for_team.py` | **KEEP + FIX** | Add banners, main gate |
| `json_for_workflows.py` | **KEEP + FIX** | Add banners. Already has main gate |

---

### `mongo/` (5 → 3, flatten async)

| File | Disposition | New Name | Rationale |
|------|------------|----------|-----------|
| `mongodb_for_agent.py` | **REWRITE** | `mongodb_for_agent.py` | Merge with async variant. Show both sync `MongoDb` and async `AsyncMongoDb` patterns |
| `mongodb_for_team.py` | **REWRITE** | `mongodb_for_team.py` | Merge with async variant |
| `async_mongo/async_mongodb_for_agent.py` | **MERGE INTO** `mongodb_for_agent.py` | — | Async variant — same concept |
| `async_mongo/async_mongodb_for_team.py` | **MERGE INTO** `mongodb_for_team.py` | — | Async variant — same concept |
| `async_mongo/async_mongodb_for_workflow.py` | **KEEP + MOVE + FIX** | `mongodb_for_workflow.py` | No sync counterpart exists. Move to parent, rename, add banners |

---

### `mysql/` (5 → 3, flatten async)

| File | Disposition | New Name | Rationale |
|------|------------|----------|-----------|
| `mysql_for_agent.py` | **REWRITE** | `mysql_for_agent.py` | Merge with async variant. Note: async has richer content (uuid, SessionType, `async def main()`) — use async as the richer base |
| `mysql_for_team.py` | **REWRITE** | `mysql_for_team.py` | Merge with async variant |
| `async_mysql/async_mysql_for_agent.py` | **MERGE INTO** `mysql_for_agent.py` | — | Has richer async pattern with session inspection |
| `async_mysql/async_mysql_for_team.py` | **MERGE INTO** `mysql_for_team.py` | — | Async variant |
| `async_mysql/async_mysql_for_workflow.py` | **KEEP + MOVE + FIX** | `mysql_for_workflow.py` | No sync counterpart. Unique content (function-based workflow with `WorkflowExecutionInput`, `ResearchTopic` schema). Move to parent, rename, add banners |

**Note:** The mysql async workflow (`async_mysql_for_workflow.py`) uses a completely different workflow pattern from all other backends — it has a function-based workflow with `WorkflowExecutionInput`, `ResearchTopic` schema, and `blog_workflow` function. This is unique content that must be preserved carefully.

---

### `postgres/` (6 → 3, flatten async)

| File | Disposition | New Name | Rationale |
|------|------------|----------|-----------|
| `postgres_for_agent.py` | **REWRITE** | `postgres_for_agent.py` | Merge with async variant. Show both `PostgresDb` and `AsyncPostgresDb` |
| `postgres_for_team.py` | **REWRITE** | `postgres_for_team.py` | Merge with async variant |
| `postgres_for_workflow.py` | **REWRITE** | `postgres_for_workflow.py` | Merge with async variant |
| `async_postgres/async_postgres_for_agent.py` | **MERGE INTO** `postgres_for_agent.py` | — | Async variant. Note: uses different db_url scheme (`psycopg_async` vs `psycopg`) |
| `async_postgres/async_postgres_for_team.py` | **MERGE INTO** `postgres_for_team.py` | — | Async variant |
| `async_postgres/async_postgres_for_workflow.py` | **MERGE INTO** `postgres_for_workflow.py` | — | Async variant |

**Note:** PostgreSQL async uses a different connection URL scheme: `postgresql+psycopg_async://` vs `postgresql+psycopg://`. Both URLs must be preserved in the merged file.

---

### `redis/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `redis_for_agent.py` | **KEEP + FIX** | Add banners, main gate. Preserve `db.get_sessions()` verification |
| `redis_for_team.py` | **KEEP + FIX** | Add banners, main gate |
| `redis_for_workflow.py` | **KEEP + FIX** | Add banners. Already has main gate |

---

### `singlestore/` (2 → 2, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `singlestore_for_agent.py` | **KEEP + FIX** | Add banners, main gate |
| `singlestore_for_team.py` | **KEEP + FIX** | Add banners, main gate |

---

### `sqlite/` (6 → 3, flatten async)

| File | Disposition | New Name | Rationale |
|------|------------|----------|-----------|
| `sqlite_for_agent.py` | **REWRITE** | `sqlite_for_agent.py` | Merge with async variant. Show both `SqliteDb` and `AsyncSqliteDb` |
| `sqlite_for_team.py` | **REWRITE** | `sqlite_for_team.py` | Merge with async variant |
| `sqlite_for_workflow.py` | **REWRITE** | `sqlite_for_workflow.py` | Merge with async variant |
| `async_sqlite/async_sqlite_for_agent.py` | **MERGE INTO** `sqlite_for_agent.py` | — | Async variant |
| `async_sqlite/async_sqlite_for_team.py` | **MERGE INTO** `sqlite_for_team.py` | — | Async variant |
| `async_sqlite/async_sqlite_for_workflow.py` | **MERGE INTO** `sqlite_for_workflow.py` | — | Async variant |

---

### `surrealdb/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `surrealdb_for_agent.py` | **KEEP + FIX** | Add banners, main gate. Preserve `Claude` model (not OpenAI) |
| `surrealdb_for_team.py` | **KEEP + FIX** | Add banners, main gate. Preserve `Claude` model |
| `surrealdb_for_workflow.py` | **KEEP + FIX** | Add banners. Already has main gate. Preserve `Claude` model |

---

## 4. New Files Needed

No new files needed. The storage section has good coverage across 12 database backends with agent, team, and workflow examples.

---

## 5. Missing READMEs and TEST_LOGs

| Directory | README.md | TEST_LOG.md |
|-----------|-----------|-------------|
| `06_storage/` (root) | EXISTS | **MISSING** |
| `dynamodb/` | EXISTS | **MISSING** |
| `examples/` | EXISTS | **MISSING** |
| `firestore/` | EXISTS | **MISSING** |
| `gcs/` | EXISTS | **MISSING** |
| `in_memory/` | EXISTS | **MISSING** |
| `json_db/` | EXISTS | **MISSING** |
| `mongo/` | EXISTS (update after flatten) | **MISSING** |
| `mysql/` | EXISTS (update after flatten) | **MISSING** |
| `postgres/` | EXISTS (update after flatten) | **MISSING** |
| `redis/` | EXISTS | **MISSING** |
| `singlestore/` | EXISTS | **MISSING** |
| `sqlite/` | EXISTS (update after flatten) | **MISSING** |
| `surrealdb/` | EXISTS | **MISSING** |

**Summary:** All 14 main directories have README.md (update 4 after flattening). None have TEST_LOG.md. After restructuring, the 4 async subdirectories are removed, so they no longer need documentation.

---

## 6. Recommended Cookbook Template

Storage files are standalone scripts that configure a database backend, create an agent/team/workflow, and run it.

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

### Template Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Setup (DB connection) → Create Agent/Team/Workflow → Run
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere
7. **Sync + async together** — When merging sync/async variants, show both patterns in the same file using labeled sections within the `if __name__` block
8. **Self-contained** — Each file must be independently runnable

### Merge Pattern for Sync/Async Pairs

When merging sync and async variants, use this pattern in the `if __name__` block:

```python
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("How many people live in Canada?")
    agent.print_response("What is their national anthem called?")

    # --- Async ---
    import asyncio
    asyncio.run(agent.aprint_response("How many people live in Canada?"))
    asyncio.run(agent.aprint_response("What is their national anthem called?"))
```

When the sync and async variants use **different DB classes** (e.g., `PostgresDb` vs `AsyncPostgresDb`), create separate agents for each:

```python
# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
sync_db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
async_db = AsyncPostgresDb(db_url="postgresql+psycopg_async://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
sync_agent = Agent(db=sync_db, ...)
async_agent = Agent(db=async_db, ...)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    sync_agent.print_response("How many people live in Canada?")

    # --- Async ---
    import asyncio
    asyncio.run(async_agent.aprint_response("How many people live in Canada?"))
```

### Best Current Examples (reference)

1. **`redis/redis_for_agent.py`** — Has good docstring with Docker setup, includes session verification. Needs: banners, main gate.
2. **`mongo/mongodb_for_agent.py`** — Good docstring with Docker command and script reference. Needs: banners, main gate.
3. **`sqlite/sqlite_for_workflow.py`** — Has main gate, good structure. Needs: banners.
