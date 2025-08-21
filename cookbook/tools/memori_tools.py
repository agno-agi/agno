"""
This example demonstrates how to use the Memori toolkit with Agno agents
for persistent memory across conversations.

To get started:
pip install memorisdk

"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.memori import MemoriTools

# Create an agent with persistent memory using Memori
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        MemoriTools(
            database_connect="sqlite:///memori_cookbook_memory.db",
            namespace="cookbook_agent",
        )
    ],
    instructions=dedent(
        """\
        Instructions:
        1. First, search your memory for relevant past conversations using the memori tool
        2. Use any relevant memories to provide a personalized response
        3. Provide a helpful and contextual answer
        4. Be conversational and friendly

        If this is the first conversation, introduce yourself and explain that you'll remember our conversations.
    """
    ),
    show_tool_calls=True,
    markdown=True,
)

# Build memory through conversation
agent.print_response("I'm a Python developer and I love building web applications")

# Memory recall
agent.print_response("What do you remember about my programming background?")

# Check memory statistics
agent.print_response("Show me your memory statistics")

# More examples:
# agent.print_response("I prefer working in the morning hours, around 8-11 AM")
# agent.print_response("What were my productivity preferences again?")
# agent.print_response("I just learned React and really enjoyed it!")
# agent.print_response("Search your memory for all my technology preferences")
