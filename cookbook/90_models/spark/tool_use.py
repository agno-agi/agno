"""
iFLYTEK Spark Tool Use
======================

Give the agent a web search tool and let it call tools. Spark Max
(`generalv3.5`), Spark Max-32K (`max-32k`) and Spark 4.0 Ultra (`4.0Ultra`)
support function calling.

Run `uv pip install ddgs` to install dependencies.
"""

from agno.agent import Agent
from agno.models.spark import Spark
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Spark(id="4.0Ultra"),
    tools=[WebSearchTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "What is happening in France?",
        stream=True,
    )
