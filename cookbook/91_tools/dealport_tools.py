"""Dealport SMB, commercial property, and verified owner intelligence tools.

Set DEALPORT_API_KEY and OPENAI_API_KEY before running this example. The agent
sizes an Ohio commercial HVAC market for free ($0.00) with preview_companies
before unlocking paid Records.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.dealport import DealportTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[DealportTools()],
    instructions=[
        "Always call preview_companies ($0.00) first to size a market before calling search_companies.",
        "Cite whether company and property facts come from primary public filings.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Preview how many independent commercial HVAC companies (NAICS 238220) operate in Ohio and list the 5 sample companies.",
        stream=True,
    )
