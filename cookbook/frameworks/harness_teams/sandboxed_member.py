"""
A Sandboxed Claude Code Member
==============================
An Agno team whose engineer is Claude Code running in its own Docker container. Every
team turn the leader delegates to the engineer runs on that member's computer: the files
it writes and its Claude conversation carry over to the next turn, on a warm container
or a fresh one restored from the member's last checkpoint.

The member keeps its computer binding, checkpoints and conversation in a session of its
own, derived from the team's session id, so the team's session is never bound to one
member's computer and two sandboxed members of a team each get their own.

Build the runtime image, run Postgres, and export OPENAI_API_KEY for the leader and
ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN for Claude Code:

    .venvs/demo/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:local
    ./cookbook/scripts/run_pgvector.sh
    .venvs/demo/bin/python cookbook/frameworks/harness_teams/sandboxed_member.py
"""

import os
from pathlib import Path
from uuid import uuid4

from agno.agents.claude import ClaudeAgent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
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
team = Team(
    id="sandboxed-team",
    name="Sandboxed Team",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    members=[engineer],
    instructions=[
        "Delegate all coding work to the Sandboxed Engineer and relay its result briefly."
    ],
    # The leader remembers earlier turns of the session, so a follow-up can refer to them.
    add_history_to_context=True,
    db=db,
)

# ---------------------------------------------------------------------------
# Run the Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "sandboxed-team-" + uuid4().hex[:8]

    team.print_response(
        "Write fizzbuzz.py that prints FizzBuzz for 1 to 15, run it, and report the last line.",
        session_id=session_id,
        stream=True,
        show_member_responses=True,
    )
    # Same session: the engineer's file and conversation are on its computer for the next turn.
    team.print_response(
        "Ask the engineer to change fizzbuzz.py to go up to 20, run it again, and report the last line.",
        session_id=session_id,
        stream=True,
        show_member_responses=True,
    )
