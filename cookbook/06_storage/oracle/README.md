# Oracle Database Integration

Examples demonstrating Oracle Database integration with Agno agents, teams, and
workflows.

## Setup

```shell
uv pip install "agno[oracle]"
```

One-command local Oracle:

```shell
./cookbook/scripts/run_oracle.sh
```

### Older Python interpreters resolve to an older driver

`agno[oracle]` leaves the `oracledb` driver version unbounded on purpose: its
newest release requires a newer Python than agno's own floor, and pip's
package resolution already selects an older, still-compatible driver release
on an older interpreter without needing an environment marker. If you pin
`oracledb` yourself, check that the pinned version supports the Python you are
running it on.

## Version matrix

| Capability | Minimum Oracle release | Notes |
|---|---|---|
| Storage (`OracleDb`, `AsyncOracleDb`) | 19c | JSON is stored as a CLOB with an `IS JSON` check constraint below 21c, and as the native `JSON` type on 21c and later. Detected automatically; no configuration needed. |
| Native `BOOLEAN` column type | 23ai | Emulated as `NUMBER(1)` below 23ai. Detected automatically. |
| Vector search (`OracleVector`) | 23ai | The native `VECTOR` type and `VECTOR_DISTANCE()` function do not exist before 23ai. `OracleVector.create()` fails immediately, naming the server's actual version, rather than producing a confusing `ORA-00902` partway through. |

**19c support is declared by behavioural equivalence, not by execution.** No
freely available 19c container image exists, so the storage layer is tested
against 18c (the CLOB-JSON code path 19c also uses) and 21c and 23ai (the
native-JSON and native-vector code paths) instead. This is stated here
plainly rather than presented as tested: if you run agno against a genuine
19c server and hit a difference, please report it.

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

### A schema is a user on Oracle

On PostgreSQL, `schema` names a namespace inside one database, and
`create_schema=True` (the default) creates it automatically if missing. On
Oracle, a schema *is* a database user, and creating one needs `CREATE USER`,
a privilege application code should not hold. So here:

- `db_schema` defaults to `None`, meaning "the connecting user's own schema" —
  not a shared namespace named after the app, the way `"ai"` is on Postgres.
- `create_schema` is accepted for interface parity but has no effect. Passing
  `db_schema="some_other_user"` requires that user to already exist; ask a DBA
  to create it if it does not:

  ```sql
  CREATE USER some_other_user IDENTIFIED BY <password>;
  GRANT CREATE SESSION, CREATE TABLE, CREATE SEQUENCE TO some_other_user;
  ALTER USER some_other_user QUOTA UNLIMITED ON <tablespace>;
  ```

## Async usage

Agno also supports using your Oracle database asynchronously, via the
`AsyncOracleDb` class. It requires the `oracle+oracledb_async://` URL prefix:
python-oracledb's asyncio support works only in thin mode, and this prefix is
what selects it.

```python
from agno.agent import Agent
from agno.db.oracle import AsyncOracleDb

db = AsyncOracleDb(db_url="oracle+oracledb_async://username:password@localhost:1521/?service_name=FREEPDB1")

agent = Agent(
    db=db,
    add_history_to_context=True,
)
```

See [`async_oracle/`](async_oracle/) for runnable Agent, Team and Workflow
examples. `AsyncOracleDb` covers the same domains as the synchronous adapter
except components and MCP OAuth, which the async base class does not support
at all (matching `AsyncPostgresDb`); the durable job queue is still available
asynchronously, served generically through a thread-offloading adapter around
the synchronous `OracleDb`.

## Examples

- [`oracle_for_agent.py`](oracle_for_agent.py) - Agent with Oracle storage
- [`oracle_for_team.py`](oracle_for_team.py) - Team with Oracle storage
- [`oracle_for_workflow.py`](oracle_for_workflow.py) - Workflow with Oracle storage
- [`async_oracle/`](async_oracle/) - Asynchronous Agent, Team and Workflow storage

## Shared engine configuration

Use `create_oracle_engine` when storage and application SQL need the same pool:

```python
from agno.db.oracle import OracleDb
from agno.db.oracle.engine import create_oracle_engine
from agno.fs.db import DbFileSystem

engine = create_oracle_engine("oracle+oracledb://username:password@localhost:1521/?service_name=FREEPDB1")
db = OracleDb(id="app-db", db_engine=engine)
files = DbFileSystem(db=db, table_name="agent_files")
# OracleVector(db=db, table_name="knowledge", ...) can borrow this same pool too.
```

The factory supplies pre-ping and a 3,600-second recycle interval — Oracle
connections are frequently dropped by a firewall or load balancer's idle
timeout, and a dead connection otherwise surfaces as an opaque driver error.
Each call creates a separate pool, so create and reuse one engine.
`create_async_oracle_engine` accepts the same options and returns an
`AsyncEngine` for `AsyncOracleDb(db_engine=engine)`, but only accepts an
`oracle+oracledb_async://` URL — see the async section above.

- [`shared_engine.py`](shared_engine.py) - Configure and share a pool without connecting

## Vector search, keyword search, hybrid search, and metadata filters

`OracleVector` (Oracle 23ai and later) lives outside this directory in the
knowledge cookbooks — see
[`../../07_knowledge/05_integrations/vector_dbs/06_oracle.py`](../../07_knowledge/05_integrations/vector_dbs/06_oracle.py)
for runnable vector, hybrid, and similarity-threshold examples.

**Keyword and hybrid search need `optimize()` called explicitly first**, and
the knowledge layer never calls it for you:

```python
from agno.vectordb.oracle import OracleVector

vector_db = OracleVector(table_name="knowledge", db_url="oracle+oracledb://...")
vector_db.create()
vector_db.optimize()  # Creates the ANN vector index and the Oracle Text CONTEXT index
```

Vector search alone needs no index to return correct results — `VECTOR_DISTANCE`
does an exact nearest-neighbor scan without one — but keyword and hybrid
search fail immediately with an actionable error (naming `optimize()` as the
fix) rather than a raw Oracle Text driver error if it has not been called.

## The owner sentinel is visible outside agno

Storage tables carry an owner column (`user_id`) so a caller's rows and the
shared, unowned rows (`user_id IS NULL`) stay distinct. Oracle folds an empty
string to `NULL` on write — the same value already used for "shared" — so an
explicitly unowned value (`user_id=""`) is stored as the literal string
`"__agno_unowned__"` instead, translated back to `""` by every agno read path.

A reader outside agno — a BI tool, a DBA running `SELECT * FROM agno_sessions`
directly — sees `"__agno_unowned__"` in that column, not an empty string. This
is a deliberate, documented consequence of the mitigation, not a leak: without
it, an explicitly unowned row would be indistinguishable from Oracle's own
`NULL`-is-shared bucket, and would leak into every other caller's shared reads
with no error raised.
