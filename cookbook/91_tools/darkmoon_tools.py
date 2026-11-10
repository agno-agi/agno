"""
Darkmoon Pentest Tools
======================

Demonstrates an agent that starts an autonomous Darkmoon penetration test against a target you are
authorised to assess, then summarises the findings.

Requirements:
- A self-hosted Darkmoon instance with its Dashboard API reachable (https://github.com/ASCIT31/Dark-Moon).
  The engine and CLI are open source; the dashboard and its API are part of the Pro edition.

Set the following environment variables (or pass them to DarkmoonTools):

    export DARKMOON_BASE_URL="http://localhost:8000"
    export DARKMOON_USERNAME="your_username"
    export DARKMOON_PASSWORD="your_password"
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.darkmoon import DarkmoonTools

agent = Agent(
    name="Application Security Analyst",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[DarkmoonTools()],
    instructions=[
        "Only assess targets the user has stated they own or are authorised to test.",
        "Treat findings as leads that need human review, not as proven facts.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "Run a Darkmoon assessment against staging.example.com and summarise the high severity findings."
    )
