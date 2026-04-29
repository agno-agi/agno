"""
Filesystem Context Provider
===========================

FilesystemContextProvider wraps a local directory and gives the agent
a single `query_<id>` tool. The tool routes through a read-only sub-agent
that has `FileTools` scoped to the root — list, search, and read files.

Requires: OPENAI_API_KEY
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.context.fs import FilesystemContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create the provider
# ---------------------------------------------------------------------------
fs = FilesystemContextProvider(
    id="cookbooks",
    root=Path(__file__).resolve().parent,
    model=OpenAIResponses(id="gpt-5.4-mini"),
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=fs.get_tools(),
    instructions=fs.instructions(),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"\nfs.status() = {fs.status()}\n")
    prompt = (
        "Walk me through setting up an agno context provider. Read "
        "the README and a simple example in this directory, then "
        "lay out the minimal steps with a short code snippet. Cite "
        "the files you pulled from."
    )
    print(f"> {prompt}\n")
    asyncio.run(agent.aprint_response(prompt))
