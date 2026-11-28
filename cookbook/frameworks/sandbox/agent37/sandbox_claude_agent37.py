"""A sandboxed Claude agent on Agent 37: two turns, each in an Agent 37 instance. This creates billable compute.

Build the template with agent37_setup.py, set AGENT37_API_KEY and AGENT37_TEMPLATE to
the name it printed, export ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN, and run Postgres:

    ./cookbook/scripts/run_pgvector.sh
    .venv/bin/python cookbook/frameworks/sandbox/agent37/sandbox_claude_agent37.py

The same agent as sandbox_claude.py with Agent37Sandbox in place of DockerSandbox. Each turn
runs Claude Code in an Agent 37 instance. When the turn completes, its files and conversation
are checkpointed to ~/.agno/sandbox/checkpoints and the instance is put to sleep for the next
turn; a turn after the warm window starts a new instance restored from that checkpoint. The
credential in this process's environment is stored by Agent 37 with the instance.
"""

import os
from pathlib import Path
from uuid import uuid4

from agno.agents.claude import ClaudeAgent
from agno.db.postgres import PostgresDb
from agno.sandbox.agent37 import Agent37Sandbox
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.coordinator import SandboxCoordinator

checkpoints = FileCheckpointStore(Path.home() / ".agno" / "sandbox" / "checkpoints")
sandbox = Agent37Sandbox(os.environ["AGENT37_TEMPLATE"], checkpoints=checkpoints)

agent = ClaudeAgent(
    id="coder",
    model="claude-sonnet-4-6",
    permission_mode="bypassPermissions",
    db=PostgresDb(
        db_url=os.getenv(
            "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
        )
    ),
    sandbox=sandbox,
)

# A session that already has turns outside the sandbox cannot be moved into one, so start a new one.
session_id = "sandbox-claude-agent37-" + uuid4().hex[:8]

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

# The last turn left its instance asleep for the next one. A sleeping instance bills for its
# disk until it is deleted, so a script that is done with the session removes it.
coordinator = SandboxCoordinator(
    agent.db, sandbox, sandbox.checkpoint_transfer(checkpoints)
)
removed = coordinator.retire_computer(session_id, agent_id="coder")
print("Removed the session's instance:", removed)
