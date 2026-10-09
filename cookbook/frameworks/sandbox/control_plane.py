"""Two identical control-plane replicas sharing a Docker execution network."""

import os

from agno.agents.sandbox import SandboxAgent
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig, RedisCoordination
from agno.os import AgentOS
from agno.sandbox.docker import DockerSandboxProvider
from agno.sandbox.workspace import GitWorkspace

# ---------------------------------------------------------------------------
# Create the control plane
# ---------------------------------------------------------------------------
db = PostgresDb(db_url=os.environ["AGNO_DB_URL"], id="sandbox-db")
coder = SandboxAgent(
    id="coder",
    name="Sandbox coder",
    provider=DockerSandboxProvider(network=os.environ["AGNO_SANDBOX_NETWORK"]),
    image=os.environ["AGNO_SANDBOX_IMAGE"],
    db=db,
    idle_timeout=int(os.getenv("AGNO_SANDBOX_IDLE_TIMEOUT", "15")),
    harness_config={
        "model": "haiku",
        "max_budget_usd": 2.0,
        "max_turns": 8,
        "allowed_tools": ["Read", "Write", "Bash"],
        "permission_mode": "acceptEdits",
    },
    sweep_interval=1,
    workspace=GitWorkspace(repo="git://git/workspace.git"),
    runtime_command=["python", "/example/test_runtime.py"]
    if os.getenv("AGNO_SANDBOX_TEST_HARNESS") == "1"
    else None,
    runtime_env={
        key: os.environ[key]
        for key in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
        if key in os.environ
    },
)
agent_os = AgentOS(
    agents=[coder],
    db=db,
    queue=QueueConfig(
        durable=True,
        redis=RedisCoordination(
            url=os.environ["AGNO_REDIS_URL"], key_prefix="sandbox-review"
        ),
        lock_grace_seconds=9,
        stop_timeout_seconds=1,
        poll_interval=0.2,
        max_attempts=int(os.getenv("AGNO_SANDBOX_MAX_ATTEMPTS", "2")),
        retry_delay_seconds=1,
    ),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the control plane
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=7777)
