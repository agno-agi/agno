"""
Sofya Tools
=============================

Demonstrates Sofya tools: web search, URL extraction, and deep research.

Set SOFYA_API_KEY in your environment. Get a key at https://sofya.co
"""

from agno.agent import Agent
from agno.tools.sofya import SofyaTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: default SofyaTools (web search)
agent = Agent(tools=[SofyaTools()])

# Example 2: enable all Sofya tools (search + extract + research)
agent_all = Agent(tools=[SofyaTools(all=True)])

# Example 3: extraction only, fetch URLs as clean markdown
extract_agent = Agent(
    tools=[
        SofyaTools(
            enable_search=False,
            enable_extract=True,
        )
    ]
)

# Example 4: deep research only, returns a cited report
research_agent = Agent(
    tools=[
        SofyaTools(
            enable_search=False,
            enable_research=True,
        )
    ]
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Search for recent developments in the Model Context Protocol",
        markdown=True,
        stream=True,
    )

    extract_agent.print_response(
        "Extract the main content from https://modelcontextprotocol.io/introduction",
        markdown=True,
        stream=True,
    )

    research_agent.print_response(
        "Write a short report on how AI agents use web search tools",
        markdown=True,
        stream=True,
    )
