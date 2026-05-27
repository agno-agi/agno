"""
Groq Browser Search
===================

Cookbook example for `groq/browser_search.py`.
"""

from agno.agent import Agent
from agno.models.groq import Groq

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Groq(id="openai/gpt-oss-20b"),
    tools=[{"type": "browser_search"}],
)
agent.print_response("Is the Going-to-the-sun road open for public?")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
