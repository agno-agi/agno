"""
Huggingface Tool Use
====================

Cookbook example for `huggingface/tool_use.py`.
"""

from agno.agent import Agent
from agno.models.huggingface import HuggingFace
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=HuggingFace(id="openai/gpt-oss-120b"),
    tools=[WebSearchTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("What is the latest news on AI?")

    # --- Sync + Streaming ---
    agent.print_response("What is the latest news on AI?", stream=True)
