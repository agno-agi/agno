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
# Pick a root — this cookbook's directory
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Create the provider
# ---------------------------------------------------------------------------
fs = FilesystemContextProvider(root=ROOT, id="cookbooks", name="Cookbooks")

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
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
        "What Python files live in this directory, and what does "
        "06_custom_provider.py demonstrate? Quote a few lines from "
        "its docstring so I know you actually read it."
    )
    print(f"> {prompt}\n")
    asyncio.run(agent.aprint_response(prompt))
