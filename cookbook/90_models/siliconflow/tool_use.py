"""Run `uv pip install duckduckgo-search` to install dependencies."""

from agno.agent import Agent
from agno.models.siliconflow import Siliconflow
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

"""
The current version of the siliconflow-chat model's Function Calling capability is stable and supports tool integration effectively.
"""

agent = Agent(
    model=Siliconflow(id="openai/gpt-oss-120b"),
    tools=[WebSearchTools()],
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
)

agent.print_response("What happing in America?")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
