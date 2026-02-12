"""
This example demonstrates how to use the ZepTools class to interact with memories stored in Zep.

To get started, please export your Zep API key as an environment variable. You can get your Zep API key from https://app.getzep.com/

export ZEP_API_KEY=<your-zep-api-key>
"""

import asyncio
import time

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.zep import ZepAsyncTools, ZepTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


def run_sync() -> None:
    # Initialize the ZepTools
    sync_zep_tools = ZepTools(
        user_id="agno", session_id="agno-session", add_instructions=True
    )

    # Initialize the Agent
    sync_agent = Agent(
        model=OpenAIChat(),
        tools=[sync_zep_tools],
        dependencies={"memory": sync_zep_tools.get_zep_memory(memory_type="context")},
        add_dependencies_to_context=True,
    )

    # Interact with the Agent so that it can learn about the user
    sync_agent.print_response("My name is John Billings")
    sync_agent.print_response("I live in NYC")
    sync_agent.print_response("I'm going to a concert tomorrow")

    # Allow the memories to sync with Zep database
    time.sleep(10)

    if sync_agent.dependencies:
        # Refresh the context
        sync_agent.dependencies["memory"] = sync_zep_tools.get_zep_memory(
            memory_type="context"
        )

        # Ask the Agent about the user
        sync_agent.print_response("What do you know about me?")


# ---------------------------------------------------------------------------
# Async Variant
# ---------------------------------------------------------------------------

"""
This example demonstrates how to use the ZepAsyncTools class to interact with memories stored in Zep.

To get started, please export your Zep API key as an environment variable. You can get your Zep API key from https://app.getzep.com/

export ZEP_API_KEY=<your-zep-api-key>
"""


async def run_async() -> None:
    # Initialize the ZepAsyncTools
    async_zep_tools = ZepAsyncTools(
        user_id="agno", session_id="agno-async-session", add_instructions=True
    )

    # Initialize the Agent
    async_agent = Agent(
        model=OpenAIChat(),
        tools=[async_zep_tools],
        dependencies={
            "memory": lambda: async_zep_tools.get_zep_memory(memory_type="context"),
        },
        add_dependencies_to_context=True,
    )

    # Interact with the Agent
    await async_agent.aprint_response("My name is John Billings")
    await async_agent.aprint_response("I live in NYC")
    await async_agent.aprint_response("I'm going to a concert tomorrow")

    # Allow the memories to sync with Zep database
    time.sleep(10)

    # Refresh the context
    async_agent.dependencies["memory"] = await async_zep_tools.get_zep_memory(
        memory_type="context"
    )

    # Ask the Agent about the user
    await async_agent.aprint_response("What do you know about me?")


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_sync()
    asyncio.run(run_async())
