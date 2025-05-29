"""
Simple Chat Agent for AG-UI Demo

This agent is used by the AG-UI demo applications to showcase
the protocol bridge functionality.
"""

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat

# Create the chat agent instance
chat_agent = Agent(
    name="chat_agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions="""
    You are a helpful AI assistant that can have natural conversations.
    Respond in a friendly and informative manner.
    """,
    markdown=True,
    debug_mode=True,
)


# Export the agent
__all__ = ["chat_agent"]
