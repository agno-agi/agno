"""
Serpapi Tools
=============================

Demonstrates serpapi tools.
"""

from agno.agent import Agent
from agno.tools.serpapi import SerpApiTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# Example 1: Enable specific SerpAPI functions
agent = Agent(
    tools=[SerpApiTools(enable_search_google=True, enable_search_youtube=False)]
)

# Example 2: Enable all SerpAPI functions
agent_all = Agent(tools=[SerpApiTools(all=True)])

# Example 3: Enable only YouTube search
youtube_agent = Agent(
    tools=[SerpApiTools(enable_search_google=False, enable_search_youtube=True)]
)

# Test the agents

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What's happening in the USA?", markdown=True)
    youtube_agent.print_response("Search YouTube for 'python tutorial'", markdown=True)
