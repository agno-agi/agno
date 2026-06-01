"""
Parallel News Search
=============================

Search for recent news and web content using natural language.

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: Basic web search
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[ParallelTools()],
    markdown=True,
)

# Example 2: Search with domain filtering
filtered_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ParallelTools(
            include_domains=["techcrunch.com", "wired.com", "arstechnica.com"],
        )
    ],
    markdown=True,
)

# Example 3: Search with result limits
concise_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ParallelTools(
            max_results=5,
            max_chars_per_result=500,
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "What are the latest developments in AI agents?",
        stream=True,
    )
