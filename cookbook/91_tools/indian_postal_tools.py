"""
Indian Postal Tools
=============================

Demonstrates Indian Postal PIN Code tools.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.indian_postal import IndianPostalTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[IndianPostalTools()],
    description="You are an Indian postal assistant. Use the available tools to look up post offices by PIN code or branch name and answer questions about them.",
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response("What post offices are in PIN code 600001?", markdown=True)
