"""Silent External Tools - Suppress verbose messages in frontends

When using `external_execution=True`, the agent prints "I have tools to execute..."
messages. Add `external_execution_silent=True` to suppress these for cleaner UX in production.

This cookbook is for AgentOS/AGUI where tool execution happens in the frontend.
The frontend will receive the tool call and handle execution on the client side.
"""

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.tools import tool
from agno.tools.duckduckgo import DuckDuckGoTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------


# external_execution_silent=True suppresses "I have tools to execute..." verbose messages
@tool(external_execution=True, external_execution_silent=True)
def generate_haiku(topic: str) -> str:
    """Generate a haiku about a given topic and display it in the frontend.

    Args:
        topic: The topic for the haiku (e.g., "nature", "technology", "love")

    Returns:
        Confirmation that the haiku was generated and displayed
    """
    return f"Haiku about '{topic}' generated and displayed in frontend"


agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        DuckDuckGoTools(),
        generate_haiku,
    ],
    description="You are a helpful AI assistant with both backend and frontend capabilities. You can search the web, create beautiful haikus, modify the UI, ask for user confirmations, and create visualizations.",
    instructions="""
    You are a versatile AI assistant with the following capabilities:

    **Tools (executed on server):**
    - Web search using DuckDuckGo for finding current information

    **Frontend Tools (executed on client):**
    - generate_haiku: Creates a haiku about a given topic

    Always be helpful, creative, and use the most appropriate tool for each request!
    """,
    add_datetime_to_context=True,
    add_history_to_context=True,
    add_location_to_context=True,
    timezone_identifier="Etc/UTC",
    markdown=True,
    debug_mode=True,
)


# Setup your AgentOS app
agent_os = AgentOS(
    agents=[agent],
    interfaces=[AGUI(agent=agent)],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:9001/config

    Use Port 9001 to configure Dojo endpoint.
    """
    agent_os.serve(app="agent_with_silent_tools:app", port=9001, reload=True)
