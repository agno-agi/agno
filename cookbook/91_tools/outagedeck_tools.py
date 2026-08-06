"""OutageDeck Tools - Live operational status without credentials.

This example gives an agent current provider status, active and historical
incidents, and individual service health through OutageDeck's public API.
No OutageDeck account or API key is required.

API documentation:
https://outagedeck.com/docs/api?utm_source=agno&utm_medium=integration&utm_campaign=agno_toolkit
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.outagedeck import OutageDeckTools

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[OutageDeckTools()],
    instructions=[
        "Always use OutageDeck before making claims about current provider or service status.",
        "Summarize active incidents with severity, state, and last update time.",
        "Include the OutageDeck URL returned by the tool so the reader can inspect the live status page.",
    ],
    markdown=True,
)

if __name__ == "__main__":
    print("=== Provider status ===")
    agent.print_response(
        "Is GitHub operational right now? Include active incidents and affected services.",
        stream=True,
    )

    print("\n=== Active incidents ===")
    agent.print_response(
        "List active major or critical incidents across all providers.",
        stream=True,
    )

    print("\n=== Service status ===")
    agent.print_response(
        "Check the current status of GitHub Actions and summarize its latest incidents.",
        stream=True,
    )
