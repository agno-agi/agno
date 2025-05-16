from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat


# Define tools to manage our shopping list
def add_item(agent: Agent, item: str) -> str:
    """Add an item to the shopping list and return confirmation."""
    # Add the item if it's not already in the list
    if item.lower() not in [i.lower() for i in agent.session_state["shopping_list"]]:
        agent.session_state["shopping_list"].append(item)
        return f"Added '{item}' to the shopping list"
    else:
        return f"'{item}' is already in the shopping list"


def remove_item(agent: Agent, item: str) -> str:
    """Remove an item from the shopping list by name."""
    # Case-insensitive search
    for i, list_item in enumerate(agent.session_state["shopping_list"]):
        if list_item.lower() == item.lower():
            agent.session_state["shopping_list"].pop(i)
            return f"Removed '{list_item}' from the shopping list"

    return f"'{item}' was not found in the shopping list"


def list_items(agent: Agent) -> str:
    """List all items in the shopping list."""
    shopping_list = agent.session_state["shopping_list"]

    if not shopping_list:
        return "The shopping list is empty."

    items_text = "\n".join([f"- {item}" for item in shopping_list])
    return f"Current shopping list:\n{items_text}"


# Create a Shopping List Manager Agent that maintains state
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    # Initialize the session state with an empty shopping list
    session_state={"shopping_list": []},
    tools=[add_item, remove_item, list_items],
    # You can use variables from the session state in the instructions
    instructions=dedent("""\
        Your job is to manage a shopping list.

        The shopping list starts empty. You can add items, remove items by name, and list all items.

        Current shopping list: {shopping_list}
    """),
    add_state_in_messages=True,
    markdown=True,
)

# Example usage
agent.print_response("Add milk, eggs, and bread to the shopping list", stream=True)
print(f"Session state: {agent.session_state}")

agent.print_response("I got bread", stream=True)
print(f"Session state: {agent.session_state}")

agent.print_response("I need apples and oranges", stream=True)
print(f"Session state: {agent.session_state}")

agent.print_response("whats on my list?", stream=True)
print(f"Session state: {agent.session_state}")

agent.print_response(
    "Clear everything from my list and start over with just bananas and yogurt",
    stream=True,
)
print(f"Session state: {agent.session_state}")
