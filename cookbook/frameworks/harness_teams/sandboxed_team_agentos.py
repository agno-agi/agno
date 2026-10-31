"""
A Team with a Sandboxed Claude Code Member behind AgentOS
=========================================================
Serves a team whose engineer is Claude Code in its own Docker container, through AgentOS
with a durable queue on Postgres. A background team run is a queued job; while the worker
runs it, the leader delegates to the engineer, whose turn runs in the member's container.
The startup checks AgentOS applies to served sandboxed agents (Postgres, a checkpoint
store every replica can read) apply to sandboxed team members too.

Build the runtime image, run Postgres, and export OPENAI_API_KEY for the leader and
ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN for Claude Code:

    .venvs/demo/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:local
    ./cookbook/scripts/run_pgvector.sh
    .venvs/demo/bin/python cookbook/frameworks/harness_teams/sandboxed_team_agentos.py

Then submit a background team run and poll it:

    curl -X POST localhost:7777/teams/sandboxed-team/runs \\
        -F session_id=demo -F background=true -F stream=false \\
        -F message="Write fizzbuzz.py for 1 to 15, run it and report the last line"
    curl "localhost:7777/teams/sandboxed-team/runs/<run_id>?session_id=demo"
"""

import os
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.postgres import PostgresDb
from agno.job_queue.config import QueueConfig
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.docker import DockerSandbox
from agno.team import Team

# ---------------------------------------------------------------------------
# Configure the Example
# ---------------------------------------------------------------------------
db = PostgresDb(
    db_url=os.getenv(
        "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
    )
)

# ---------------------------------------------------------------------------
# Create the Team
# ---------------------------------------------------------------------------
engineer = ClaudeAgent(
    id="sandboxed-engineer",
    name="Sandboxed Engineer",
    role="Writes and runs Python in its own sandboxed computer",
    model="claude-sonnet-4-6",
    permission_mode="bypassPermissions",
    sandbox=DockerSandbox(
        os.getenv("AGNO_SANDBOX_IMAGE", "agno-sandbox:local"),
        network="isolated",
        # A host whose networks overlap the default range sets AGNO_SANDBOX_SUBNET to a free one.
        subnet=os.environ.get("AGNO_SANDBOX_SUBNET", "172.30.0.0/22"),
        memory_mb=1024,
        # This example runs on one host, so a local folder holds the checkpoints. With several replicas,
        # any replica may run the next turn: use a store every replica can read, such as S3CheckpointStore.
        checkpoints=FileCheckpointStore(
            Path.home() / ".agno" / "sandbox" / "checkpoints"
        ),
    ),
)
team = Team(
    id="sandboxed-team",
    name="Sandboxed Team",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    members=[engineer],
    instructions=[
        "Delegate all coding work to the Sandboxed Engineer and relay its result briefly."
    ],
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
# The engineer has no database of its own, so it coordinates its computer on the OS database.
agent_os = AgentOS(
    id="sandboxed-team-os",
    teams=[team],
    db=db,
    queue=QueueConfig(durable=True, db=db),
    telemetry=False,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app=app, reload=False)
