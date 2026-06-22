"""
Xiaomi MiMo Tool Use
====================

Give the agent a web search tool and let it call tools while thinking mode is on
(`use_thinking=True`). The model reasons about which tool to call, runs it, and
folds the result into its answer.

Run `uv pip install ddgs` to install dependencies.
"""

from agno.agent import Agent
from agno.models.xiaomi import MiMo
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=MiMo(id="mimo-v2.5-pro", use_thinking=True),
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
