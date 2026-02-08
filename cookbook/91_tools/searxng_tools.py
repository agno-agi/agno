"""
Searxng Tools
=============================

Demonstrates searxng tools.
"""

from agno.agent import Agent
from agno.tools.searxng import SearxngTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# Initialize Searxng with your Searxng instance URL
searxng = SearxngTools(
    host="http://localhost:53153",
    engines=[],
    fixed_max_results=5,
    news=True,
    science=True,
)

# Create an agent with Searxng
agent = Agent(tools=[searxng])

# Example: Ask the agent to search using Searxng

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("""
    Please search for information about artificial intelligence 
    and summarize the key points from the top results
    """)
