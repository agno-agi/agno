from textwrap import dedent

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.run import RunContext


# Define tools to manage our shopping list
def add_item(run_context: RunContext, item: str) -> str:
    """Add an item to the shopping list and return confirmation."""
    # Add the item if it's not already in the list
    if run_context.session_state is None:
        run_context.session_state = {}

    if item.lower() not in [
        i.lower() for i in run_context.session_state["shopping_list"]
    ]:
        run_context.session_state["shopping_list"].append(item)  # type: ignore
        return f"Added '{item}' to the shopping list"
    else:
        return f"'{item}' is already in the shopping list"


def remove_item(run_context: RunContext, item: str) -> str:
    """Remove an item from the shopping list by name."""
    if run_context.session_state is None:
        run_context.session_state = {}

    # Case-insensitive search
    for i, list_item in enumerate(run_context.session_state["shopping_list"]):
        if list_item.lower() == item.lower():
            run_context.session_state["shopping_list"].pop(i)
            return f"Removed '{list_item}' from the shopping list"

    return f"'{item}' was not found in the shopping list"


def list_items(run_context: RunContext) -> str:
    """List all items in the shopping list."""
    if run_context.session_state is None:
        run_context.session_state = {}

    shopping_list = run_context.session_state["shopping_list"]

    if not shopping_list:
        return "The shopping list is empty."

    items_text = "\n".join([f"- {item}" for item in shopping_list])
    return f"Current shopping list:\n{items_text}"


# Create a Shopping List Manager Agent that maintains state
agent = Agent(
    model=OpenAIChat(id="o3-mini"),
    # Initialize the session state with an empty shopping list (default session state for all sessions)
    session_state={"shopping_list": []},
    db=SqliteDb(db_file="tmp/example.db"),
    tools=[add_item, remove_item, list_items],
    # You can use variables from the session state in the instructions
    instructions=dedent("""\
        Your job is to manage a shopping list.

        The shopping list starts empty. You can add items, remove items by name, and list all items.

        Current shopping list: {shopping_list}
    """),
    markdown=True,
)

# Example usage
agent.print_response("Add milk, eggs, and bread to the shopping list", stream=True)
print(f"Session state: {agent.get_session_state()}")

agent.print_response("I got bread", stream=True)
print(f"Session state: {agent.get_session_state()}")

agent.print_response("I need apples and oranges", stream=True)
print(f"Session state: {agent.get_session_state()}")

agent.print_response("whats on my list?", stream=True)
print(f"Session state: {agent.get_session_state()}")

agent.print_response(
    "Clear everything from my list and start over with just bananas and yogurt",
    stream=True,
)
print(f"Session state: {agent.get_session_state()}")
