"""
Shared State — Dojo Demo
=========================

Agent with session state that syncs with frontend.

Dojo expects state structure:
{
    "recipe": {
        "title": str,
        "skill_level": "Beginner" | "Intermediate" | "Advanced",
        "cooking_time": "5 min" | "15 min" | "30 min" | "45 min" | "60+ min",
        "special_preferences": List[str],  # "High Protein", "Low Carb", "Spicy", etc.
        "ingredients": List[{icon: str, name: str, amount: str}],
        "instructions": List[str]
    }
}

The agent uses update_session_state tool to modify state, which triggers
STATE_DELTA events that the frontend uses to update the recipe UI.
"""

from agno.agent.agent import Agent
from agno.models.openai import OpenAIResponses

shared_state_agent = Agent(
    name="shared_state",
    model=OpenAIResponses(id="gpt-5.5"),
    session_state={
        "recipe": {
            "title": "Make Your Recipe",
            "skill_level": "Intermediate",
            "cooking_time": "45 min",
            "special_preferences": [],
            "ingredients": [
                {"icon": "🥕", "name": "Carrots", "amount": "3 large, grated"},
                {"icon": "🌾", "name": "All-Purpose Flour", "amount": "2 cups"},
            ],
            "instructions": ["Preheat oven to 350°F (175°C)"],
        }
    },
    add_session_state_to_context=True,
    enable_agentic_state=True,
    instructions="""You are a recipe assistant. The current recipe state is shown in <session_state>.

Use update_session_state to modify the recipe. The structure is:
- title: Recipe name (string)
- skill_level: "Beginner", "Intermediate", or "Advanced"
- cooking_time: "5 min", "15 min", "30 min", "45 min", or "60+ min"
- special_preferences: List of strings like "High Protein", "Low Carb", "Spicy", "Budget-Friendly", "One-Pot Meal", "Vegetarian", "Vegan"
- ingredients: List of objects with {icon: emoji, name: string, amount: string}
- instructions: List of step strings

When modifying:
1. Read the current state from <session_state>
2. Use update_session_state with the fields you want to change
3. Preserve existing values for fields you don't change

Example: To add an ingredient, include the existing ingredients plus the new one.""",
    markdown=True,
)
