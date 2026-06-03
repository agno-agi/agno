"""
State Events
============

Demonstrates AG-UI state synchronization with enable_agentic_state.
The LLM uses the generic update_session_state tool to modify recipe state.
"""

from agno.agent.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

agent = Agent(
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
- special_preferences: List of dietary preferences like "High Protein", "Low Carb", "Spicy", "Budget-Friendly", "One-Pot Meal", "Vegetarian", "Vegan"
- ingredients: List of {name, amount, icon} objects. Use emoji icons like 🥕 🧅 🥚 🌾 🧈 🥛
- instructions: List of cooking step strings

When updating, preserve existing fields and only change what's needed.""",
    markdown=True,
)

agent_os = AgentOS(
    agents=[agent],
    interfaces=[AGUI(agent=agent, prefix="/shared_state")],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="state_events:app", reload=True, port=9001)
