from agno.agent.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.team import Team


# Define tools to manage our shopping list
def add_item(agent: Agent, item: str) -> str:
    """Add an item to the shopping list and return confirmation.

    Args:
        item (str): The item to add to the shopping list.
    """
    # Add the item if it's not already in the list
    if item.lower() not in [
        i.lower() for i in agent.team_session_state["shopping_list"]
    ]:
        agent.team_session_state["shopping_list"].append(item)
        return f"Added '{item}' to the shopping list"
    else:
        return f"'{item}' is already in the shopping list"


def remove_item(agent: Agent, item: str) -> str:
    """Remove an item from the shopping list by name.

    Args:
        item (str): The item to remove from the shopping list.
    """
    # Case-insensitive search
    for i, list_item in enumerate(agent.team_session_state["shopping_list"]):
        if list_item.lower() == item.lower():
            agent.team_session_state["shopping_list"].pop(i)
            return f"Removed '{list_item}' from the shopping list"

    return f"'{item}' was not found in the shopping list. Current shopping list: {agent.team_session_state['shopping_list']}"


def remove_all_items(agent: Agent) -> str:
    """Remove all items from the shopping list."""
    agent.team_session_state["shopping_list"] = []
    return "All items removed from the shopping list"


shopping_list_agent = Agent(
    name="Shopping List Agent",
    role="Manage the shopping list",
    agent_id="shopping_list_manager",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[add_item, remove_item, remove_all_items],
    instructions=[
        "Manage the shopping list by adding and removing items",
        "Always confirm when items are added or removed",
        "If the task is done, update the session state to log the changes & chores you've performed",
    ],
)


# Shopping management team - new layer for handling all shopping list modifications
shopping_mgmt_team = Team(
    name="Shopping Management Team",
    team_id="shopping_management",
    mode="coordinate",
    model=OpenAIChat(id="gpt-4o-mini"),
    show_tool_calls=True,
    members=[shopping_list_agent],
    instructions=[
        "Manage adding and removing items from the shopping list using the Shopping List Agent",
        "Forward requests to add or remove items to the Shopping List Agent",
    ],
)


# New recipe suggestion agent
recipe_agent = Agent(
    name="Recipe Suggester",
    agent_id="recipe_suggester",
    role="Suggest recipes based on available ingredients",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "Suggest recipes that can be made using ingredients from the shopping list",
        "Be creative but practical with recipe suggestions",
        "Consider common pantry items that people usually have available",
    ],
)


def list_items(team: Team) -> str:
    """List all items in the shopping list."""
    shopping_list = team.team_session_state["shopping_list"]

    if not shopping_list:
        return "The shopping list is empty."

    items_text = "\n".join([f"- {item}" for item in shopping_list])
    return f"Current shopping list:\n{items_text}"


def suggest_recipes(team: Team, meal_type: str = "any") -> str:
    """Suggest recipes based on items in the shopping list.

    Args:
        meal_type (str): Type of meal to suggest (breakfast, lunch, dinner, snack, or any)
    """
    shopping_list = team.team_session_state["shopping_list"]

    if not shopping_list:
        return "The shopping list is empty. Add some ingredients first to get recipe suggestions."

    meal_type_str = f" {meal_type}" if meal_type.lower() != "any" else ""

    return f"Based on your shopping list ({', '.join(shopping_list)}), here are some{meal_type_str} recipe ideas for you."


# Create meal planning subteam
meal_planning_team = Team(
    name="Meal Planning Team",
    team_id="meal_planning",
    mode="collaborate",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[recipe_agent],
    instructions=[
        "You are a meal planning team that suggests recipes based on shopping list items",
        "Use the available ingredients to suggest practical and tasty meals",
        "Consider dietary preferences if mentioned by the user",
        "Offer creative ways to use items in the shopping list",
    ],
)


def log_change(team: Team, chore: str, priority: str = "medium") -> str:
    """Add a chore to the session state with priority level.

    Args:
        chore (str): The chore to add to the list
        priority (str): Priority level of the chore (low, medium, high)

    Returns:
        str: Confirmation message
    """
    # Initialize chores list if it doesn't exist
    if "chores" not in team.session_state:
        team.session_state["chores"] = []

    # Validate priority
    valid_priorities = ["low", "medium", "high"]
    if priority.lower() not in valid_priorities:
        priority = "medium"  # Default to medium if invalid

    # Add the chore with timestamp and priority
    from datetime import datetime

    chore_entry = {
        "description": chore,
        "priority": priority.lower(),
        "added_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "completed": False,
    }

    team.session_state["chores"].append(chore_entry)

    return f"Added chore: '{chore}' with {priority} priority"


shopping_team = Team(
    name="Shopping List Team",
    mode="coordinate",
    model=OpenAIChat(id="gpt-4o-mini"),
    team_session_state={"shopping_list": []},
    tools=[list_items, log_change],
    session_state={"chores": []},
    team_id="shopping_list_team",
    members=[
        shopping_mgmt_team,
        meal_planning_team,
    ],
    show_tool_calls=True,
    markdown=True,
    instructions=[
        "You are a team that manages a shopping list & helps plan meals using that list.",
        "If you need to add or remove items from the shopping list, forward the full request to the Shopping Management Team",
        "If you need to list the items in the shopping list, use the list_items tool.",
        "If the user got something from the shopping list, it means it can be removed from the shopping list.",
        "If the user asks for recipe ideas or meal planning, consult the Meal Planning Team.",
        "The Meal Planning Team can access the shopping list to suggest recipes based on available ingredients. Use the suggest_recipes tool.",
        "If the user asks for recipe suggestions, forward the request to the Meal Planning Team.",
        "If the user asks for meal planning ideas, forward the request to the Meal Planning Team.",
        "After each completed task (adding, removing, or modifying the shopping list), use the log_change tool to log exactly what was done. Include specific details like which items were added or removed, and use a priority of 'high' for important changes. For example, if milk was added, log 'Added milk to shopping list'. This creates a clear audit trail of all shopping list activities.",
    ],
    show_members_responses=True,
)

# Example usage
shopping_team.print_response(
    "Add milk, eggs, and bread to the shopping list", stream=True
)
print(f"Session state: {shopping_team.team_session_state}")

shopping_team.print_response("I got bread", stream=True)
print(f"Session state: {shopping_team.team_session_state}")

shopping_team.print_response("I need apples and oranges", stream=True)
print(f"Session state: {shopping_team.team_session_state}")

shopping_team.print_response("whats on my list?", stream=True)
print(f"Session state: {shopping_team.team_session_state}")

# Try the meal planning feature
shopping_team.print_response("What can I make with these ingredients?", stream=True)
print(f"Session state: {shopping_team.team_session_state}")

shopping_team.print_response(
    "Clear everything from my list and start over with just bananas and yogurt",
    stream=True,
)
print(f"Session state: {shopping_team.team_session_state}")


print(f"Team session state: {shopping_team.session_state}")
