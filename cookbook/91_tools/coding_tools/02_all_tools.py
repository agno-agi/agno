"""
CodingTools: All 7 Tools Enabled
=================================
Enable all tools including the exploration tools (grep, find, ls)
by setting all=True or enabling them individually.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.coding import CodingTools

# ---------------------------------------------------------------------------
# Create Agent with all CodingTools
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[CodingTools(base_dir=".", all=True)],
    instructions="You are a coding assistant. Use the coding tools to help the user.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Find all Python files in this directory, then grep for any import statements.",
        stream=True,
    )
