"""This example demonstrate how to yield custom events from a custom tool."""

import asyncio
from dataclasses import dataclass
from typing import Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import CustomEvent
from agno.tools import tool


# Our custom event, extending the CustomEvent class
@dataclass
class CustomerProfileEvent(CustomEvent):
    """CustomEvent for customer profile."""

    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None


# Our custom tool
@tool()
async def get_customer_profile():
    """Example custom tool that simply yields a custom event."""

    yield CustomerProfileEvent(
        customer_name="John Doe",
        customer_email="john.doe@example.com",
        customer_phone="1234567890",
    )


# Setup an Agent with our custom tool.
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[get_customer_profile],
    instructions="Your task is to retrieve customer profiles for the user.",
)


async def run_agent():
    # Running the Agent: it should call our custom tool and yield the custom event
    async for event in agent.arun(
        "Hello, can you get me the customer profile for customer with ID 123?",
        stream=True,
    ):
        if isinstance(event, CustomEvent):
            print(f"✅ Custom event emitted: {event}")


asyncio.run(run_agent())
