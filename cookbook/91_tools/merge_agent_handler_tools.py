"""
Merge Agent Handler Tools
=========================

Demonstrates how to use Merge Agent Handler tools from Agno.

Prerequisites:
1. Set MERGE_API_KEY environment variable.
2. Create a tool pack and registered user in Merge Agent Handler.
3. Set TOOL_PACK_ID and REGISTERED_USER_ID placeholders below.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.merge_agent_handler import MergeAgentHandlerTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        MergeAgentHandlerTools(
            tool_pack_id="YOUR_TOOL_PACK_ID",
            registered_user_id="YOUR_REGISTERED_USER_ID",
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "List the available tools in my Merge tool pack, then use the right one to fetch the latest Gong users.",
        markdown=True,
    )
