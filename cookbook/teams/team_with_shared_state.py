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
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[add_item, remove_item, remove_all_items],
    instructions=[
        "Find information about the company in the wikipedia",
    ],
)


def list_items(team: Team) -> str:
    """List all items in the shopping list."""
    shopping_list = team.session_state["shopping_list"]

    if not shopping_list:
        return "The shopping list is empty."

    items_text = "\n".join([f"- {item}" for item in shopping_list])
    return f"Current shopping list:\n{items_text}"


shopping_team = Team(
    name="Shopping List Team",
    mode="coordinate",
    model=OpenAIChat(id="gpt-4o-mini"),
    session_state={"shopping_list": []},
    tools=[list_items],
    members=[
        shopping_list_agent,
    ],
    show_tool_calls=True,
    markdown=True,
    instructions=[
        "You are a team that manages a shopping list.",
        "If you need to add or remove items from the shopping list, forward the full request to the shopping list agent (don't break it up into multiple requests).",
        "If you need to list the items in the shopping list, use the list_items tool.",
        "If the user got something from the shopping list, it means it can be removed from the shopping list.",
    ],
    show_members_responses=True,
)

# Example usage
shopping_team.print_response(
    "Add milk, eggs, and bread to the shopping list", stream=True
)
print(f"Session state: {shopping_team.session_state}")

shopping_team.print_response("I got bread", stream=True)
print(f"Session state: {shopping_team.session_state}")

shopping_team.print_response("I need apples and oranges", stream=True)
print(f"Session state: {shopping_team.session_state}")

shopping_team.print_response("whats on my list?", stream=True)
print(f"Session state: {shopping_team.session_state}")

shopping_team.print_response(
    "Clear everything from my list and start over with just bananas and yogurt",
    stream=True,
)
print(f"Session state: {shopping_team.session_state}")
