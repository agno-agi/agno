"""
Nested Shared State
===================

Demonstrates hierarchical teams that coordinate over shared session state.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.run import RunContext
from agno.team import Team

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/example.db")


def add_item(run_context: RunContext, item: str) -> str:
    """Add an item to the shopping list."""
    if run_context.session_state is None:
        run_context.session_state = {}

    if item.lower() not in [
        i.lower() for i in run_context.session_state["shopping_list"]
    ]:
        run_context.session_state["shopping_list"].append(item)
        return f"Added '{item}' to the shopping list"
    return f"'{item}' is already in the shopping list"


def remove_item(run_context: RunContext, item: str) -> str:
    """Remove an item from the shopping list by name."""
    if run_context.session_state is None:
        run_context.session_state = {}

    for i, list_item in enumerate(run_context.session_state["shopping_list"]):
        if list_item.lower() == item.lower():
            run_context.session_state["shopping_list"].pop(i)
            return f"Removed '{list_item}' from the shopping list"

    return f"'{item}' was not found in the shopping list. Current shopping list: {run_context.session_state['shopping_list']}"


def remove_all_items(run_context: RunContext) -> str:
    """Remove all items from the shopping list."""
    if run_context.session_state is None:
        run_context.session_state = {}

    run_context.session_state["shopping_list"] = []
    return "All items removed from the shopping list"


def get_ingredients(run_context: RunContext) -> str:
    """Retrieve ingredients from the shopping list for recipe suggestions."""
    if run_context.session_state is None:
        run_context.session_state = {}

    shopping_list = run_context.session_state["shopping_list"]

    if not shopping_list:
        return "The shopping list is empty. Add some ingredients first to get recipe suggestions."

    return f"Available ingredients from shopping list: {', '.join(shopping_list)}"


def list_items(run_context: RunContext) -> str:
    """List all items in the shopping list."""
    if run_context.session_state is None:
        run_context.session_state = {}

    shopping_list = run_context.session_state["shopping_list"]

    if not shopping_list:
        return "The shopping list is empty."

    items_text = "\n".join([f"- {item}" for item in shopping_list])
    return f"Current shopping list:\n{items_text}"


def add_chore(run_context: RunContext, chore: str, priority: str = "medium") -> str:
    """Add a chore to the list with priority level."""
    if run_context.session_state is None:
        run_context.session_state = {}

    if "chores" not in run_context.session_state:
        run_context.session_state["chores"] = []

    valid_priorities = ["low", "medium", "high"]
    if priority.lower() not in valid_priorities:
        priority = "medium"

    from datetime import datetime

    chore_entry = {
        "description": chore,
        "priority": priority.lower(),
        "added_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    run_context.session_state["chores"].append(chore_entry)
    return f"Added chore: '{chore}' with {priority} priority"


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
shopping_list_agent = Agent(
    name="Shopping List Agent",
    role="Manage the shopping list",
    id="shopping_list_manager",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[add_item, remove_item, remove_all_items],
    instructions=[
        "Manage the shopping list by adding and removing items",
        "Always confirm when items are added or removed",
        "If the task is done, update the session state to log the changes & chores you've performed",
    ],
)

recipe_agent = Agent(
    name="Recipe Suggester",
    id="recipe_suggester",
    role="Suggest recipes based on available ingredients",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[get_ingredients],
    instructions=[
        "First, use the get_ingredients tool to get the current ingredients from the shopping list",
        "After getting the ingredients, create detailed recipe suggestions based on those ingredients",
        "Create at least 3 different recipe ideas using the available ingredients",
        "For each recipe, include: name, ingredients needed (highlighting which ones are from the shopping list), and brief preparation steps",
        "Be creative but practical with recipe suggestions",
        "Consider common pantry items that people usually have available in addition to shopping list items",
        "Consider dietary preferences if mentioned by the user",
        "If no meal type is specified, suggest a variety of options (breakfast, lunch, dinner, snacks)",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
shopping_mgmt_team = Team(
    name="Shopping Management Team",
    role="Execute shopping list operations",
    id="shopping_management",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[shopping_list_agent],
    instructions=[
        "Manage adding and removing items from the shopping list using the Shopping List Agent",
        "Forward requests to add or remove items to the Shopping List Agent",
    ],
)

meal_planning_team = Team(
    name="Meal Planning Team",
    role="Plan meals based on shopping list items",
    id="meal_planning",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[recipe_agent],
    instructions=[
        "You are a meal planning team that suggests recipes based on shopping list items.",
        "IMPORTANT: When users ask 'What can I make with these ingredients?' or any recipe-related questions, IMMEDIATELY forward the EXACT SAME request to the recipe_agent WITHOUT asking for further information.",
        "DO NOT ask the user for ingredients - the recipe_agent will work with what's already in the shopping list.",
        "Your primary job is to forward recipe requests directly to the recipe_agent without modification.",
    ],
)

shopping_team = Team(
    id="shopping_list_team",
    name="Shopping List Team",
    role="Orchestrate shopping list management and meal planning",
    model=OpenAIResponses(id="gpt-5-mini"),
    session_state={"shopping_list": [], "chores": []},
    tools=[list_items, add_chore],
    db=db,
    members=[shopping_mgmt_team, meal_planning_team],
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


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
def main() -> None:
    print("Example 1: Adding Items to Shopping List")
    print("-" * 50)
    shopping_team.print_response(
        "Add milk, eggs, and bread to the shopping list", stream=True
    )
    print(f"Session state: {shopping_team.get_session_state()}")
    print()

    print("Example 2: Item Consumption & Removal")
    print("-" * 50)
    shopping_team.print_response("I got bread from the store", stream=True)
    print(f"Session state: {shopping_team.get_session_state()}")
    print()

    print("Example 3: Adding Fresh Ingredients")
    print("-" * 50)
    shopping_team.print_response(
        "I need apples and oranges for my fruit salad", stream=True
    )
    print(f"Session state: {shopping_team.get_session_state()}")
    print()

    print("Example 4: Viewing Current Shopping List")
    print("-" * 50)
    shopping_team.print_response("What's on my shopping list right now?", stream=True)
    print(f"Session state: {shopping_team.get_session_state()}")
    print()

    print("Example 5: Recipe Suggestions from Culinary Team")
    print("-" * 50)
    shopping_team.print_response("What can I make with these ingredients?", stream=True)
    print(f"Session state: {shopping_team.get_session_state()}")
    print()

    print("Example 6: Complete List Reset & Restart")
    print("-" * 50)
    shopping_team.print_response(
        "Clear everything from my list and start over with just bananas and yogurt",
        stream=True,
    )
    print(f"Shared Session state: {shopping_team.get_session_state()}")
    print()

    print("Example 7: Quick Recipe Check with New Ingredients")
    print("-" * 50)
    shopping_team.print_response("What healthy breakfast can I make now?", stream=True)
    print()

    print(f"Team Session State: {shopping_team.get_session_state()}")


if __name__ == "__main__":
    main()
