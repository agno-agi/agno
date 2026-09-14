# Oracle Integration

Examples demonstrating Oracle Database integration with Agno agents, teams, and workflows.

## Setup

```shell
uv pip install oracledb sqlalchemy
```

Start a local Oracle Database Free instance (the script waits for the database to
initialize — the first start takes a few minutes — and creates the `ai`/`ai` user):

```shell
./cookbook/scripts/run_oracle.sh
```

## Configuration

### Synchronous Oracle

```python
from agno.agent import Agent
from agno.db.oracle import OracleDb

db = OracleDb(db_url="oracle+oracledb://user:password@localhost:1521/?service_name=FREEPDB1")

agent = Agent(
    db=db,
    add_history_to_context=True,
)
```

### Asynchronous Oracle

```python
import asyncio
from agno.agent import Agent
from agno.db.oracle import AsyncOracleDb

db = AsyncOracleDb(db_url="oracle+oracledb_async://user:password@localhost:1521/?service_name=FREEPDB1")

agent = Agent(
    db=db,
    add_history_to_context=True,
)

asyncio.run(agent.aprint_response("Hello!"))
```

## Synchronous Examples

- [`oracle_for_agent.py`](oracle_for_agent.py) - Agent with Oracle storage
- [`oracle_for_team.py`](oracle_for_team.py) - Team with Oracle storage

## Asynchronous Examples

- [`async_oracle/async_oracle_for_agent.py`](async_oracle/async_oracle_for_agent.py) - Agent with Async Oracle storage
- [`async_oracle/async_oracle_for_team.py`](async_oracle/async_oracle_for_team.py) - Team with Async Oracle storage
- [`async_oracle/async_oracle_for_workflow.py`](async_oracle/async_oracle_for_workflow.py) - Workflow with Async Oracle storage

## Database URL Format

- **Sync (python-oracledb thin mode)**: `oracle+oracledb://user:password@host:port/?service_name=SERVICE`
- **Async (python-oracledb asyncio)**: `oracle+oracledb_async://user:password@host:port/?service_name=SERVICE`

## Async vs Sync

Choose **AsyncOracleDb** when building high-concurrency or async-framework (FastAPI)
applications that need non-blocking database operations. Choose **OracleDb** for
traditional synchronous applications and simpler deployments.
