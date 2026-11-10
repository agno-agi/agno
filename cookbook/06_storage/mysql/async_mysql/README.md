# Async MySQL Integration

Examples demonstrating asynchronous MySQL integration with Agno agents, teams, and workflows.

## Setup

```shell
uv pip install sqlalchemy asyncmy
```

## Configuration

```python
from agno.db.mysql import AsyncMySQLDb

db = AsyncMySQLDb(db_url="mysql+asyncmy://username:password@localhost:3306/database")
```

## Examples

- [`async_mysql_for_agent.py`](async_mysql_for_agent.py) - Agent with AsyncMySQLDb storage
- [`async_mysql_for_team.py`](async_mysql_for_team.py) - Team with AsyncMySQLDb storage
- [`async_mysql_for_workflow.py`](async_mysql_for_workflow.py) - Workflow with AsyncMySQLDb storage
