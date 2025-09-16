from typing import List

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.tools import tool
from agno.tools.duckduckgo import DuckDuckGoTools


# Frontend Tools
@tool(external_execution=True)
def generate_haiku(
    english: List[str], japanese: List[str], image_names: List[str]
) -> str:
    """Generate a haiku in Japanese and English and display it in the frontend."""
    return "Haiku generated and displayed in frontend"


@tool(external_execution=True)
def change_background(background: str) -> str:
    """Change the background color or style of the chat interface."""
    return f"Background changed to: {background}"


@tool(external_execution=True)
def user_confirmation(message: str, action: str, importance: str = "medium") -> str:
    """Ask the user for confirmation before proceeding with an action."""
    return f"User confirmation requested for: {action}"


@tool(external_execution=True)
def create_chart(chart_type: str, data: List[dict], title: str) -> str:
    """Create and display a chart or visualization in the frontend."""
    return f"Chart created: {chart_type} chart titled '{title}'"


agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        DuckDuckGoTools(),
        generate_haiku,
        change_background,
        user_confirmation,
        create_chart,
    ],
    description="You are a helpful AI assistant with both backend and frontend capabilities. You can search the web, create beautiful haikus, modify the UI, ask for user confirmations, and create visualizations.",
    instructions="""
    You are a versatile AI assistant with the following capabilities:

    **Backend Tools (executed on server):**
    - Web search using DuckDuckGo for finding current information

    **Frontend Tools (executed in browser):**
    - Generate beautiful haikus with English/Japanese text and images
    - Change the chat background color or style for better user experience
    - Ask users for confirmation before important actions
    - Create charts and visualizations from data

    **When to use frontend tools:**
    - Use generate_haiku when users ask for poems or creative content
    - Use change_background when users want to customize the interface
    - Use user_confirmation for important decisions or actions
    - Use create_chart when presenting data that would benefit from visualization

    Always be helpful, creative, and use the most appropriate tool for each request!
    """,
    add_datetime_to_context=True,
    add_history_to_context=True,
    add_location_to_context=True,
    timezone_identifier="Etc/UTC",
    markdown=True,
    debug_mode=True,
)


# Setup our AgentOS app
agent_os = AgentOS(
    agents=[agent],
    interfaces=[AGUI(agent=agent)],
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run our AgentOS.
    
    You can see the configuration and available apps at:
    http://localhost:7777/config
    
    Use Port 9001 to configure Dojo endpoint.
    """
    agent_os.serve(app="agent_with_tools:app", port=9001, reload=True)
