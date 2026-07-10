"""
Memanto Integration
===================

Demonstrates Memanto as a persistent semantic memory layer for an Agno agent.

Uses MemantoTools (same pattern as ZepTools) for agentic remember / recall / answer.

Prerequisites:
1. Install Memanto CLI: `pip install memanto`
2. Configure Moorcheh on the Memanto server: `export MOORCHEH_API_KEY=...`
3. Start the server: `memanto serve`
4. Create an agent (once): `memanto agent create agno-demo`

Optional env vars:
- MEMANTO_URL (default http://localhost:8000)
- MEMANTO_AGENT_ID (default agno-demo)
"""

import os

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.memanto import MemantoTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
MEMANTO_URL = os.getenv("MEMANTO_URL", "http://localhost:8000")
MEMANTO_AGENT_ID = os.getenv("MEMANTO_AGENT_ID", "agno-demo")

memanto_tools = MemantoTools(
    agent_id=MEMANTO_AGENT_ID,
    base_url=MEMANTO_URL,
    add_instructions=True,
)

# Seed a preference (comment out after first run if you want a clean re-test)
memanto_tools.remember(
    content="Alice prefers email communication and dark mode UI.",
    memory_type="preference",
    confidence=0.95,
    tags="ui, communication",
)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[memanto_tools],
    instructions=[
        "You are a helpful assistant with long-term Memanto memory.",
        "Use the recall tool before asking the user to repeat known preferences.",
        "Store important new preferences with the remember tool.",
    ],
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    user_id = "alice@example.com"

    print("=" * 60)
    print("Run 1: Introduce yourself")
    print("=" * 60)
    agent.print_response(
        "Hi, my name is Alice. I work in NYC and prefer concise answers.",
        user_id=user_id,
        stream=True,
    )

    print()
    print("=" * 60)
    print("Run 2: Ask what the agent knows")
    print("=" * 60)
    agent.print_response(
        "What do you know about my communication and UI preferences?",
        user_id=user_id,
        stream=True,
    )
