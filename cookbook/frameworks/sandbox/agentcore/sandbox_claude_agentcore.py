"""A sandboxed Claude agent on AgentCore: two turns, each on a fresh microVM. This creates billable compute.

Deploy a runtime with agentcore_setup.py, set AGENTCORE_RUNTIME_ARN to the ARN it printed,
set AWS_PROFILE and AWS_REGION, and run Postgres:

    ./cookbook/scripts/run_pgvector.sh
    .venv/bin/python cookbook/frameworks/sandbox/agentcore/sandbox_claude_agentcore.py

The same agent as sandbox_claude.py with AgentCoreSandbox in place of DockerSandbox. Each turn
runs Claude Code in an AgentCore microVM. When the turn completes, its files and conversation
are checkpointed to ~/.agno/sandbox/checkpoints and the microVM is stopped; the next turn
starts a new microVM restored from that checkpoint. Claude reaches Bedrock through the
runtime's execution role, so no API key is sent into the sandbox.
"""

import os
from uuid import uuid4

from agno.agents.claude import ClaudeAgent
from agno.db.postgres import PostgresDb
from agno.sandbox.agentcore import AgentCoreSandbox

runtime_arn = os.environ["AGENTCORE_RUNTIME_ARN"]

agent = ClaudeAgent(
    id="coder",
    model=os.getenv("AGNO_SANDBOX_MODEL", "us.anthropic.claude-sonnet-5"),
    permission_mode="bypassPermissions",
    db=PostgresDb(
        db_url=os.getenv(
            "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
        )
    ),
    sandbox=AgentCoreSandbox(
        runtime_arn,
        env={"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": runtime_arn.split(":")[3]},
    ),
)

# A session that already has turns outside the sandbox cannot be moved into one, so start a new one.
session_id = "sandbox-claude-agentcore-" + uuid4().hex[:8]

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
