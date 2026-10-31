"""
A Sandboxed Claude Code Step
============================
A workflow step that runs Claude Code in its own Docker container. Every run of the
same workflow session uses that step's computer: the file Claude writes in the first
run is there for the second, on a warm container or a fresh one restored from the
step's last checkpoint.

The step keeps its computer binding, checkpoints and conversation in a session of its
own, derived from the workflow's session id, so the workflow's session is never bound to
one step's computer.

Build the runtime image, run Postgres, and export ANTHROPIC_API_KEY or
CLAUDE_CODE_OAUTH_TOKEN for Claude Code:

    .venvs/demo/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:local
    ./cookbook/scripts/run_pgvector.sh
    .venvs/demo/bin/python cookbook/frameworks/harness_workflows/sandboxed_step.py
"""

import os
from pathlib import Path
from uuid import uuid4

from agno.agents.claude import ClaudeAgent
from agno.db.postgres import PostgresDb
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.docker import DockerSandbox
from agno.workflow import Step, Workflow

# ---------------------------------------------------------------------------
# Configure the Example
# ---------------------------------------------------------------------------
db = PostgresDb(
    db_url=os.getenv(
        "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
    )
)

# ---------------------------------------------------------------------------
# Create the Workflow
# ---------------------------------------------------------------------------
engineer = ClaudeAgent(
    id="sandboxed-engineer",
    name="Sandboxed Engineer",
    model="claude-sonnet-4-6",
    permission_mode="bypassPermissions",
    db=db,
    sandbox=DockerSandbox(
        os.getenv("AGNO_SANDBOX_IMAGE", "agno-sandbox:local"),
        network="isolated",
        # A host whose networks overlap the default range sets AGNO_SANDBOX_SUBNET to a free one.
        subnet=os.environ.get("AGNO_SANDBOX_SUBNET", "172.30.0.0/22"),
        memory_mb=1024,
        checkpoints=FileCheckpointStore(
            Path.home() / ".agno" / "sandbox" / "checkpoints"
        ),
    ),
)
workflow = Workflow(
    id="sandboxed-step",
    name="Sandboxed Step",
    steps=[Step(name="engineer", agent=engineer)],
    db=db,
)

# ---------------------------------------------------------------------------
# Run the Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "sandboxed-step-" + uuid4().hex[:8]

    workflow.print_response(
        "Write fizzbuzz.py that prints FizzBuzz for 1 to 15, run it, and report the last line.",
        session_id=session_id,
        stream=True,
    )
    # Same session: the step's file and conversation are on its computer for the next run.
    workflow.print_response(
        "Change fizzbuzz.py to go up to 20, run it again, and report the last line.",
        session_id=session_id,
        stream=True,
    )
