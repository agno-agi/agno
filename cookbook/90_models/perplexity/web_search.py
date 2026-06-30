"""
Perplexity Web Search
=====================

Cookbook example for `perplexity/web_search.py`.
"""

from agno.agent import Agent, RunOutput  # noqa
from agno.models.perplexity import Perplexity

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Perplexity(id="sonar-pro"), markdown=True)

# Print the response in the terminal
agent.print_response("Show me top 2 news stories from USA?")

# Get the response in a variable
# run: RunOutput = agent.run("What is happening in the world today?")
# print(run.content)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
