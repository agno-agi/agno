# Async Oracle Integration

Examples demonstrating asynchronous Oracle Database integration with Agno
agents, teams, and workflows.

## Setup

```shell
uv pip install "agno[oracle]"
```

## Configuration

```python
from agno.db.oracle import AsyncOracleDb

db = AsyncOracleDb(db_url="oracle+oracledb_async://username:password@localhost:1521/?service_name=FREEPDB1")
```

`AsyncOracleDb` requires the `oracle+oracledb_async://` URL prefix specifically:
python-oracledb's asyncio support works only in thin mode, and this prefix is
what selects it — passing a plain `oracle+oracledb://` URL (or an engine built
from one) raises immediately, naming what was expected, rather than failing
confusingly on first `await`.

See the parent [`README`](../README.md) for the full version matrix, the
19c-by-behavioural-equivalence gap, schema-as-user semantics, and the owner
sentinel a reader outside agno sees.

## What's covered

`AsyncOracleDb` reaches parity with the synchronous adapter for every domain
these examples exercise — schema versions, sessions, runs, memory, metrics,
knowledge content, learnings, schedules, tool results, approvals, auth
tokens, and service accounts. Components and MCP OAuth are not implemented at
all on the async side (matching `AsyncPostgresDb`, which does not implement
them either); the durable job queue is still available asynchronously, served
generically by wrapping the synchronous `OracleDb` with a thread-offloading
adapter rather than a second native implementation.

## Examples

- [`async_oracle_for_agent.py`](async_oracle_for_agent.py) - Agent with AsyncOracleDb storage
- [`async_oracle_for_team.py`](async_oracle_for_team.py) - Team with AsyncOracleDb storage
- [`async_oracle_for_workflow.py`](async_oracle_for_workflow.py) - Workflow with AsyncOracleDb storage
