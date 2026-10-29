"""Claude and Codex native permission requests in the AgentOS Approvals UI."""

import os
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent
from agno.db.postgres import PostgresDb
from agno.job_queue.config import QueueConfig, RedisCoordination
from agno.os import AgentOS
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.docker import DockerSandbox

# ---------------------------------------------------------------------------
# Configure storage and optional sandbox execution
# ---------------------------------------------------------------------------
db = PostgresDb(db_url=os.environ["DATABASE_URL"])
image = os.getenv("AGNO_SANDBOX_IMAGE")
sandbox = (
    DockerSandbox(
        image=image,
        network="isolated",
        checkpoints=FileCheckpointStore(Path("tmp/native-approval-checkpoints")),
    )
    if image
    else None
)

# ---------------------------------------------------------------------------
# Create the agents
# ---------------------------------------------------------------------------
claude = ClaudeAgent(
    id="claude-approvals",
    name="Claude Approvals",
    model="claude-sonnet-4-6",
    db=db,
    sandbox=sandbox,
    permission_mode="default",
    approval_timeout=900,
)
codex = CodexAgent(
    id="codex-approvals",
    name="Codex Approvals",
    model="gpt-5.6-luna",
    db=db,
    sandbox=sandbox,
    sandbox_mode="read-only",
    approval_policy="on-request",
    approval_timeout=900,
)

queue = (
    QueueConfig(
        durable=True,
        db=db,
        redis=RedisCoordination(url=os.environ["REDIS_URL"]),
        max_attempts=2,
    )
    if sandbox
    else None
)
agent_os = AgentOS(id="native-approvals", agents=[claude, codex], db=db, queue=queue)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the server and connect the AgentOS UI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=7777)
