"""
Serve a Codex Agent over A2A
============================

Expose an external Codex Agent through the A2A agent namespace. External
agents use the same card and message routes as native Agents, under
`/a2a/agents/{id}`. The AgentOS database stores each run before it starts.

Prerequisites: OPENAI_API_KEY, the Codex CLI, and the `agno[a2a]` extra with `openai-codex`
Run: .venvs/demo/bin/python cookbook/05_agent_os/15_a2a/external_agent.py
Try: With the server running, rerun this file with --demo to call POST http://127.0.0.1:7779/a2a/agents/codex-assistant
"""

import asyncio
import sys

from agno.agents.codex import CodexAgent
from agno.client.a2a import A2AClient
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Codex Agent
# ---------------------------------------------------------------------------

AGENT_URL = "http://127.0.0.1:7779/a2a/agents/codex-assistant"

db = SqliteDb(
    id="a2a-external-db",
    db_file="tmp/a2a_external.db",
)

codex_assistant = CodexAgent(
    id="codex-assistant",
    name="Codex Assistant",
    description="A Codex-powered coding assistant served through A2A.",
    model="gpt-5.6-luna",
    sandbox="read-only",
    cwd=".",
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="a2a-external-os",
    description="AgentOS exposing an external Codex Agent through A2A.",
    agents=[codex_assistant],
    db=db,
    a2a_interface=True,
)
app = agent_os.get_app()


async def run_demo() -> None:
    """Discover and call the Codex Agent through its entity-scoped A2A URL."""
    client = A2AClient(AGENT_URL, timeout=180)
    card = await client.aget_agent_card()
    if card is None:
        raise RuntimeError(f"No Agent card found at {AGENT_URL}")

    result = await client.send_message(
        "In one sentence, what does a Python list comprehension do?"
    )
    if not result.is_completed:
        raise RuntimeError(f"Agent task ended with status {result.status}")

    print(f"Agent card: {card.name}")
    print(f"Agent endpoint: {card.url}")
    print(f"Task ID: {result.task_id}")
    print(f"Response: {result.content}")

    stored_task = await client.get_task(result.task_id)
    print(f"Stored task status: {stored_task.status}")


# ---------------------------------------------------------------------------
# Run Agent Server or Client Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--demo" in sys.argv:
        asyncio.run(run_demo())
    else:
        agent_os.serve(app=app, port=7779)
