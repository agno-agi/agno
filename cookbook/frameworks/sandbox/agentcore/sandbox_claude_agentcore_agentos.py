"""A sandboxed Claude agent on AgentCore behind AgentOS with a durable queue. This creates billable compute.

The same agent as sandbox_claude_agentcore.py, served over HTTP like sandbox_claude_agentos.py.
Deploy a runtime with agentcore_setup.py, set AGENTCORE_RUNTIME_ARN to the ARN it printed, set
AWS_PROFILE and AWS_REGION, and run Postgres and Redis:

    ./cookbook/scripts/run_pgvector.sh
    docker run -d --name agno-redis -p 6379:6379 redis
    .venv/bin/python cookbook/frameworks/sandbox/agentcore/sandbox_claude_agentcore_agentos.py

Then send a turn and poll it:

    curl -X POST localhost:7777/agents/coder/runs \\
        -F session_id=demo -F background=true -F message="Write hello.py and run it"
    curl localhost:7777/agents/coder/runs/<run_id>?session_id=demo

AgentOS, the queue and the database stay on this host; each turn runs Claude Code in an AgentCore
microVM, which reaches Bedrock through the runtime's execution role. With a queue, any replica may
run the next attempt, so every replica must read the same checkpoints: set
AGNO_SANDBOX_CHECKPOINT_BUCKET to keep them in S3 (needs agno[s3]). Unset, they stay in a directory
on this host, which only a single replica can use.
"""

import os
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.postgres import PostgresDb
from agno.job_queue.config import QueueConfig, RedisCoordination
from agno.os import AgentOS
from agno.sandbox.agentcore import AgentCoreSandbox
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.s3 import S3CheckpointStore

runtime_arn = os.environ["AGENTCORE_RUNTIME_ARN"]

# Every replica must restore every other replica's checkpoints. With AGNO_SANDBOX_CHECKPOINT_BUCKET
# set they live in that S3 bucket, which any number of replicas share. Without it they stay in a
# directory on this host, which is only safe while this one process is the deployment's only replica.
bucket = os.getenv("AGNO_SANDBOX_CHECKPOINT_BUCKET")
checkpoints = (
    S3CheckpointStore(bucket, prefix="sandbox/checkpoints")
    if bucket
    else FileCheckpointStore(Path.home() / ".agno" / "sandbox" / "checkpoints")
)

db = PostgresDb(
    db_url=os.getenv(
        "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
    )
)
agent = ClaudeAgent(
    id="coder",
    model=os.getenv("AGNO_SANDBOX_MODEL", "us.anthropic.claude-sonnet-5"),
    permission_mode="bypassPermissions",
    sandbox=AgentCoreSandbox(
        runtime_arn,
        env={"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": runtime_arn.split(":")[3]},
        checkpoints=checkpoints,
    ),
)
agent_os = AgentOS(
    id="sandbox-claude-agentcore",
    agents=[agent],
    db=db,
    queue=QueueConfig(
        durable=True,
        db=db,
        redis=RedisCoordination(
            url=os.getenv("AGNO_SANDBOX_REDIS_URL", "redis://localhost:6379/0")
        ),
    ),
    telemetry=False,
)

if __name__ == "__main__":
    agent_os.serve(
        app=agent_os.get_app(),
        port=int(os.getenv("AGNO_SANDBOX_PORT", "7777")),
        reload=False,
    )
