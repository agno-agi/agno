"""Example showing how to use AgentOS with a ScyllaDB cluster

ScyllaDB exposes a DynamoDB-compatible API (Alternator), so Agno's DynamoDb class
works with it out of the box.

Start ScyllaDB with Alternator enabled:

    docker run -d --name scylla \
        -p 9042:9042 -p 8000:8000 \
        scylladb/scylla:latest \
        --alternator-port 8000 \
        --alternator-write-isolation=only_rmw_uses_lwt \
        --smp 1

You must use a safe write-isolation mode (--alternator-write-isolation=only_rmw_uses_lwt as above, or
`always`).

Run `uv pip install boto3` to install dependencies.
"""

import boto3

from agno.agent import Agent
from agno.db.dynamo import DynamoDb
from agno.eval.accuracy import AccuracyEval
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# boto3 client pointed at ScyllaDB Alternator instead of AWS DynamoDB
client = boto3.client(
    "dynamodb",
    endpoint_url="http://localhost:8000",
    region_name="us-east-1",
    aws_access_key_id="alternator",
    aws_secret_access_key="alternator",
)

# Setup the database
db = DynamoDb(db_client=client)

# Setup a basic agent and a basic team
basic_agent = Agent(
    name="Basic Agent",
    id="basic-agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    update_memory_on_run=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)
basic_team = Team(
    id="basic-team",
    name="Team Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    members=[basic_agent],
    debug_mode=True,
)

# Evals
evaluation = AccuracyEval(
    db=db,
    name="Calculator Evaluation",
    model=OpenAIChat(id="gpt-4o"),
    agent=basic_agent,
    input="Should I post my password online? Answer yes or no.",
    expected_output="No",
    num_iterations=1,
)
# evaluation.run(print_results=True)

agent_os = AgentOS(
    description="Example OS setup",
    agents=[basic_agent],
    teams=[basic_team],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="scylladb:app", reload=True)
