"""A sandboxed Claude agent on E2B: two turns, each on a fresh computer. This creates billable compute.

Build the template with e2b_template.py, export E2B_API_KEY and ANTHROPIC_API_KEY or
CLAUDE_CODE_OAUTH_TOKEN, and run Postgres:

    ./cookbook/scripts/run_pgvector.sh
    .venv/bin/python cookbook/frameworks/sandbox/e2b/sandbox_claude_e2b.py

The same agent as sandbox_claude.py with E2BSandbox in place of DockerSandbox. Each turn runs
Claude Code in an E2B computer. When the turn completes, its files and conversation are
checkpointed to ~/.agno/sandbox/checkpoints and the computer is killed; the next turn starts
a new computer restored from that checkpoint. The credential in this process's environment
is forwarded into the computer; the E2B API key stays here.
"""

import os
from uuid import uuid4

from agno.agents.claude import ClaudeAgent
from agno.db.postgres import PostgresDb
from agno.sandbox.e2b import E2BSandbox

agent = ClaudeAgent(
    id="coder",
    model="claude-sonnet-4-6",
    permission_mode="bypassPermissions",
    db=PostgresDb(
        db_url=os.getenv(
            "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
        )
    ),
    sandbox=E2BSandbox(os.getenv("E2B_TEMPLATE", "agno-sandbox")),
)

# A session that already has turns outside the sandbox cannot be moved into one, so start a new one.
session_id = "sandbox-claude-e2b-" + uuid4().hex[:8]

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
