"""
Openai Websearch Builtin Tool
=============================

Cookbook example for `openai/responses/websearch_builtin_tool.py`.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.file import FileTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-4o"),
    tools=[{"type": "web_search_preview"}, FileTools()],
    instructions="Save the results to a file with a relevant name.",
    markdown=True,
)
agent.print_response("Whats happening in France?")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
