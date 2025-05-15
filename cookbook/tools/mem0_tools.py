"""
This example demonstrates how to use the Mem0Toolkit class to interact with memories stored in Mem0.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mem0 import Mem0Toolkit

USER_ID = "john_billings"
SESSION_ID = "session1"

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[Mem0Toolkit()],
    user_id=USER_ID,
    session_id=SESSION_ID,
    add_state_in_messages=True,
    markdown=True,
    instructions=dedent(
        """
        You have an evolving memory of this user. Proactively capture new personal details,
        preferences, plans, and relevant context the user shares, and naturally bring them up
        in later conversation. Before answering questions about past details, recall from your memory
        to provide precise and personalized responses. Keep your memory concise: store only
        meaningful information that enhances long-term dialogue. If the user asks to start fresh,
        clear all remembered information and proceed anew.
        """
    ),
    show_tool_calls=True,
)

agent.print_response("I live in NYC")
agent.print_response("NYC is a big city")
agent.print_response("NYC has a famous Brooklyn Bridge")
agent.print_response("Delete all my memories")
agent.print_response("I moved to LA")
agent.print_response("I'm going to a Taylor Swift concert tomorrow")
agent.print_response("Summarize all the details of the conversation")
agent.print_response("What is the name of the concert I am going to?")
