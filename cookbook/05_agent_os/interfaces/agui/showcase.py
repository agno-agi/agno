"""
AG-UI Showcase
==============

Comprehensive cookbook exposing all AG-UI endpoints.
Run this single server to test all AG-UI features with Agno.

Endpoints:
- /agentic_chat/agui — Basic chat with tools
- /backend_tool_rendering/agui — Weather tools demo
- /human_in_the_loop/agui — HITL with confirmations
- /tool_based_generative_ui/agui — Haiku generator
- /shared_state/agui — Recipe state sync
"""

from typing import List

from pydantic import BaseModel, Field

from agno.agent.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.tools import tool


# 1. Agentic Chat — basic chat with web search
agentic_chat_agent = Agent(
    name="AgenticChat",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="You are a helpful assistant. Answer questions concisely.",
    markdown=True,
)


# 2. Backend Tool Rendering — weather tools
@tool
def get_weather(city: str) -> str:
    """Get current weather for a city."""
    weather_data = {
        "San Francisco": "Sunny, 68°F",
        "New York": "Cloudy, 55°F",
        "Tokyo": "Rainy, 62°F",
    }
    return weather_data.get(city, f"Weather for {city}: Partly cloudy, 70°F")


backend_tool_agent = Agent(
    name="WeatherAgent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[get_weather],
    instructions="You help users check weather. Use the get_weather tool.",
    markdown=True,
)


# 3. Human in the Loop — with confirmation tool
@tool(requires_confirmation=True)
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email (requires user confirmation)."""
    return f"Email sent to {to} with subject: {subject}"


@tool(requires_confirmation=True)
def delete_file(filename: str) -> str:
    """Delete a file (requires user confirmation)."""
    return f"Deleted file: {filename}"


hitl_agent = Agent(
    name="HITLAgent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[send_email, delete_file],
    instructions="You help users with tasks that require confirmation. Always use tools when asked to send emails or delete files.",
    markdown=True,
)


# 4. Tool Based Generative UI — haiku generator
class Haiku(BaseModel):
    english: List[str] = Field(description="Haiku lines in English")
    japanese: List[str] = Field(description="Haiku lines in Japanese")


@tool(external_execution=True)
def generate_haiku(english: List[str], japanese: List[str]) -> str:
    """Generate a haiku displayed in the frontend."""
    return "Haiku generated and displayed"


generative_ui_agent = Agent(
    name="HaikuAgent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[generate_haiku],
    instructions="""You are a haiku poet. When asked to create a haiku:
1. Create a beautiful haiku in both English and Japanese
2. Use the generate_haiku tool to display it
Format: 5-7-5 syllables in English, traditional Japanese style.""",
    markdown=True,
)


# 5. Shared State — recipe assistant with state sync
shared_state_agent = Agent(
    name="RecipeAssistant",
    model=OpenAIResponses(id="gpt-5.5"),
    session_state={
        "recipe": {
            "title": "",
            "skill_level": "Intermediate",
            "cooking_time": "45 min",
            "special_preferences": [],
            "ingredients": [],
            "instructions": [],
        }
    },
    add_session_state_to_context=True,
    enable_agentic_state=True,
    instructions="""You are a recipe assistant that helps users create and modify recipes.

The current recipe state is shown in <session_state>. Use it to understand what exists.

Use update_session_state to modify the recipe. The recipe structure is:
- title: Recipe name
- skill_level: "Beginner", "Intermediate", or "Advanced"
- cooking_time: "5 min", "15 min", "30 min", "45 min", or "60+ min"
- special_preferences: List like "High Protein", "Low Carb", "Spicy", "Vegetarian", "Vegan"
- ingredients: List of {name, amount, icon} objects. Use emoji icons.
- instructions: List of cooking step strings

When updating, preserve existing fields and only change what's needed.""",
    markdown=True,
)


# Create AgentOS with all endpoints
agent_os = AgentOS(
    agents=[
        agentic_chat_agent,
        backend_tool_agent,
        hitl_agent,
        generative_ui_agent,
        shared_state_agent,
    ],
    interfaces=[
        AGUI(agent=agentic_chat_agent, prefix="/agentic_chat"),
        AGUI(agent=backend_tool_agent, prefix="/backend_tool_rendering"),
        AGUI(agent=hitl_agent, prefix="/human_in_the_loop"),
        AGUI(agent=generative_ui_agent, prefix="/tool_based_generative_ui"),
        AGUI(agent=shared_state_agent, prefix="/shared_state"),
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    print("Starting AG-UI Showcase server...")
    print("Endpoints available:")
    print("  - /agentic_chat/agui")
    print("  - /backend_tool_rendering/agui")
    print("  - /human_in_the_loop/agui")
    print("  - /tool_based_generative_ui/agui")
    print("  - /shared_state/agui")
    agent_os.serve(app="showcase:app", reload=True, port=9001)
