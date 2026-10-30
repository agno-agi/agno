"""A sandboxed Claude agent behind AgentOS with a durable queue: the same agent as
sandbox_claude.py, served over HTTP.

Build the runtime image, run Postgres, and export ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN:

    .venv/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:local
    ./cookbook/scripts/run_pgvector.sh
    .venv/bin/python cookbook/frameworks/sandbox/docker/sandbox_claude_agentos.py

Then send a turn and poll it:

    curl -X POST localhost:7777/agents/coder/runs \\
        -F session_id=demo -F background=true -F message="Write hello.py and run it"
    curl localhost:7777/agents/coder/runs/<run_id>?session_id=demo

Every API request submits to the queue, so a dropped connection does not cancel the turn, and a
second request on the same session waits for the first. With a queue, any replica may run the next
attempt, so checkpoints must live where every replica can read them: set
AGNO_SANDBOX_CHECKPOINT_BUCKET to keep them in S3 (needs agno[s3] and AWS credentials). Unset, they
stay in a directory on this host, which only a single replica can use.

Redis is optional. Postgres alone handles cancellation, crash recovery and results on any number of
replicas. Set AGNO_SANDBOX_REDIS_URL to add live streams and resume from any replica; without it, a
replica streams only the turns its own worker runs, and a client that lands elsewhere polls the run.
"""

import os
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.postgres import PostgresDb
from agno.job_queue.config import QueueConfig, RedisCoordination
from agno.os import AgentOS
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.docker import DockerSandbox
from agno.sandbox.s3 import S3CheckpointStore

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
    model="claude-sonnet-4-6",
    permission_mode="bypassPermissions",
    sandbox=DockerSandbox(
        os.getenv("AGNO_SANDBOX_IMAGE", "agno-sandbox:local"),
        network="isolated",
        # A host whose networks overlap the default range sets AGNO_SANDBOX_SUBNET to a free one.
        subnet=os.environ.get("AGNO_SANDBOX_SUBNET", "172.30.0.0/22"),
        memory_mb=1024,
        checkpoints=checkpoints,
    ),
)
agent_os = AgentOS(
    id="sandbox-claude",
    agents=[agent],
    db=db,
    queue=QueueConfig(
        durable=True,
        db=db,
        redis=RedisCoordination(url=os.environ["AGNO_SANDBOX_REDIS_URL"])
        if os.getenv("AGNO_SANDBOX_REDIS_URL")
        else None,
    ),
    telemetry=False,
)

if __name__ == "__main__":
    agent_os.serve(
        app=agent_os.get_app(),
        port=int(os.getenv("AGNO_SANDBOX_PORT", "7777")),
        reload=False,
    )
