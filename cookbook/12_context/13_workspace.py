"""
Workspace Context Provider
==========================

WorkspaceContextProvider wraps a project directory and gives the agent
a single `query_<id>` tool. The tool routes through a read-only sub-agent
that has the `Workspace` toolkit scoped to the root: list files, search
content, and read files with line numbers.

Use this for repository roots and active project workspaces. It skips
common dependency directories, build outputs, caches, virtualenvs, and
agent scratch folders by default.

Requires: OPENAI_API_KEY
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.context.workspace import WorkspaceContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create the provider
# ---------------------------------------------------------------------------
project = WorkspaceContextProvider(
    id="agno",
    name="Agno Project",
    root=Path(__file__).resolve().parents[2],
    model=OpenAIResponses(id="gpt-5.4-mini"),
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=project.get_tools(),
    instructions=project.instructions(),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"\nproject.status() = {project.status()}\n")
    prompt = (
        "Find where the workspace context provider and Workspace toolkit are "
        "implemented. Explain why this provider is better than a generic "
        "filesystem provider for repository roots. Cite the files you read."
    )
    print(f"> {prompt}\n")
    asyncio.run(agent.aprint_response(prompt))
