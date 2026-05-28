# SQLite Integration

Examples demonstrating SQLite database integration with Agno agents, teams, and workflows.

## Configuration

```python
from agno.agent import Agent
from agno.db.sqlite import SqliteDb

db = SqliteDb(db_file="path/to/database.db")

agent = Agent(
    db=db,
    add_history_to_context=True,
)
```

## Async usage

Agno also supports using your SQLite database asynchronously, via the `AsyncSqliteDb` class:

```python
from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb

db = AsyncSqliteDb(db_file="path/to/database.db")

agent = Agent(
    db=db,
    add_history_to_context=True,
)
```

## Examples

- [`sqlite_for_agent.py`](sqlite_for_agent.py) - Agent with SQLite storage
- [`sqlite_for_team.py`](sqlite_for_team.py) - Team with SQLite storage
- [`sqlite_for_workflow.py`](sqlite_for_workflow.py) - Workflow with SQLite storage

