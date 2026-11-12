"""A sandboxed Claude agent on E2B behind AgentOS with a durable queue. This creates billable compute.

The same agent as sandbox_claude_e2b.py, served over HTTP like ../docker/sandbox_claude_agentos.py.
Build the template with e2b_template.py, export E2B_API_KEY and ANTHROPIC_API_KEY or
CLAUDE_CODE_OAUTH_TOKEN, and run Postgres and Redis:

    ./cookbook/scripts/run_pgvector.sh
    docker run -d --name agno-redis -p 6379:6379 redis
    .venv/bin/python cookbook/frameworks/sandbox/e2b/sandbox_claude_e2b_agentos.py

Then send a turn and poll it:

    curl -X POST localhost:7777/agents/coder/runs \\
        -F session_id=demo -F background=true -F message="Write hello.py and run it"
    curl localhost:7777/agents/coder/runs/<run_id>?session_id=demo

AgentOS, the queue and the database stay on this host; each turn runs Claude Code in an E2B
computer, and start/poll reach the runtime server inside it over its E2B port. With a queue,
any replica may run the next attempt, so every replica must read the same checkpoint directory.
"""

import os
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.postgres import PostgresDb
from agno.job_queue.config import QueueConfig, RedisCoordination
from agno.os import AgentOS
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.e2b import E2BSandbox

db = PostgresDb(
    db_url=os.getenv(
        "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
    )
)
agent = ClaudeAgent(
    id="coder",
    model="claude-sonnet-4-6",
    permission_mode="bypassPermissions",
    sandbox=E2BSandbox(
        os.getenv("E2B_TEMPLATE", "agno-sandbox"),
        runtime_port=8765,
        checkpoints=FileCheckpointStore(
            Path.home() / ".agno" / "sandbox" / "checkpoints"
        ),
    ),
)
agent_os = AgentOS(
    id="sandbox-claude-e2b",
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
