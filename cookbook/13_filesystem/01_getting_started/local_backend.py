"""
FileSystem - Local Backend
==========================
Store the agent's files as real files on disk instead of rows in a database.
Pass LocalFileSystem as the backend; the agent code stays the same.

This is handy in development, when you want to open what the agent wrote with
your editor or read it with ls and cat.

This example has the agent write two files, then prints the on-disk tree.
"""

from pathlib import Path
from uuid import uuid4

from agno.agent import Agent
from agno.fs import FileSystem
from agno.fs.local import LocalFileSystem
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create FileSystem
# ---------------------------------------------------------------------------
ROOT = f"tmp/agent_fs_local_{uuid4().hex}"

fs = FileSystem(LocalFileSystem(root=ROOT))

# ---------------------------------------------------------------------------
# Create Agent - identical to the database-backed version
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[fs.tools()],
    instructions="You are a note-keeping assistant.",
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Record two things: write 'Summarized the onboarding doc; the migration "
        "timeline is the key risk to flag' to notes/summary.md, and append "
        "'https://example.com/a' to seen/2026-07-24.md."
    )

    print("on-disk tree under " + ROOT + ":")
    root = Path(ROOT)
    for path in sorted(root.rglob("*")):
        if path.is_file():
            print("  " + path.relative_to(root).as_posix())
