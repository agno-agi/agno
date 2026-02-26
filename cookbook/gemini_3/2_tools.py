"""
2. Agent with Tools
===================
Add external tools so the agent can take actions beyond text generation.
This agent uses web search to find current information.

Run:
    python cookbook/gemini_3/2_tools.py

Example prompt:
    "Compare the latest funding rounds in AI startups this month"
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
finance_agent = Agent(
    name="Finance Agent",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions="""\
You are a finance research agent. You find and analyze current financial news.

## Workflow

1. Search the web for the requested financial information
2. Analyze and compare findings
3. Present a clear, structured summary

## Rules

- Always cite your sources
- Use tables for comparisons
- Include dates for all data points\
""",
    tools=[WebSearchTools()],
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    finance_agent.print_response(
        "Compare the latest funding rounds in AI startups this month",
        stream=True,
    )
