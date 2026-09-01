"""
Discover an A2A Agent Card
==========================

Read the Agent card from the entity-scoped discovery route with both the
synchronous and asynchronous first-party client methods. The example prints
stable identity and endpoint fields from the running server.

Prerequisites: Start basic.py on port 7779
Run: .venvs/demo/bin/python cookbook/05_agent_os/15_a2a/agent_card.py
Try: Fetch GET http://127.0.0.1:7779/a2a/agents/a2a-assistant/.well-known/agent-card.json
"""

import asyncio

from agno.client.a2a import A2AClient, AgentCard

# ---------------------------------------------------------------------------
# Create A2A Client
# ---------------------------------------------------------------------------

AGENT_URL = "http://127.0.0.1:7779/a2a/agents/a2a-assistant"
CARD_URL = f"{AGENT_URL}/.well-known/agent-card.json"


def read_card_sync(client: A2AClient) -> AgentCard:
    """Fetch a card with the synchronous API."""
    card = client.get_agent_card()
    if card is None:
        raise RuntimeError(f"No Agent card found at {CARD_URL}")
    return card


async def read_card_async(client: A2AClient) -> AgentCard:
    """Fetch a card with the asynchronous API."""
    card = await client.aget_agent_card()
    if card is None:
        raise RuntimeError(f"No Agent card found at {CARD_URL}")
    return card


def show_card(card: AgentCard, label: str) -> None:
    """Print stable discovery fields."""
    print(f"{label} name: {card.name}")
    print(f"{label} description: {card.description}")
    print(f"{label} version: {card.version}")
    print(f"{label} endpoint: {card.url}")


# ---------------------------------------------------------------------------
# Run Agent Card Discovery
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    a2a_client = A2AClient(AGENT_URL, timeout=30)
    sync_card = read_card_sync(a2a_client)
    async_card = asyncio.run(read_card_async(a2a_client))

    if (sync_card.name, sync_card.url) != (async_card.name, async_card.url):
        raise RuntimeError(
            "Sync and async card discovery returned different identities"
        )

    print(f"Card route: {CARD_URL}")
    show_card(sync_card, "Sync")
    show_card(async_card, "Async")
