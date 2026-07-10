"""Seltz Tools Example.

Run `pip install seltz agno openai python-dotenv` to install dependencies.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.seltz import SeltzTools
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


load_dotenv()

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[SeltzTools(show_results=True)],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response("Search for current AI safety reports", markdown=True)
