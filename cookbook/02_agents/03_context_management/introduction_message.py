"""
Introduction Message
=============================

Use the introduction parameter to set an initial greeting message.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    # The introduction is sent as the agent's first message in a conversation
    introduction="Hello! I'm your coding assistant. I can help you write, debug, and explain code. What would you like to work on?",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # The introduction message is available as a property
    print("Introduction:", agent.introduction)
    print()
    agent.print_response(
        "Help me write a Python function to check if a string is a palindrome.",
        stream=True,
    )
