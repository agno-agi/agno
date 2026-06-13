"""
Team State Events
=================

Demonstrates AG-UI state synchronization with a Team using enable_agentic_state.
The team coordinates multiple agents while maintaining shared session state.
"""

from agno.agent.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.team.team import Team

recipe_creator = Agent(
    name="recipe_creator",
    role="Recipe Creator",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="You create recipes with ingredients and instructions. Focus on the cooking process.",
    markdown=True,
)

nutrition_advisor = Agent(
    name="nutrition_advisor",
    role="Nutrition Advisor",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="You advise on dietary preferences and nutritional aspects of recipes.",
    markdown=True,
)

recipe_team = Team(
    name="RecipeTeam",
    members=[recipe_creator, nutrition_advisor],
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
    instructions="""You are a recipe team that helps users create and modify recipes.

The current recipe state is shown in <session_state>. Use it to understand what exists.

Use update_session_state to modify the recipe. The recipe structure is:
- title: Recipe name
- skill_level: "Beginner", "Intermediate", or "Advanced"
- cooking_time: "5 min", "15 min", "30 min", "45 min", or "60+ min"
- special_preferences: List of dietary preferences like "High Protein", "Low Carb", "Spicy", "Budget-Friendly", "One-Pot Meal", "Vegetarian", "Vegan"
- ingredients: List of {name, amount, icon} objects. Use emoji icons like 🥕 🧅 🥚 🌾 🧈 🥛
- instructions: List of cooking step strings

Coordinate between the recipe creator (ingredients, instructions) and nutrition advisor (dietary preferences).
When updating, preserve existing fields and only change what's needed.""",
    show_members_responses=True,
    markdown=True,
)

agent_os = AgentOS(
    teams=[recipe_team],
    interfaces=[AGUI(team=recipe_team, prefix="/shared_state")],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="team_state_events:app", reload=True, port=9001)
