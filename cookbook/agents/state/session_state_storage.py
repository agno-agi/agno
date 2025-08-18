"""Run `pip install agno openai sqlalchemy` to install dependencies."""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat


# Define a tool that adds an item to the shopping list
def add_item(agent: Agent, item: str) -> str:
    """Add an item to the shopping list."""
    agent.session_state["shopping_list"].append(item)  # type: ignore
    return f"The shopping list is now {agent.session_state['shopping_list']}"  # type: ignore


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    # Fix the session id to continue the same session across execution cycles
    session_id="fixed_id_for_demo",
    # Initialize the session state with an empty shopping list
    session_state={"shopping_list": []},
    # Add a tool that adds an item to the shopping list
    tools=[add_item],
    # Store the session state in a SQLite database
    db=SqliteDb(db_file="tmp/data.db"),
    # Add the current shopping list from the state in the instructions
    instructions="Current shopping list is: {shopping_list}",
    # Important: Set `add_state_in_messages=True`
    # to make `{shopping_list}` available in the instructions
    add_state_in_messages=True,
    markdown=True,
)

# Example usage
agent.print_response("What's on my shopping list?", stream=True)
print(f"Session state: {agent.session_state}")
agent.print_response("Add milk, eggs, and bread", stream=True)
print(f"Session state: {agent.session_state}")
