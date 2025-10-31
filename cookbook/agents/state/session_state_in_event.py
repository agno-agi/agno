from agno.agent import Agent, RunCompletedEvent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat


def add_item(session_state, item: str) -> str:
    """Add an item to the shopping list."""
    session_state["shopping_list"].append(item)  # type: ignore
    return f"The shopping list is now {session_state['shopping_list']}"  # type: ignore


# Create an Agent that maintains state
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    # Initialize the session state with a counter starting at 0 (this is the default session state for all users)
    session_state={"shopping_list": []},
    db=SqliteDb(db_file="tmp/agents.db"),
    tools=[add_item],
    # You can use variables from the session state in the instructions
    instructions="Current state (shopping list) is: {shopping_list}",
    markdown=True,
)

# Example usage
response = agent.run(
    "Add milk, eggs, and bread to the shopping list", stream=True, stream_events=True
)
for event in response:
    if isinstance(event, RunCompletedEvent):
        print(f"Session state: {event.session_state}")
