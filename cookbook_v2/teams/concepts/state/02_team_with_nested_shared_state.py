"""
This example demonstrates the nested Team functionality in a hierarchical team structure.
Each team and agent has a clearly defined role that guides their behavior and specialization:

Team Hierarchy & Roles:
├── Shopping List Team (Orchestrator)
│   Role: "Orchestrate comprehensive shopping list management and meal planning"
│   ├── Shopping Management Team (Operations Specialist)
│   │   Role: "Execute precise shopping list operations through delegation"
│   │   └── Shopping List Agent
│   │       Role: "Maintain and modify the shopping list with precision and accuracy"
│   └── Meal Planning Team (Culinary Expert)
│       Role: "Transform shopping list ingredients into creative meal suggestions"
│       └── Recipe Suggester Agent
│           Role: "Create innovative and practical recipe suggestions"

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
    role="Execute shopping list operations",
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
    role="Plan meals based on shopping list items",
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
    role="Orchestrate shopping list management and meal planning",
    mode="coordinate",
    model=OpenAIChat(id="gpt-4o-mini"),
    team_session_state={"shopping_list": []},  # Shared shopping list
    session_state={"chores": []},  # Team-specific state for chores
    tools=[list_items, add_chore],
    members=[
        shopping_mgmt_team,
        meal_planning_team,
    ],
    markdown=True,
    instructions=[
        "You are the orchestration layer for a comprehensive shopping and meal planning ecosystem",
        "If you need to add or remove items from the shopping list, forward the full request to the Shopping Management Team",
        "IMPORTANT: If the user asks about recipes or what they can make with ingredients, IMMEDIATELY forward the EXACT request to the meal_planning_team with NO additional questions",
        "Example: When user asks 'What can I make with these ingredients?', you should simply forward this exact request to meal_planning_team without asking for more information",
        "If you need to list the items in the shopping list, use the list_items tool",
        "If the user got something from the shopping list, it means it can be removed from the shopping list",
        "After each completed task, use the add_chore tool to log exactly what was done with high priority",
        "Provide a seamless experience by leveraging your specialized teams for their expertise",
    ],
    show_members_responses=True,
)

# =============================================================================
# DEMONSTRATION
# =============================================================================

# Example 1: Adding items (demonstrates role-based delegation)
print("Example 1: Adding Items to Shopping List")
print("-" * 50)
shopping_team.print_response(
    "Add milk, eggs, and bread to the shopping list", stream=True
)
print(f"Session state: {shopping_team.team_session_state}")
print()

# Example 2: Item consumption and removal
print("Example 2: Item Consumption & Removal")
print("-" * 50)
shopping_team.print_response("I got bread from the store", stream=True)
print(f"Session state: {shopping_team.team_session_state}")
print()

# Example 3: Adding more ingredients
print("Example 3: Adding Fresh Ingredients")
print("-" * 50)
shopping_team.print_response(
    "I need apples and oranges for my fruit salad", stream=True
)
print(f"Session state: {shopping_team.team_session_state}")
print()

# Example 4: Listing current items
print("Example 4: Viewing Current Shopping List")
print("-" * 50)
shopping_team.print_response("What's on my shopping list right now?", stream=True)
print(f"Session state: {shopping_team.team_session_state}")
print()

# Example 5: Recipe suggestions (demonstrates culinary expertise role)
print("Example 5: Recipe Suggestions from Culinary Team")
print("-" * 50)
shopping_team.print_response("What can I make with these ingredients?", stream=True)
print(f"Session state: {shopping_team.team_session_state}")
print()

# Example 6: Complete list management
print("Example 6: Complete List Reset & Restart")
print("-" * 50)
shopping_team.print_response(
    "Clear everything from my list and start over with just bananas and yogurt",
    stream=True,
)
print(f"Shared Session state: {shopping_team.team_session_state}")
print()

# Example 7: Quick recipe check with new ingredients
print("Example 7: Quick Recipe Check with New Ingredients")
print("-" * 50)
shopping_team.print_response("What healthy breakfast can I make now?", stream=True)
print()

print(f"Team Session State: {shopping_team.team_session_state}")
