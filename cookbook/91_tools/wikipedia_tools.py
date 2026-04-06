"""
Wikipedia Tools
=============================

Demonstrates wikipedia tools.
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.tools.wikipedia import WikipediaTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# Example 1: Basic Wikipedia search (without knowledge base)
agent = Agent(tools=[WikipediaTools()])

# Example 2: Wikipedia with knowledge base integration
knowledge_base = Knowledge()
kb_agent = Agent(tools=[WikipediaTools(knowledge=knowledge_base)])

# Test the agents

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Search Wikipedia for 'artificial intelligence'", markdown=True
    )
    kb_agent.print_response(
        "Find information about machine learning and add it to knowledge base",
        markdown=True,
    )
