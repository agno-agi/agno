# ScyllaDB Integration

Examples demonstrating ScyllaDB integration with Agno agents, teams, and workflows.

ScyllaDB exposes a DynamoDB-compatible API called
[Alternator](https://docs.scylladb.com/stable/alternator/alternator.html). Because of this,
Agno's `DynamoDb` class works with ScyllaDB out of the box. You just point a `boto3` client at
the Alternator endpoint and pass it to `DynamoDb` via `db_client`. No Agno code changes are
required.

## Setup

```shell
uv pip install boto3
```

Run ScyllaDB with Alternator enabled:

```shell
docker run -d --name scylla \
  -p 9042:9042 -p 8000:8000 \
  scylladb/scylla:latest \
  --alternator-port 8000 \
  --alternator-write-isolation=only_rmw_uses_lwt \
  --smp 1
```

> **You must use a safe write-isolation mode.** Agno's `DynamoDb` relies on conditional
> writes and atomic `ADD` counter updates. Under a permissive mode (`unsafe_rmw`), concurrent
> read-modify-write operations are *silently lost* with no error. Use
> `--alternator-write-isolation=only_rmw_uses_lwt` (as above) or `only_rmw_uses_lwt` (the recommended
> production default).

## Configuration

```python
import boto3

from agno.agent import Agent
from agno.db.dynamo import DynamoDb

client = boto3.client(
    "dynamodb",
    endpoint_url="http://localhost:8000",
    region_name="us-east-1",
    aws_access_key_id="alternator",
    aws_secret_access_key="alternator",
)

db = DynamoDb(db_client=client)

agent = Agent(db=db)
```

## Examples

- [`scylladb_for_agent.py`](scylladb_for_agent.py) - Agent with ScyllaDB storage
- [`scylladb_for_team.py`](scylladb_for_team.py) - Team with ScyllaDB storage
- [`scylladb_for_workflow.py`](scylladb_for_workflow.py) - Workflow with ScyllaDB storage

> **Note:** This is the *storage / database* integration (via Alternator). ScyllaDB also has a
> *vector store* integration for Knowledge Bases that reuses Agno's Cassandra driver — see
> [`cookbook/07_knowledge/05_integrations/vector_dbs/05_scylladb.py`](../../07_knowledge/05_integrations/vector_dbs/05_scylladb.py).
