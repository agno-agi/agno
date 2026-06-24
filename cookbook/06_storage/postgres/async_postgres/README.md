# Async Postgres Integration

Examples demonstrating asynchronous PostgreSQL integration with Agno agents, teams, and workflows.

## Setup

```shell
uv pip install sqlalchemy psycopg
```

## Configuration

```python
from agno.db.postgres import AsyncPostgresDb

db = AsyncPostgresDb(db_url="postgresql+psycopg_async://username:password@localhost:5432/database")
```

## Examples

- [`async_postgres_for_agent.py`](async_postgres_for_agent.py) - Agent with AsyncPostgresDb storage
- [`async_postgres_for_team.py`](async_postgres_for_team.py) - Team with AsyncPostgresDb storage
- [`async_postgres_for_workflow.py`](async_postgres_for_workflow.py) - Workflow with AsyncPostgresDb storage
