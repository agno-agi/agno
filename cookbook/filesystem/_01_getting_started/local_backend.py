"""
FileSystem - Local Backend
=======================

The storage backend is a seam: swap DbFileSystem for LocalFileSystem (real
files on disk) and the agent code does not change. Useful in development when
you want to inspect the store with ordinary shell tools.

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

fs = FileSystem(backend=LocalFileSystem(root=ROOT), namespace="getting-started")

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
        "Record two things: write 'prefer short answers' to notes/style.md, and "
        "append 'https://example.com/a' to seen/2026-07-24.md."
    )

    print("on-disk tree under " + ROOT + ":")
    root = Path(ROOT)
    for path in sorted(root.rglob("*")):
        if path.is_file():
            print("  " + path.relative_to(root).as_posix())
