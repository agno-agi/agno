"""
Web Context Provider — Parallel backend
=======================================

Expose the web as a queryable context via Parallel's beta API.

Run: pip install openai parallel-web
Env: PARALLEL_API_KEY, OPENAI_API_KEY
"""

from agno.agent import Agent
from agno.context.web import WebContextProvider
from agno.context.web.parallel import ParallelBackend
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Build Provider
# ---------------------------------------------------------------------------
provider = WebContextProvider(backend=ParallelBackend())

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
