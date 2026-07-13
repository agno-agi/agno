"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.azure import AzureOpenAI
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=AzureOpenAI(id="gpt-4o-mini"),
    tools=[WebSearchTools()],
    markdown=True,
)

agent.print_response("Whats happening in France?", stream=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
