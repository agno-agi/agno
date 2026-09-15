# Oracle Database Integration

Examples demonstrating Oracle Database integration with Agno agents. Storage
supports Oracle 19c and later; schema-variant detection (JSON storage, boolean
representation) is automatic. A full version matrix, and where Oracle behaves
differently from PostgreSQL, are documented as the remaining storage examples
land.

## Setup

```shell
uv pip install "agno[oracle]"
```

One-command local Oracle:

```shell
./cookbook/scripts/run_oracle.sh
```

## Configuration

```python
from agno.agent import Agent
from agno.db.oracle import OracleDb

db = OracleDb(db_url="oracle+oracledb://username:password@localhost:1521/?service_name=FREEPDB1")

agent = Agent(
    db=db,
    add_history_to_context=True,
)
```

On Oracle a schema is a user: `db_schema` defaults to `None`, meaning tables
are created in the connecting user's own schema, and `create_schema` has no
effect (creating an Oracle user needs a privilege application code should not
hold) — pass an existing schema name explicitly if you need one other than
the connecting user's own.

## Examples

- [`oracle_for_agent.py`](oracle_for_agent.py) - Agent with Oracle storage
