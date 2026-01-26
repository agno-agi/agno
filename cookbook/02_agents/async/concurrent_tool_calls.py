"""
This example shows how to use concurrent tool calls in Agno.
You should see the tool calls start and complete in parallel.
"""

from typing import AsyncIterator

from agno.agent import Agent
from agno.models.openai import OpenAIChat


async def get_weather(city: str) -> AsyncIterator[str]:
    import time

    print(f"[{time.time():.2f}] get_weather started")
    from asyncio import sleep

    await sleep(1)  # Fast function - 1 second
    print(f"[{time.time():.2f}] get_weather yielding result")
    yield f"The weather in {city} is sunny"
    print(f"[{time.time():.2f}] get_weather completed")


async def get_activities(city: str) -> AsyncIterator[str]:
    import time

    print(f"[{time.time():.2f}] get_activities started")
    from asyncio import sleep

    await sleep(3)  # Slow function - 3 seconds
    print(f"[{time.time():.2f}] get_activities yielding result")
    yield f"The activities in {city} are swimming, hiking, and biking"
    print(f"[{time.time():.2f}] get_activities completed")


agent = Agent(
    model=OpenAIChat(id="gpt-4.1"),
    tools=[get_weather, get_activities],
)


async def test():
    import time

    print("Starting agent run...")
    start_time = time.time()

    generator = agent.arun(
        "What is the weather and activities in San Francisco?",
        stream=True,
        stream_events=True,
    )
    async for event in generator:
        current_time = time.time() - start_time

        if hasattr(event, "event"):
            if "ToolCallStarted" in event.event:
                print(f"[{current_time:.2f}s] {event.event} - {event.tool.tool_name}")
            elif "ToolCallCompleted" in event.event:
                print(f"[{current_time:.2f}s] {event.event} - {event.tool.tool_name}")
            elif "RunStarted" in event.event:
                print(f"[{current_time:.2f}s] {event.event}")

    total_time = time.time() - start_time
    print(f"Total execution time: {total_time:.2f}s")


if __name__ == "__main__":
    import asyncio

    asyncio.run(test())
