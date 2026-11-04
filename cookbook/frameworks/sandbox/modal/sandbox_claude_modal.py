"""A sandboxed Claude agent on Modal: two turns, each on a fresh sandbox. This creates billable compute.

Sign in to Modal (modal token new), export ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN, and run
Postgres:

    ./cookbook/scripts/run_pgvector.sh
    .venv/bin/python cookbook/frameworks/sandbox/modal/sandbox_claude_modal.py

The same agent as sandbox_claude.py with ModalSandbox in place of DockerSandbox. Each turn runs
Claude Code in a Modal sandbox. When the turn completes, its files and conversation are
checkpointed to ~/.agno/sandbox/checkpoints and the sandbox stays warm for the next turn. Modal
cannot pause it, so the script removes it at the end rather than leave it running until its
lifetime ends. The credential in this process's environment is forwarded into the sandbox.
"""

import os
from pathlib import Path
from uuid import uuid4

from agno.agents.claude import ClaudeAgent
from agno.db.postgres import PostgresDb
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.coordinator import SandboxCoordinator
from agno.sandbox.modal import ModalSandbox
from modal_image import runtime_image

db = PostgresDb(
    db_url=os.getenv(
        "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
    )
)
checkpoints = FileCheckpointStore(Path.home() / ".agno" / "sandbox" / "checkpoints")
sandbox = ModalSandbox(runtime_image(), memory_mb=2048, checkpoints=checkpoints)
agent = ClaudeAgent(
    id="coder",
    model=os.getenv("AGNO_SANDBOX_MODEL", "claude-sonnet-4-6"),
    permission_mode="bypassPermissions",
    db=db,
    sandbox=sandbox,
)

# A session that already has turns outside the sandbox cannot be moved into one, so start a new one.
session_id = "sandbox-claude-modal-" + uuid4().hex[:8]

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

# The checkpoint stays the recovery point, so a later turn restores onto a fresh sandbox.
coordinator = SandboxCoordinator(db, sandbox, sandbox.checkpoint_transfer(checkpoints))
print(
    "Warm sandbox removed:", coordinator.retire_computer(session_id, agent_id="coder")
)
