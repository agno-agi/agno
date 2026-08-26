"""
Volcengine Ark Tool Use
=======================

Give the agent a web search tool and let it call tools while thinking mode is on
(`use_thinking=True`). The model reasons about which tool to call, runs it, and
folds the result into its answer.

Run `uv pip install ddgs` to install dependencies.
"""

from agno.agent import Agent
from agno.models.volcengine import Ark
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Ark(id="doubao-seed-2-1-pro-260628", use_thinking=True),
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
        show_full_reasoning=True,
    )
