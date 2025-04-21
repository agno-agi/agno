"""
This example demonstrates how to use the ZepAsyncTools class to interact with memories stored in Zep.

To get started, please export your Zep API key as an environment variable. You can get your Zep API key from https://app.getzep.com/

export ZEP_API_KEY=<your-zep-api-key>
"""

import asyncio
import time

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.zep import ZepAsyncTools


async def main():
    # Initialize the ZepAsyncTools
    zep_tools = ZepAsyncTools(
        user_id="agno", session_id="agno-async-session", add_instructions=True
    )

    # Initialize the Agent
    agent = Agent(
        model=OpenAIChat(),
        tools=[zep_tools],
        context={
            "memory": lambda: zep_tools.get_zep_memory(memory_type="context"),
        },
        add_context=True,
    )

    # Interact with the Agent
    await agent.aprint_response("My name is John Billings")
    await agent.aprint_response("I live in NYC")
    await agent.aprint_response("I'm going to a concert tomorrow")

    # Allow the memories to sync with Zep database
    time.sleep(10)

    # Refresh the context
    agent.context["memory"] = await zep_tools.get_zep_memory(memory_type="context")

    # Ask the Agent about the user
    await agent.aprint_response("What do you know about me?")


if __name__ == "__main__":
    asyncio.run(main())
