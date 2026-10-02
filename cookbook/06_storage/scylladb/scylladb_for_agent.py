"""Use ScyllaDB as the database for an agent.

ScyllaDB exposes a DynamoDB-compatible API (Alternator), so Agno's DynamoDb class
works with it unchanged. You just point a boto3 DynamoDB client at the Alternator
endpoint and pass it to DynamoDb via db_client.

Start ScyllaDB with Alternator enabled:

    docker run -d --name scylla \
        -p 9042:9042 -p 8000:8000 \
        scylladb/scylla:latest \
        --alternator-port 8000 \
        --alternator-write-isolation=only_rmw_uses_lwt \
        --smp 1

You must use a safe write-isolation mode. Agno's DynamoDb relies on conditional writes and
atomic ADD counter updates; under a permissive mode (unsafe_rmw) concurrent read-modify-write
operations are silently lost with no error. Use --alternator-write-isolation=only_rmw_uses_lwt (as above)
or only_rmw_uses_lwt (the recommended production default).

Run `uv pip install boto3` to install dependencies."""

import boto3

from agno.agent import Agent
from agno.db.dynamo import DynamoDb

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# boto3 client pointed at ScyllaDB Alternator instead of AWS DynamoDB.
# Alternator ignores credentials by default, but boto3 requires some values.
client = boto3.client(
    "dynamodb",
    endpoint_url="http://localhost:8000",
    region_name="us-east-1",
    aws_access_key_id="alternator",
    aws_secret_access_key="alternator",
)

db = DynamoDb(db_client=client)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    db=db,
    name="ScyllaDB Agent",
    description="An agent that uses ScyllaDB (Alternator) as a database",
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # The Agent sessions and runs will now be stored in ScyllaDB
    agent.print_response("How many people live in Canada?")
    agent.print_response("What is their national anthem called?")
