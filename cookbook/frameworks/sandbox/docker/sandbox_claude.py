"""The smallest sandboxed Claude agent: two turns, each on a fresh computer, no AgentOS.

Build the runtime image, run Postgres, and export ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN:

    .venv/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:local
    ./cookbook/scripts/run_pgvector.sh
    .venv/bin/python cookbook/frameworks/sandbox/docker/sandbox_claude.py

Each turn runs the whole Claude Code process in a container from DockerSandbox. When the turn
completes, its files and conversation are checkpointed to ~/.agno/sandbox/checkpoints and the
container is removed; the next turn starts a new container restored from that checkpoint. The
credential in this process's environment is forwarded into the container.
"""

import os
from uuid import uuid4

from agno.agents.claude import ClaudeAgent
from agno.db.postgres import PostgresDb
from agno.sandbox.docker import DockerSandbox

agent = ClaudeAgent(
    id="coder",
    model="claude-sonnet-4-6",
    permission_mode="bypassPermissions",
    db=PostgresDb(
        db_url=os.getenv(
            "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
        )
    ),
    sandbox=DockerSandbox(
        os.getenv("AGNO_SANDBOX_IMAGE", "agno-sandbox:local"),
        network="isolated",
        # A host whose networks overlap the default range sets AGNO_SANDBOX_SUBNET to a free one.
        subnet=os.environ.get("AGNO_SANDBOX_SUBNET", "172.30.0.0/22"),
        memory_mb=1024,
    ),
)

# A session that already has turns outside the sandbox cannot be moved into one, so start a new one.
session_id = "sandbox-claude-" + uuid4().hex[:8]

first = agent.run(
    "Write hello.py that prints hello, run it, and reply with just its output.",
    session_id=session_id,
)
print("Turn 1:", first.status.value, "-", first.content)

second = agent.run(
    "What file did you create in this session? Reply with the file name only.",
    session_id=session_id,
)
print("Turn 2:", second.status.value, "-", second.content)
