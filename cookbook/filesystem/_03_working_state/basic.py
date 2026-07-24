"""
Working State - Basic
=====================

Progress checkpoints that survive across sessions and runs: the agent records
where it stopped in state/checkpoint.md, and the next session - fresh, with no
shared history - resumes from exactly that point.

This example runs a four-step task as two sessions of two steps each. For the
cross-PROCESS durability proof, see _01_getting_started/basic.py.
"""

from uuid import uuid4

from agno.agent import Agent
from agno.fs import FileSystem
from agno.fs.db import DbFileSystem
from agno.models.openai import OpenAIResponses

STEPS = [
    "1. Export the users table",
    "2. Export the orders table",
    "3. Verify row counts match",
    "4. Write the summary report",
]

# ---------------------------------------------------------------------------
# Create FileSystem
# ---------------------------------------------------------------------------
# Fresh per-run db so the demo starts from step 1 every execution. A real
# resumable job pins one fixed, shared db_url so the checkpoint outlives the
# process, not just the session.
DB_FILE = f"tmp/agent_fs_checkpoint_{uuid4().hex}.db"

fs = FileSystem(
    backend=DbFileSystem(db_url=f"sqlite:///{DB_FILE}"), namespace="migration"
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[fs.tools()],
    instructions=(
        "You run a data migration with these steps:\n" + "\n".join(STEPS) + "\n"
        "Each session you have time for exactly TWO steps. Read state/checkpoint.md "
        "first (it may not exist on the first run) to see what is already done. "
        "Perform the next two pending steps (performing = describing the work as "
        "done), then overwrite state/checkpoint.md with the full list of completed "
        "steps using write_file. Reply with which steps you completed this session."
    ),
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Distinct session_ids: session 2 is genuinely fresh (no shared conversation
    # state), so resuming the migration can only come from the checkpoint file.
    print("session 1: no checkpoint exists yet")
    agent.print_response("Continue the migration.", session_id="migration-1")
    print("checkpoint after session 1:")
    print(fs.read("state/checkpoint.md"))

    print("session 2: a fresh session resumes from the checkpoint")
    agent.print_response("Continue the migration.", session_id="migration-2")
    print("checkpoint after session 2:")
    print(fs.read("state/checkpoint.md"))
