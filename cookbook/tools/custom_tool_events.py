"""This example demonstrate how to yield custom events from a custom tool."""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.base import CustomEvent
from agno.tools import tool


# Make sure to set show_result=True for our tool events to be shown.
@tool(show_result=True)
async def custom_tool():
    """Example custom tool that simply yields a custom event."""

    yield CustomEvent(data={"foo": "bar"})


# Setup an Agent and pass our custom tool.
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[custom_tool],
)


async def run_agent():
    # Running the Agent: it should call our custom tool and yield the custom event.
    async for event in agent.arun(
        "Call the tool you are equipped with. We want to see the events it yields.",
        stream=True,
    ):
        if isinstance(event, CustomEvent):
            print(f"✅ Custom event emitted: {event}")


asyncio.run(run_agent())
