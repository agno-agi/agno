"""Test session state management with a simple counter"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat


def increment_counter(session_state) -> str:
    """Increment the counter in session state."""
    # Initialize counter if it doesn't exist
    if "count" not in session_state:
        session_state["count"] = 0

    # Increment the counter
    session_state["count"] += 1

    return f"Counter incremented! Current count: {session_state['count']}"


def get_counter(session_state) -> str:
    """Get the current counter value."""
    count = session_state.get("count", 0)
    return f"Current count: {count}"


# Create an Agent that maintains state
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    # Initialize the session state with a counter starting at 0
    session_state={"count": 0},
    tools=[increment_counter, get_counter],
    # Use variables from the session state in the instructions
    instructions="You can increment and check a counter. Current count is: {count}",
    # Important: Resolve the state in the messages so the agent can see state changes
    resolve_in_context=True,
    markdown=True,
)

# Test the counter functionality
print("Testing counter functionality...")
agent.print_response(
    "Let's increment the counter 3 times and observe the state changes!", stream=True
)
print(f"Final session state: {agent.get_session_state()}")
