"""
Parallel Quickstart - Web Research Agent
========================================

The smallest possible Parallel-powered agent: give an Agent the Parallel
Search API and ask it something that needs fresh information from the web.

Parallel's Search API is built for agents - it takes a natural-language
objective and returns ranked excerpts the model can reason over directly,
so a single tool call is usually enough to ground an answer.

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
# ParallelTools enables the Search and Extract APIs by default.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[ParallelTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "What did Parallel (parallel.ai) launch most recently, and when?",
        stream=True,
    )
