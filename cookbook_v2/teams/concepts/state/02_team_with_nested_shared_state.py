"""
This example demonstrates nested shared state with multiple team layers.

The example shows how state can be shared across nested teams and how different
teams can coordinate through shared state management.
"""

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team


# Define tools to manage our shopping list
def add_item(agent: Agent, item: str) -> str:
    """Add an item to the shopping list and return confirmation."""
    if item.lower() not in [
        i.lower() for i in agent.team_session_state["shopping_list"]
    ]:
        agent.team_session_state["shopping_list"].append(item)
        return f"Added '{item}' to the shopping list"
    else:
        return f"'{item}' is already in the shopping list"


def remove_item(agent: Agent, item: str) -> str:
    """Remove an item from the shopping list by name."""
    for i, list_item in enumerate(agent.team_session_state["shopping_list"]):
        if list_item.lower() == item.lower():
            agent.team_session_state["shopping_list"].pop(i)
            return f"Removed '{list_item}' from the shopping list"
    return f"'{item}' was not found in the shopping list"


def list_items(team: Team) -> str:
    """List all items in the shopping list."""
    shopping_list = team.team_session_state["shopping_list"]
    if not shopping_list:
        return "The shopping list is empty."
    items_text = "\n".join([f"- {item}" for item in shopping_list])
    return f"Current shopping list:\n{items_text}"


def get_ingredients(agent: Agent) -> str:
    """Retrieve ingredients from the shopping list for recipe suggestions."""
    shopping_list = agent.team_session_state["shopping_list"]
    if not shopping_list:
        return "The shopping list is empty. Add some ingredients first."
    return f"Available ingredients: {', '.join(shopping_list)}"


def add_chore(team: Team, chore: str, priority: str = "medium") -> str:
    """Add a chore to track completed tasks."""
    from datetime import datetime
    
    chore_entry = {
        "description": chore,
        "priority": priority.lower(),
        "added_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    team.session_state["chores"].append(chore_entry)
    return f"Added chore: '{chore}' with {priority} priority"


# Shopping list management agent
shopping_list_agent = Agent(
    name="Shopping List Agent",
    role="Manage the shopping list",
    agent_id="shopping_list_manager",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[add_item, remove_item],
    instructions=[
        "Manage the shopping list by adding and removing items",
        "Always confirm when items are added or removed",
    ],
)

# Recipe suggestion agent
recipe_agent = Agent(
    name="Recipe Suggester",
    agent_id="recipe_suggester",
    role="Suggest recipes based on available ingredients",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[get_ingredients],
    instructions=[
        "Use get_ingredients to see available ingredients",
        "Create 2-3 recipe suggestions using those ingredients",
        "Include ingredient lists and brief preparation steps",
    ],
)

# Shopping management team (nested layer)
shopping_mgmt_team = Team(
    name="Shopping Management Team",
    team_id="shopping_management",
    mode="coordinate",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[shopping_list_agent],
    instructions=[
        "Handle shopping list modifications using the Shopping List Agent",
    ],
)

# Meal planning team (nested layer)
meal_planning_team = Team(
    name="Meal Planning Team",
    team_id="meal_planning",
    mode="coordinate",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[recipe_agent],
    instructions=[
        "Provide recipe suggestions using available ingredients",
    ],
)

# Main shopping team with nested teams
shopping_team = Team(
    name="Shopping List Team",
    mode="coordinate",
    model=OpenAIChat(id="gpt-4o-mini"),
    team_session_state={"shopping_list": []},  # Shared shopping list
    session_state={"chores": []},  # Team-specific state for chores
    tools=[list_items, add_chore],
    team_id="shopping_list_team",
    members=[
        shopping_mgmt_team,
        meal_planning_team,
    ],
    markdown=True,
    instructions=[
        "You manage a shopping list and help plan meals.",
        "For shopping list changes, forward to Shopping Management Team.",
        "For recipe requests, forward to Meal Planning Team.",
        "Use add_chore to log completed tasks.",
    ],
    show_members_responses=True,
)

# Example usage demonstrating nested shared state
shopping_team.print_response("Add milk, eggs, and bread to the shopping list", stream=True)
print(f"Shopping list state: {shopping_team.team_session_state}")

shopping_team.print_response("What can I make with these ingredients?", stream=True)
print(f"Shopping list state: {shopping_team.team_session_state}")

shopping_team.print_response("I got the milk", stream=True)
print(f"Shopping list state: {shopping_team.team_session_state}")

print(f"Team chores state: {shopping_team.session_state}")
