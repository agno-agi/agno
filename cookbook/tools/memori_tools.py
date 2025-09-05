"""
This example demonstrates how to use the Memori ToolKit with Agno Agents,
for persistent memory across conversations.

Run: `pip install memorisdk` to install dependencies
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.memori import MemoriTools

# Setup the Memori ToolKit
memori_tools = MemoriTools(
    database_connect="sqlite:///memori_cookbook_memory.db",
    namespace="cookbook_agent",
    # enable_* flags are optional; defaults enable all small functions
    enable_search_memory=True,
    enable_record_conversation=True,
    enable_get_memory_stats=True,
)

# Setup your Agent
agent = Agent(
    # Add the Memori ToolKit to the Agent
    tools=[memori_tools],
    model=OpenAIChat(id="gpt-4o"),
    markdown=True,
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
)

# Run your Agent
agent.print_response("I'm a Python developer and I love building web applications")

# Thanks to the Memori ToolKit, your Agent can now remember the conversation:
agent.print_response("What do you remember about my programming background?")

# Using the Memori ToolKit, your Agent also gains access to memory statistics:
agent.print_response("Show me your memory statistics")


# More examples:
#
# agent.print_response("I prefer working in the morning hours, around 8-11 AM")
# agent.print_response("What were my productivity preferences again?")
# agent.print_response("I just learned React and really enjoyed it!")
# agent.print_response("Search your memory for all my technology preferences")
