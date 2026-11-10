"""
Xai Live Search Agent Stream
============================

Cookbook example for `xai/live_search_agent_stream.py`.
"""

from agno.agent import Agent
from agno.models.xai.xai import xAI

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=xAI(
        id="grok-3",
        search_parameters={
            "mode": "on",
            "max_search_results": 20,
            "return_citations": True,
        },
    ),
    markdown=True,
)
agent.print_response(
    "Provide me a digest of world news in the last 24 hours.", stream=True
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
