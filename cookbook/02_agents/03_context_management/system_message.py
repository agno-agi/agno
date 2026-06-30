"""
System Message
=============================

Customize the agent's system message and role.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    # Override the auto-generated system message with a custom one
    system_message="You are a concise technical writer. Always respond in bullet points. Never use more than 3 sentences per bullet point.",
    # Change the role of the system message (default is "system")
    system_message_role="system",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Explain how HTTP cookies work.",
        stream=True,
    )
