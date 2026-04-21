"""
Web Context Provider — Exa backend
==================================

Expose the web as a queryable context via Exa's SDK.

Run: pip install openai exa-py
Env: EXA_API_KEY, OPENAI_API_KEY
"""

from agno.agent import Agent
from agno.context.web import WebContextProvider
from agno.context.web.exa import ExaBackend
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Build Provider
# ---------------------------------------------------------------------------
provider = WebContextProvider(backend=ExaBackend())

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=provider.get_tools(),
    instructions=[
        "You are a research agent.",
        provider.instructions(),
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Status:", provider.status())
    agent.print_response(
        "What is Agno? Summarize in two sentences and cite the source URL.",
        stream=True,
    )
