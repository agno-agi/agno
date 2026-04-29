"""
Workspace — basic usage
=======================

A polished local-machine toolkit: read/write/edit/delete/search/shell, scoped to
a local directory (path-scoped to a `root`). Destructive operations require
confirmation by default —
see ``with_confirmation.py`` for the pause/resume flow.

This example uses ``confirm=[]`` to disable confirmation so the agent
runs end-to-end without prompts. For production, leave the defaults on.
"""

import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.workspace import Workspace

# Use a clean tmp directory so the demo doesn't touch real files.
workspace = Path(tempfile.mkdtemp(prefix="workspace_demo_"))
(workspace / "README.md").write_text(
    "# Demo workspace\n\n"
    "This file lives in a tmp directory.\n"
    "The agent below will read it and produce a summary file.\n"
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        Workspace(
            str(workspace),
            allowed=Workspace.ALL_TOOLS,
            confirm=[],
        )
    ],
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Read README.md, then write a 2-line summary to NOTES.md. "
        "After that, list the files to confirm both exist."
    )
    print(f"\nWorkspace: {workspace}")
