# Async Oracle Integration

Examples demonstrating asynchronous Oracle Database integration with Agno agents, teams, and workflows.

## Setup

```shell
uv pip install sqlalchemy oracledb
```

## Configuration

```python
from agno.db.oracle import AsyncOracleDb

db = AsyncOracleDb(db_url="oracle+oracledb_async://user:password@localhost:1521/?service_name=FREEPDB1")
```

## Examples

- [`async_oracle_for_agent.py`](async_oracle_for_agent.py) - Agent with AsyncOracleDb storage
- [`async_oracle_for_team.py`](async_oracle_for_team.py) - Team with AsyncOracleDb storage
- [`async_oracle_for_workflow.py`](async_oracle_for_workflow.py) - Workflow with AsyncOracleDb storage
