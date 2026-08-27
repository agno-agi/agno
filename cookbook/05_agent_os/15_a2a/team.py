"""
Serve a Team over A2A
=====================

Expose a research Team through the A2A team namespace. Its card and message
routes live under `/a2a/teams/{id}`, not the Agent namespace.

Prerequisites: OPENAI_API_KEY and the `agno[a2a]` extra
Run: .venvs/demo/bin/python cookbook/05_agent_os/15_a2a/team.py
Try: With the server running, rerun this file with --demo to call POST http://127.0.0.1:7779/a2a/teams/research-team/v1/message:send
"""

import asyncio
import sys

from agno.agent import Agent
from agno.client.a2a import A2AClient
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Research Team
# ---------------------------------------------------------------------------

TEAM_URL = "http://127.0.0.1:7779/a2a/teams/research-team"

db = SqliteDb(
    id="a2a-team-db",
    db_file="tmp/a2a_team.db",
)

researcher = Agent(
    id="a2a-researcher",
    name="Researcher",
    role="Identify the important facts and tradeoffs.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Analyze the request and return concise factual notes.",
)

writer = Agent(
    id="a2a-writer",
    name="Writer",
    role="Turn research notes into a clear response.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Write a compact answer from the available research.",
)

research_team = Team(
    id="research-team",
    name="Research Team",
    description="A two-member team that researches and writes concise answers.",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[researcher, writer],
    db=db,
    instructions=[
        "Delegate fact finding to the Researcher.",
        "Delegate final wording to the Writer.",
        "Return one concise combined answer.",
    ],
    show_members_responses=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="a2a-team-os",
    description="AgentOS exposing a Team through A2A.",
    teams=[research_team],
    a2a_interface=True,
)
app = agent_os.get_app()


async def run_demo() -> None:
    """Discover and call the Team through its entity-scoped A2A URL."""
    client = A2AClient(TEAM_URL, timeout=90)
    card = await client.aget_agent_card()
    if card is None:
        raise RuntimeError(f"No Team card found at {TEAM_URL}")

    result = await client.send_message(
        "Give two practical reasons to keep API examples small."
    )
    if not result.is_completed:
        raise RuntimeError(f"Team task ended with status {result.status}")

    print(f"Team card: {card.name}")
    print(f"Team endpoint: {card.url}")
    print(f"Task ID: {result.task_id}")
    print(f"Response: {result.content}")


# ---------------------------------------------------------------------------
# Run Team Server or Client Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--demo" in sys.argv:
        asyncio.run(run_demo())
    else:
        agent_os.serve(app=app, port=7779)
