from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat


def add_item(session_state, item: str) -> str:
    """Add an item to the shopping list."""
    session_state["shopping_list"].append(item)  # type: ignore
    return f"The shopping list is now {session_state['shopping_list']}"  # type: ignore


# Create an Agent that maintains state
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    # Initialize the session state with an empty shopping list (this is the default session state for all users)
    session_state={"shopping_list": []},
    db=SqliteDb(db_file="tmp/agents.db"),
    tools=[add_item],
    # You can use variables from the session state in the instructions
    instructions="Current state (shopping list) is: {shopping_list}",
    markdown=True,
)

# Example usage
agent.print_response("Add milk, eggs, and bread to the shopping list", stream=True)

current_session_state = agent.get_session_state()
current_session_state["shopping_list"].append("chocolate")
agent.update_session_state(current_session_state)

agent.print_response("What's on my list?", stream=True, debug_mode=True)

print(f"Final session state: {agent.get_session_state()}")
