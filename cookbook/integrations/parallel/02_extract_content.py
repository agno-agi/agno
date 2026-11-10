"""
Parallel Extract - Clean Content From URLs
==========================================

The Extract API turns specific URLs into clean, structured text - handling
JavaScript-heavy pages and PDFs - so your agent can read sources you already
have in hand instead of searching for them.

Reach for Extract when you KNOW the URLs: documentation, a filing, a
competitor's pricing page, a linked PDF.

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# ---------------------------------------------------------------------------
# Tools - Extract only
# ---------------------------------------------------------------------------
# Disable Search so the agent reads the URLs we give it rather than hunting
# for new ones. Excerpts return the most relevant passages; the agent can
# request full_content on a call when it needs the entire page.
extract_tools = ParallelTools(
    enable_search=False,
    enable_extract=True,
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[extract_tools],
    markdown=True,
    instructions=[
        "Extract content from the URLs the user provides.",
        "Summarize the key points and cite each URL you used.",
    ],
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Read https://parallel.ai and https://docs.parallel.ai and tell me "
        "what APIs Parallel offers and who they are for.",
        stream=True,
    )
