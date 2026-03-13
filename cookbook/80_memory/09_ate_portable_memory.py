"""
Use portable .mv2 memory with an Agno agent via the ate CLI.

Requirements:
    pip install agno ate-robotics

The agent gets tools to add, search, list, and export memories
stored in a single portable .mv2 file.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.ate_memory import AteMemoryTools

# Create memory tools pointing at a .mv2 file
memory_tools = AteMemoryTools(memory_path="./my-agent-memory.mv2")

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[memory_tools],
    instructions=[
        "You are a helpful assistant with persistent memory.",
        "Use ate memory tools to store important facts and recall them later.",
        "When the user shares personal info, store it with add_memory.",
        "When answering questions, search your memory first with search_memory.",
    ],
    markdown=True,
)

if __name__ == "__main__":
    # First interaction — store some facts
    asyncio.run(
        agent.aprint_response(
            "My name is Alice and I'm working on a robotics project using ROS2. "
            "I prefer Python over C++ and my deadline is March 15.",
            stream=True,
            user_id="alice",
        )
    )

    # Second interaction — recall from memory
    asyncio.run(
        agent.aprint_response(
            "What do you remember about my project?",
            stream=True,
            user_id="alice",
        )
    )
