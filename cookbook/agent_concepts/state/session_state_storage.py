"""Run `pip install agno openai sqlalchemy` to install dependencies."""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage


# Define a tool that adds an item to the shopping list
def add_item(agent: Agent, item: str) -> str:
    """Add an item to the shopping list."""
    if item not in agent.session_state["shopping_list"]:
        agent.session_state["shopping_list"].append(item)
    return f"The shopping list is now {agent.session_state['shopping_list']}"


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    # Fix the session id to continue the same session across execution cycles
    session_id="fixed_id_for_demo",
    # Initialize the session state with an empty shopping list
    session_state={"shopping_list": []},
    # Add a tool that adds an item to the shopping list
    tools=[add_item],
    # Store the session state in a SQLite database
    storage=SqliteStorage(table_name="agent_sessions", db_file="tmp/data.db"),
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
