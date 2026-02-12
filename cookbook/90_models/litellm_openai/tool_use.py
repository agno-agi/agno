"""Run `uv pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.litellm import LiteLLMOpenAI
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=LiteLLMOpenAI(id="gpt-4o"),
    tools=[WebSearchTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
