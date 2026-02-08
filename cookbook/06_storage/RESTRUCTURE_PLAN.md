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

2. **No main gate on most files.** Only 12/45 files (27%) have `if __name__ == "__main__":`. Workflow files consistently have it; agent and team files almost never do.

3. **Highly templated content across backends.** Team files across all backends use the identical HackerNews Team example (same agents, same `Article` schema, same prompt) — only the DB import differs. Same for workflow files (Content Creation Workflow). This is by design (showing each backend works the same way) but worth noting.

4. **No TEST_LOG.md anywhere.** Zero directories have test logs.

5. **Missing docstrings on root files.** The 3 root concept files (`01_persistent_session_storage.py`, `02_session_summary.py`, `03_chat_history.py`) and `examples/multi_user_multi_session.py` lack docstrings.

### Overall Assessment

Storage has a clean, well-organized structure. Each database backend gets its own directory with agent/team/workflow examples. The async subdirectories use genuinely different database classes (`AsyncPostgresDb`, `AsyncSqliteDb`, etc.) with different connection schemes, so they are kept as separate directories. This is primarily a style compliance task.

### Proposed Target

| Metric | Current | Target |
|--------|---------|--------|
| Files | 45 | 45 (no change) |
| Style compliance | 0% | 100% |
| README coverage | 14/18 | All directories |
| TEST_LOG coverage | 0/18 | All directories |

**No file merges, cuts, or moves needed.**

---

## 2. Proposed Directory Structure

No structural changes needed. The directory is already well-organized. Async subdirectories are kept separate because they use different database classes.

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
├── mongo/                             # MongoDB backend (2 files)
│   └── async_mongo/                   # Async MongoDB (3 files)
├── mysql/                             # MySQL backend (2 files)
│   └── async_mysql/                   # Async MySQL (3 files)
├── postgres/                          # PostgreSQL backend (3 files)
│   └── async_postgres/                # Async PostgreSQL (3 files)
├── redis/                             # Redis backend (3 files)
├── singlestore/                       # SingleStore backend (2 files)
├── sqlite/                            # SQLite backend (3 files)
│   └── async_sqlite/                  # Async SQLite (3 files)
└── surrealdb/                         # SurrealDB backend (3 files)
```

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

### `mongo/` (2 → 2, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `mongodb_for_agent.py` | **KEEP + FIX** | Add banners, main gate |
| `mongodb_for_team.py` | **KEEP + FIX** | Add banners, main gate |

---

### `mongo/async_mongo/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `async_mongodb_for_agent.py` | **KEEP + FIX** | Add banners, main gate |
| `async_mongodb_for_team.py` | **KEEP + FIX** | Add banners, main gate |
| `async_mongodb_for_workflow.py` | **KEEP + FIX** | Add banners. Unique workflow content |

---

### `mysql/` (2 → 2, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `mysql_for_agent.py` | **KEEP + FIX** | Add banners, main gate |
| `mysql_for_team.py` | **KEEP + FIX** | Add banners, main gate |

---

### `mysql/async_mysql/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `async_mysql_for_agent.py` | **KEEP + FIX** | Add banners, main gate. Has richer async pattern with session inspection |
| `async_mysql_for_team.py` | **KEEP + FIX** | Add banners, main gate |
| `async_mysql_for_workflow.py` | **KEEP + FIX** | Add banners. Unique function-based workflow with `WorkflowExecutionInput`, `ResearchTopic` schema, `blog_workflow` function |

**Note:** The mysql async workflow (`async_mysql_for_workflow.py`) uses a completely different workflow pattern from all other backends. This is unique content that must be preserved carefully.

---

### `postgres/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `postgres_for_agent.py` | **KEEP + FIX** | Add banners, main gate |
| `postgres_for_team.py` | **KEEP + FIX** | Add banners, main gate |
| `postgres_for_workflow.py` | **KEEP + FIX** | Add banners. Already has main gate |

---

### `postgres/async_postgres/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `async_postgres_for_agent.py` | **KEEP + FIX** | Add banners, main gate. Uses `AsyncPostgresDb` with `psycopg_async` URL |
| `async_postgres_for_team.py` | **KEEP + FIX** | Add banners, main gate |
| `async_postgres_for_workflow.py` | **KEEP + FIX** | Add banners. Already has main gate |

**Note:** PostgreSQL async uses a different connection URL scheme: `postgresql+psycopg_async://` vs `postgresql+psycopg://`.

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

### `sqlite/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `sqlite_for_agent.py` | **KEEP + FIX** | Add banners, main gate |
| `sqlite_for_team.py` | **KEEP + FIX** | Add banners, main gate |
| `sqlite_for_workflow.py` | **KEEP + FIX** | Add banners. Already has main gate |

---

### `sqlite/async_sqlite/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `async_sqlite_for_agent.py` | **KEEP + FIX** | Add banners, main gate. Uses `AsyncSqliteDb` |
| `async_sqlite_for_team.py` | **KEEP + FIX** | Add banners, main gate |
| `async_sqlite_for_workflow.py` | **KEEP + FIX** | Add banners. Already has main gate |

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
| `mongo/` | EXISTS | **MISSING** |
| `mongo/async_mongo/` | **MISSING** | **MISSING** |
| `mysql/` | EXISTS | **MISSING** |
| `mysql/async_mysql/` | **MISSING** | **MISSING** |
| `postgres/` | EXISTS | **MISSING** |
| `postgres/async_postgres/` | **MISSING** | **MISSING** |
| `redis/` | EXISTS | **MISSING** |
| `singlestore/` | EXISTS | **MISSING** |
| `sqlite/` | EXISTS | **MISSING** |
| `sqlite/async_sqlite/` | **MISSING** | **MISSING** |
| `surrealdb/` | EXISTS | **MISSING** |

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
7. **Self-contained** — Each file must be independently runnable

### Best Current Examples (reference)

1. **`redis/redis_for_agent.py`** — Has good docstring with Docker setup, includes session verification. Needs: banners, main gate.
2. **`mongo/mongodb_for_agent.py`** — Good docstring with Docker command and script reference. Needs: banners, main gate.
3. **`sqlite/sqlite_for_workflow.py`** — Has main gate, good structure. Needs: banners.
