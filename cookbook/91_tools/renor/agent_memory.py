"""
Renor MCP Memory
================

Give an Agno agent memory that outlives the conversation.

This recipe connects an Agno agent to Renor, a memory server that speaks MCP and
stores plain Markdown in a folder you own (`VAULT_PATH`). The first run saves a
decision; the second run opens a new MCP session and recalls it, so the agent
answers from disk instead of from chat history.

The server runs self-hosted over stdio with `npx -y renor-engine mcp`, so no
Renor account is needed. It exposes `remember_fact`, `search`, `facts`,
`evidence`, `keyword`, `entity`, `note`, and `status`.

Prompts to try:
- "We are moving enterprise customers to annual billing from Q1. Save that decision."
- "What did we decide about enterprise billing, and when does it start?"

Run: `uv pip install "agno[mcp]" openai`
"""

import asyncio
import os
from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Renor keeps one Markdown ledger and one SQLite index under this folder.
# It is gitignored; delete it to start the second run from empty memory.
VAULT_PATH = os.environ.get(
    "RENOR_VAULT_PATH",
    str(Path(__file__).parent / "tmp" / "renor-vault"),
)

# Self-hosted stdio server: memory stays on this machine and needs no account.
SERVER_COMMAND = "npx -y renor-engine mcp"

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------

INSTRUCTIONS = dedent(
    """
    You are a product manager's assistant with access to Renor, a long-term memory server.

    When the user states a decision, a correction, or a fact worth keeping beyond this
    conversation, call `remember_fact` with a `subject`, a `predicate`, and an `object`.
    Keep each in a single string, and include the reason when the user gives one.

    Before answering a question about past decisions or earlier work, call `search`
    with the user's own words, then answer from what memory returns. If memory has
    nothing, say so instead of guessing.
    """
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


def create_agent(memory_tools: MCPTools) -> Agent:
    """Build an agent whose long-term memory is the Renor MCP server."""
    return Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        tools=[memory_tools],
        instructions=INSTRUCTIONS,
        markdown=True,
    )


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------


async def run(message: str) -> None:
    """Open a fresh MCP session so each run reads memory from disk, not chat history."""
    # `env` is merged into the inherited environment, so `npx` still resolves via PATH.
    async with MCPTools(
        command=SERVER_COMMAND,
        env={"VAULT_PATH": VAULT_PATH},
    ) as memory_tools:
        await create_agent(memory_tools).aprint_response(message, stream=True)


if __name__ == "__main__":
    asyncio.run(
        run(
            "We are moving enterprise customers to annual billing from Q1. Save that decision."
        )
    )
    asyncio.run(
        run("What did we decide about enterprise billing, and when does it start?")
    )
