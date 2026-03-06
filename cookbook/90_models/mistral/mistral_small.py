"""Run `uv pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.mistral import MistralChat
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=MistralChat(id="mistral-small-latest"),
    tools=[WebSearchTools()],
    markdown=True,
)
agent.print_response("Tell me about mistrall small, any news", stream=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
