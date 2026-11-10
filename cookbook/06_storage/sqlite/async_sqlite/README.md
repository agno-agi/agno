# Async SQLite Integration

Examples demonstrating asynchronous SQLite integration with Agno agents, teams, and workflows.

## Setup

```shell
uv pip install sqlalchemy aiosqlite
```

## Configuration

```python
from agno.db.sqlite import AsyncSqliteDb

db = AsyncSqliteDb(db_file="path/to/database.db")
```

## Examples

- [`async_sqlite_for_agent.py`](async_sqlite_for_agent.py) - Agent with AsyncSqliteDb storage
- [`async_sqlite_for_team.py`](async_sqlite_for_team.py) - Team with AsyncSqliteDb storage
- [`async_sqlite_for_workflow.py`](async_sqlite_for_workflow.py) - Workflow with AsyncSqliteDb storage
