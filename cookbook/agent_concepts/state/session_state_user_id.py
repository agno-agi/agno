"""
This example demonstrates how to maintain state for each user in a multi-user environment.

The shopping list is stored in a dictionary, organized by user ID and session ID.

Agno automatically creates the "current_user_id" and "current_session_id" variables in the session state.

You can access these variables in your functions using the `agent.session_state` dictionary.
"""

import json

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.utils.log import log_info

# In-memory database to store user shopping lists
# Organized by user ID and session ID
shopping_list = {}


def add_item(agent: Agent, item: str) -> str:
    """Add an item to the current user's shopping list."""
    current_user_id = agent.session_state["current_user_id"]
    current_session_id = agent.session_state["current_session_id"]
    shopping_list.setdefault(current_user_id, {}).setdefault(
        current_session_id, []
    ).append(item)
    return f"Item {item} added to the shopping list"


def remove_item(agent: Agent, item: str) -> str:
    """Remove an item from the current user's shopping list."""
    current_user_id = agent.session_state["current_user_id"]
    current_session_id = agent.session_state["current_session_id"]

    if (
        current_user_id not in shopping_list
        or current_session_id not in shopping_list[current_user_id]
    ):
        return f"No shopping list found for user {current_user_id} and session {current_session_id}"

    if item not in shopping_list[current_user_id][current_session_id]:
        return f"Item '{item}' not found in the shopping list for user {current_user_id} and session {current_session_id}"

    shopping_list[current_user_id][current_session_id].remove(item)
    return f"Item {item} removed from the shopping list"


def get_shopping_list(agent: Agent) -> str:
    """Get the current user's shopping list."""
    current_user_id = agent.session_state["current_user_id"]
    current_session_id = agent.session_state["current_session_id"]
    return f"Shopping list for user {current_user_id} and session {current_session_id}: \n{json.dumps(shopping_list[current_user_id][current_session_id], indent=2)}"


# Create an Agent that maintains state
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[add_item, remove_item, get_shopping_list],
    # Reference the in-memory database
    instructions=[
        "Current User ID: {current_user_id}",
        "Current Session ID: {current_session_id}",
    ],
    # Important: Add the state in the instructions
    add_state_in_messages=True,
    markdown=True,
)

user_id_1 = "john_doe"
user_id_2 = "mark_smith"
user_id_3 = "carmen_sandiago"

# Example usage
agent.print_response(
    "Add milk, eggs, and bread to the shopping list",
    stream=True,
    user_id=user_id_1,
    session_id="user_1_session_1",
)
agent.print_response(
    "Add tacos to the shopping list",
    stream=True,
    user_id=user_id_2,
    session_id="user_2_session_1",
)
agent.print_response(
    "Add apples and grapesto the shopping list",
    stream=True,
    user_id=user_id_3,
    session_id="user_3_session_1",
)
agent.print_response(
    "Remove milk from the shopping list",
    stream=True,
    user_id=user_id_1,
    session_id="user_1_session_1",
)
agent.print_response(
    "Add minced beef to the shopping list",
    stream=True,
    user_id=user_id_2,
    session_id="user_2_session_1",
)

# What is on Mark Smith's shopping list?
agent.print_response(
    "What is on Mark Smith's shopping list?",
    stream=True,
    user_id=user_id_2,
    session_id="user_2_session_1",
)

# New session, so new shopping list
agent.print_response(
    "Add chicken and soup to my list.",
    stream=True,
    user_id=user_id_2,
    session_id="user_3_session_2",
)

print(f"Final shopping lists: \n{json.dumps(shopping_list, indent=2)}")
